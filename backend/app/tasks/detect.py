import json
import logging
import math
import random
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select, update
from pydantic import BaseModel
from google.genai import errors, types

from app.db.models import Clip, RankingRun, Transcript, Moment, VideoStatus
from app.services.gemini_client import client
from app.tasks.render import DEFAULT_FORMAT
from app.workers.contract import TaskContext, job_contract
from app.workers.queues import io_queue
from app.services.r2_client import download_bytes

logger = logging.getLogger(__name__)

GEMINI_MODEL = "gemini-2.5-flash"
# Per-million-token prices for GEMINI_MODEL. VERIFY against current Gemini pricing
# before trusting est_cost_usd — these drift and feed billing rollups.
GEMINI_IN_PER_MTOK = 0.30
GEMINI_OUT_PER_MTOK = 2.50
GEMINI_MAX_ATTEMPTS = 3
# Codes worth a local retry: 429 (rate limit) and the transient 5xx family Gemini returns
# under load. A 503 here is what sank a whole detect job on 2026-07-18.
GEMINI_RETRY_CODES = {429, 500, 502, 503, 504}
PROMPT_VERSION = "detect-v3"
MAX_MOMENTS_PER_SECTION = 3
MAX_SECTIONS = 40
MAX_SECTION_LEN = 300.0     # a section covers at most 5 min, so no long stretch competes
                            # for one section's 3-clip budget; enforced by splitting after
MAX_TOTAL_MOMENTS = 60
MIN_LEN=20
MAX_LEN=120
SENT_GAP=0.6
# Breathing room added on both sides of the substance the model picked. Clips that open
# exactly on the first word and cut on the last one read as chopped, and the payoff never
# lands. CORE_* is the window the model is asked for; MIN_LEN/MAX_LEN bound the result
# once the cushion is on.
CUSHION=5.0
CORE_MIN=MIN_LEN - 2 * CUSHION
CORE_MAX=MAX_LEN - 2 * CUSHION
SILENCE_EXTEND=2.0
SNAP_WINDOW=3.0     # max seconds a boundary search may travel from the cited timestamp
LOUD_DB_OVER_MEDIAN = 8.0
LOUD_MIN_DUR = 1.0
OVERLAPPING_RATIO = 0.4
SECTION_WORKERS = 4

# ─── FREE-TIER THROTTLE ──────────────────────────────────────────────────────────────
# WHY THIS EXISTS: Gemini's FREE tier caps gemini-2.5-flash at 5 requests/minute per model.
# detect fires 1 segment call + up to MAX_SECTIONS section calls across SECTION_WORKERS
# threads, which blows past 5 RPM instantly and 429s the whole job (RESOURCE_EXHAUSTED).
# This gate spaces every Gemini request GEMINI_MIN_INTERVAL_S apart, across ALL workers, so
# we stay under the free-tier limit. It is a workaround for being on the free tier, nothing
# more.
#
# TO REMOVE ONCE ON A PAID TIER: set GEMINI_MIN_INTERVAL_S = 0 (Tier 1 = ~1000 RPM, so
# pacing only makes detect slower for no benefit). At interval 0 the gate is a no-op and you
# can delete this whole block plus the _throttle() call in _gemini_with_retry if you want it
# gone entirely. Search "FREE-TIER THROTTLE" to find every piece.
GEMINI_MIN_INTERVAL_S = 13.0
_throttle_lock = threading.Lock()
_last_call_at = 0.0


def _throttle() -> None:
    """Block until at least GEMINI_MIN_INTERVAL_S has passed since the last Gemini request,
    counting requests from every section worker. See the FREE-TIER THROTTLE note above."""
    if GEMINI_MIN_INTERVAL_S <= 0:
        return
    global _last_call_at
    with _throttle_lock:
        wait = _last_call_at + GEMINI_MIN_INTERVAL_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_call_at = time.monotonic()
# Every kept moment renders without the user asking. This used to be a top-3 slice because
# each render pulled down the whole source, so fifteen clips meant fifteen full downloads.
# render now reads its window straight out of R2 over HTTP, so the cost is roughly one
# clip's worth of bytes per clip.
AUTO_RENDER_CAPTIONS = False

SECTION_SYSTEM_INSTRUCTIONS = f"""You split a timestamped video transcript into consecutive \
topical sections that together cover the whole video. Each section is one coherent subject or \
segment of the conversation — a place a viewer would say "now they're talking about X".

Rules:
- start/end MUST be timestamps that appear in the script (use the [h:mm:ss] markers).
- Sections run back to back and tile the whole timeline: each section's start is the previous \
section's end. Do not leave gaps and do not overlap.
- Keep each section under {MAX_SECTION_LEN / 60:.0f} minutes. Split a long topic into parts if it runs longer.
- Return AT MOST {MAX_SECTIONS} sections. Prefer a handful of meaningful sections over many tiny ones.
- topic: a short phrase naming what the section is about.
Return only what the schema asks for."""

SYSTEM_INSTRUCTIONS = f"""You find the most clip-worthy moments in a video from its \
timestamped transcript. The script below interleaves spoken lines with energy markers:
  [h:mm:ss] <text>      a spoken line, starting at that timestamp
  <SILENCE Ns>          a pause of N seconds (dramatic beat, or dead air)
  <LOUD +NdB a-b>       a burst of loud audio between a and b (laughter, reaction, emphasis)

Return AT MOST {MAX_MOMENTS_PER_SECTION} moments, each a self-contained clip that would work posted alone.

Rules:
- start/end MUST be timestamps that appear in the script (use the [h:mm:ss] markers).
- Mark only the substance of the moment: between {CORE_MIN:.0f} and {CORE_MAX:.0f} seconds. \
Do not exceed {CORE_MAX:.0f}. About {CUSHION:.0f} seconds of lead-in and follow-through get \
added to each side afterwards, so you do not need to pad the timestamps yourself.
- Begin on a clean thought, not mid-sentence.
- End AFTER the payoff has fully landed, not on the last word of it. The punchline, the \
reaction to it, and the beat that follows all belong inside the clip. A moment that stops \
the instant the point is made feels cut off, so carry the end through to the next natural \
stopping place. Never end mid-sentence or mid-list.
- Skip moments whose payoff is still unfinished when the interesting part runs out of room. \
A complete smaller moment beats a truncated big one.
- Prefer moments with a strong hook in the first few seconds; energy markers are signal, not filler.
- Score each 0..1: hook (grabs attention fast), completeness (stands alone), \
shareability (worth reposting), visual (implied on-screen interest).
- transcript_excerpt: the verbatim spoken text spanning the clip.
- reason: one sentence on why it earns its place. title: a punchy, specific caption.
Return only what the schema asks for. If nothing qualifies, return an empty list."""


class MomentOut(BaseModel):
    start: str            # "h:mm:ss" as cited in the annotated script
    end: str
    type: str
    title: str
    reason: str
    hook: float           # 0..1
    completeness: float
    shareability: float
    visual: float
    transcript_excerpt: str

class SectionOut(BaseModel):
    start: str
    end: str
    topic: str




def _fmt_ts(sec) -> str:
    """Seconds -> 'h:mm:ss' for the transcript lines the LLM cites."""
    sec = max(0, int(float(sec)))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def _parse_ts(ts) -> float:
    """'h:mm:ss' / 'm:ss' / bare seconds -> float seconds (inverse of _fmt_ts)."""
    sec = 0.0
    for part in str(ts).split(":"):
        sec = sec * 60 + float(part)
    return sec


def _detect_done(ctx):
    """Only a *completed* run counts as done.

    The run row is committed as status="running" before the Gemini call (so the task
    holds no transaction across it), which means a failed attempt leaves a row behind.
    Checking for mere existence would make a retry skip detect and report success on a
    video that has no moments at all.
    """
    stmt = select(RankingRun).where(
        RankingRun.video_id == ctx.video.id,
        RankingRun.status == "done",
    )
    with ctx.tx() as db:
        return db.execute(stmt).scalars().first() is not None


def _load_inputs(ctx):
    video = ctx.video

    # Read the row, then close the transaction before the R2 downloads below: they are
    # network IO and must not run inside a transaction.
    with ctx.tx() as db:
        transcript = db.execute(
            select(Transcript).where(Transcript.video_id == video.id)
        ).scalar_one_or_none()

        if transcript is None:
            raise RuntimeError(f"No transcript for video {video.id}; transcribe must run first")

        words_r2_key = transcript.words_r2_key
        segments = transcript.segments

    words = json.loads(download_bytes(words_r2_key))                     # [{word,start,end}, ...]

    features = {"rms": [], "silences": []}                               # defensive default
    features_key = (video.artifacts or {}).get("features_key")
    if features_key:
        features = json.loads(download_bytes(features_key))              # {rms:[...], silences:[...]}

    # Return segments rather than the Transcript row: it is detached once the block above
    # closes, and handing back a live-looking ORM object invites a lazy load that would
    # fail with no session to load from.
    return segments, words, features


def _loud_spikes(rms):
    """Contiguous windows whose energy is >= LOUD_DB_OVER_MEDIAN above the recording's
    median. Returns (start_sec, end_sec, peak_db_above_median) per merged run."""
    if not rms:
        return []
    median = statistics.median(r["rms_db"] for r in rms)
    threshold = median + LOUD_DB_OVER_MEDIAN

    spikes, cur = [], None   # cur = [start, end, peak_rms]
    for r in rms:
        if r["rms_db"] >= threshold:
            if cur is None:
                cur = [r["t"], r["t"], r["rms_db"]]
            else:
                cur[1] = r["t"]
                cur[2] = max(cur[2], r["rms_db"])
        elif cur is not None:
            spikes.append(cur)
            cur = None
    if cur is not None:
        spikes.append(cur)

    return [
        (s, e, round(peak - median, 1))
        for s, e, peak in spikes
        if e - s >= LOUD_MIN_DUR
    ]

def _gemini_with_retry(call):
    """Run a Gemini call, retrying transient throttle/5xx locally before letting it abort
    the job. `call` is a zero-arg callable so the request is re-issued fresh each attempt.

    detect fans out to one segment call plus up to MAX_SECTIONS section calls, so any single
    503 would otherwise sink the whole job and force RQ to re-run all of them. Retrying just
    the one throttled call keeps the other sections' work; only a call still failing after
    GEMINI_MAX_ATTEMPTS falls through to the whole-job retry (a genuinely saturated provider).
    """
    for attempt in range(1, GEMINI_MAX_ATTEMPTS + 1):
        try:
            _throttle()   # FREE-TIER THROTTLE: pace requests under the 5 RPM free-tier cap
            return call()
        except errors.APIError as e:
            if e.code not in GEMINI_RETRY_CODES or attempt == GEMINI_MAX_ATTEMPTS:
                raise
            # Exponential base plus jitter, so the concurrent section calls do not all wake
            # and re-hit the provider in lockstep while it is still saturated.
            delay = 2 ** attempt + random.uniform(0, 1)
            logger.warning("detect: gemini %s, retry %d/%d in %.1fs",
                           e.code, attempt, GEMINI_MAX_ATTEMPTS, delay)
            time.sleep(delay)


def _segment_transcript(full_script) -> tuple[list[SectionOut], object]:
    """Pass 1: split the whole annotated script into consecutive topical sections that tile
    the timeline. Cheap output (just boundaries), so this is one call over the full script."""
    response = _gemini_with_retry(lambda: client.models.generate_content(
        model=GEMINI_MODEL,
        contents=f"{SECTION_SYSTEM_INSTRUCTIONS}\n\n---\n\n{full_script}",
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=list[SectionOut],
            temperature=0.2,
        ),
    ))
    if response.parsed is None:
        raise RuntimeError(f"Gemini returned no parseable sections: {response.text!r}")
    return response.parsed, response.usage_metadata


def _cap_section_lengths(sections, max_len):
    """Guarantee no section is longer than max_len by splitting oversized ones into even,
    consecutive sub-windows. The prompt asks the model for this, but it will not obey
    reliably, and a too-long section would squeeze a big stretch into one section's clip
    budget. Sub-windows keep the parent topic and tile the same [start, end]."""
    capped: list[SectionOut] = []
    for sec in sections:
        start, end = _parse_ts(sec.start), _parse_ts(sec.end)
        span = end - start
        if span <= max_len:
            capped.append(sec)
            continue
        n = math.ceil(span / max_len)
        step = span / n
        for i in range(n):
            sub_start = start + i * step
            sub_end = end if i == n - 1 else start + (i + 1) * step
            capped.append(SectionOut(
                start=_fmt_ts(sub_start), end=_fmt_ts(sub_end), topic=sec.topic
            ))
    return capped


def _slice_annotated(segments, features, start, end):
    seg_slice = [s for s in segments if start <= float(s["start"]) <= end]
    feat_slice = {
        "silences": [x for x in features.get("silences", []) if start <= float(x["silence_start"]) <= end],
        "rms":      [r for r in features.get("rms", [])      if start <= float(r["t"]) <= end],
    }
    return _build_annotated(seg_slice, feat_slice)   # <-- still used


def _build_annotated(segments, features) -> str:
    """Merge speech, silences, and loud spikes into one time-sorted, timestamped script
    for the ranking prompt. Degrades to plain [h:mm:ss] lines when features are empty.

    Builds a uniform list of (time, order, line) events, sorts once, then joins — so the
    sort does the interleaving instead of hand-written ordering logic. `order` breaks
    ties so an energy marker renders just before a spoken line at the same instant.
    """
    events: list[tuple[float, int, str]] = []

    for s in segments:
        text = (s.get("text") or "").strip()
        if text:
            start = float(s["start"])
            events.append((start, 1, f"[{_fmt_ts(start)}] {text}"))

    for sil in features.get("silences", []):
        start = float(sil["silence_start"])
        dur = float(sil["silence_end"]) - start
        if dur >= 1.0:                                   # skip inter-word gaps
            events.append((start, 0, f"<SILENCE {dur:.1f}s>"))

    for start, end, peak_db in _loud_spikes(features.get("rms", [])):
        events.append((start, 0, f"<LOUD +{peak_db:.0f}dB {_fmt_ts(start)}-{_fmt_ts(end)}>"))

    events.sort(key=lambda e: (e[0], e[1]))
    return "\n".join(line for _, _, line in events)

def _extract(prompt_inject, topic=None) -> tuple[list[MomentOut], object | None]:
    """The clip-finding Gemini call over one annotated script. Returns (moments, usage);
    usage is None when there was nothing to send (an empty slice), so the caller skips it
    in the token tally without a wasted request."""
    if not prompt_inject.strip():
        return [], None

    focus = f"\n\nThis section is about: {topic}." if topic else ""
    response = _gemini_with_retry(lambda: client.models.generate_content(
        model=GEMINI_MODEL,
        contents=f"{SYSTEM_INSTRUCTIONS}{focus}\n\n---\n\n{prompt_inject}",
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=list[MomentOut],
            temperature=0.4,
        ),
    ))
    if response.parsed is None:
        return [], response.usage_metadata
    return response.parsed, response.usage_metadata


def _extract_section(section, segments, features) -> tuple[list[MomentOut], object | None]:
    """Pass 2: mine a single section for clip-worthy moments, seeing only its own slice."""
    start = _parse_ts(section.start)
    end = _parse_ts(section.end)
    prompt_inject = _slice_annotated(segments, features, start, end)
    return _extract(prompt_inject, topic=section.topic)


def _sentence_boundaries(words):
    """Timestamps where a real pause (>= SENT_GAP) precedes the next word - i.e. clean
    places to open or close a clip. First word's start always counts."""
    if not words:
        return []
    boundaries = [words[0]["start"]]
    for prev, cur in zip(words, words[1:]):
        if cur["start"] - prev["end"] >= SENT_GAP:
            boundaries.append(cur["start"])
    return boundaries


def _snap_moment(raw_start, raw_end, boundaries, silences, video_end=None):
    """Corrects the LLM's cited start/end against real word timing and silence data, then
    opens the clip up so it does not read as chopped.

    Start snaps backward to the nearest clean boundary within SNAP_WINDOW - it can only
    add lead-in context, never lose the hook the model picked. End snaps forward, so a
    cut can only finish the sentence, never truncate it, then rides into a trailing
    silence (up to SILENCE_EXTEND) so a laugh/reaction lands before the clip ends.

    On top of that both sides get CUSHION seconds of air, which is what actually keeps the
    payoff from landing on the final frame. The cushion shrinks (never below zero) rather
    than pushing the clip past MAX_LEN, and is clipped to the source's own bounds.
    """
    start_candidates = [b for b in boundaries if raw_start - SNAP_WINDOW <= b <= raw_start]
    end_candidates = [b for b in boundaries if raw_end <= b <= raw_end + SNAP_WINDOW]

    start = max(start_candidates) if start_candidates else raw_start
    end = min(end_candidates) if end_candidates else raw_end

    for sil in silences:
        sil_start = float(sil["silence_start"])
        if abs(sil_start - end) <= 0.5:
            end = min(end + SILENCE_EXTEND, float(sil["silence_end"]))
            break

    # Split whatever room MAX_LEN leaves evenly between the two sides, so a long moment
    # gives up head and tail air together instead of losing all of it off the end.
    room = max(0.0, MAX_LEN - (end - start))
    cushion = min(CUSHION, room / 2)

    padded_start = max(0.0, start - cushion)
    padded_end = end + cushion
    if video_end is not None:
        padded_end = min(padded_end, float(video_end))

    if padded_end - padded_start >= MIN_LEN:
        return padded_start, padded_end

    return raw_start, raw_end   # nothing snapped stayed in bounds; keep the citation

def _dedup_overlap(moments, ratio) -> tuple[list, int]:
    """Keep distinct clips, drop redundant ones. Greedy in score order: the highest-scored
    clip claims its span, and any later clip that shares more than `ratio` of the shorter
    clip's length with something already kept is discarded as a duplicate.

    Dividing the shared seconds by the *shorter* clip is deliberate - a short clip sitting
    entirely inside a long one is a near-total duplicate even though it covers only a slice
    of the long clip's timeline. Caps the survivors at MAX_TOTAL_MOMENTS so a long video
    cannot fan out an unbounded render load; because the scan is score-ordered, the cap
    trims the weakest tail. Returns (survivors, dropped_count).
    """
    ranked = sorted(moments, key=lambda m: m.scores["final"], reverse=True)

    kept: list = []
    dropped = 0
    for m in ranked:
        m_start, m_end = float(m.start_sec), float(m.end_sec)
        m_dur = m_end - m_start

        duplicate = False
        for k in kept:
            k_start, k_end = float(k.start_sec), float(k.end_sec)
            overlap = max(0.0, min(m_end, k_end) - max(m_start, k_start))
            shorter = min(m_dur, k_end - k_start)
            if shorter > 0 and overlap / shorter > ratio:
                duplicate = True
                break

        if duplicate or len(kept) >= MAX_TOTAL_MOMENTS:
            dropped += 1
            continue
        kept.append(m)

    return kept, dropped


def _coverage_metrics(moments, duration_sec) -> tuple[float, float]:
    """How much of the timeline the kept clips cover, and the largest uncovered gap.

    Coverage is the union of clip spans (overlapping clips merged so shared seconds are not
    double-counted) over the video length. The gap is the longest continuous uncovered
    stretch anywhere - the run-up before the first clip, a dead zone between clips, or the
    tail after the last one. A big gap near the end is the tell that the back half was
    under-mined. Pure arithmetic on the final snapped start/end.
    """
    duration = float(duration_sec or 0.0)
    if not duration or not moments:
        return 0.0, round(duration, 1)

    spans = sorted((float(m.start_sec), float(m.end_sec)) for m in moments)
    merged: list[list[float]] = []
    for s, e in spans:
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])

    covered = sum(e - s for s, e in merged)

    gap = merged[0][0]                      # gap before the first clip
    prev_end = merged[0][1]
    for s, e in merged[1:]:
        gap = max(gap, s - prev_end)
        prev_end = e
    gap = max(gap, duration - prev_end)     # tail gap after the last clip

    return round(100 * covered / duration, 1), round(gap, 1)


def _queue_auto_renders(ctx: TaskContext, db, moments: list[Moment]) -> list[Clip]:
    """Create queued Clip rows for every moment and schedule their renders.

    The Clip row is written here rather than by the render job so the frontend can list
    every pending clip the instant detect commits — one that hasn't been picked up yet
    reads as "rendering" on screen instead of only appearing once its file exists.

    Ordering is by the blended `final` score. Every moment gets a clip either way, but the
    queue is worked roughly in order, so the ones most worth watching land first.

    Takes the caller's session: the clips belong in the same transaction as the moments
    they point at, so a crash cannot leave clips referencing moments that were never
    written.
    """
    ranked = sorted(moments, key=lambda m: m.scores["final"], reverse=True)

    clips = []
    for moment in ranked:
        moment.status = "kept"
        clip = Clip(
            moment_id=moment.id,
            video_id=ctx.video.id,
            user_id=ctx.video.user_id,
            status="queued",
            params={
                # float() because these columns are Numeric: after a flush they can come
                # back as Decimal, which json can't serialise into the job params.
                "start": float(moment.start_sec),
                "end": float(moment.end_sec),
                "format": DEFAULT_FORMAT,
                "captions": AUTO_RENDER_CAPTIONS,
            },
        )
        db.add(clip)
        clips.append(clip)

    db.flush()   # mint the clip ids the render jobs are keyed on

    for clip in clips:
        # Deferred until detect's transaction commits — see TaskContext.enqueue_next.
        # Renders go to the cpu pool; the pipeline stages are IO-bound.
        ctx.enqueue_next(
            "app.tasks.render.render",
            str(ctx.video.id),
            {"clip_id": str(clip.id)},
            queue="cpu",
        )

    return clips


@job_contract("detect", skip_if=_detect_done)
def detect(ctx: TaskContext) -> None:
    logger.info("detect %s: start", ctx.video.id)

    segments, words, features = _load_inputs(ctx)
    boundaries = _sentence_boundaries(words)
    silences = features.get("silences", [])

    full_script = _build_annotated(segments=segments, features=features)

    # The run row is committed here, before any Gemini call, so the task holds no
    # transaction across the model work — Postgres reaps sessions idle inside a transaction
    # after 5 minutes, which is how this job died on 2026-07-18. run_id is what everything
    # below uses: no ORM object outlives this block.
    with ctx.tx() as db:
        run = RankingRun(
            video_id=ctx.video.id,
            params={"max_per_section": MAX_MOMENTS_PER_SECTION, "max_sections": MAX_SECTIONS,
                    "max_total_moments": MAX_TOTAL_MOMENTS, "overlap_ratio": OVERLAPPING_RATIO,
                    "section_workers": SECTION_WORKERS, "min_len": MIN_LEN, "max_len": MAX_LEN,
                    "core_min": CORE_MIN, "core_max": CORE_MAX, "cushion": CUSHION,
                    "sent_gap": SENT_GAP, "loud_db_over_median": LOUD_DB_OVER_MEDIAN},
            prompt_version=PROMPT_VERSION,
            model=GEMINI_MODEL,
            status="running",
            est_cost_usd=None,   # filled in after the Gemini calls
        )
        db.add(run)
        db.flush()
        run_id = run.id

    ctx.progress(stage="detect", pct=30)



    try:
        in_tok = out_tok = 0

        def _tally(usage) -> None:
            nonlocal in_tok, out_tok
            if usage is not None:
                in_tok += usage.prompt_token_count
                out_tok += usage.candidates_token_count

        # PASS 1 — segment the whole video into topical sections that tile the timeline,
        # then split any section over MAX_SECTION_LEN so none outgrows its clip budget.
        sections, seg_usage = _segment_transcript(full_script)
        _tally(seg_usage)
        sections = _cap_section_lengths(sections, MAX_SECTION_LEN)[:MAX_SECTIONS]
        logger.info("detect %s: segmented into %d sections", ctx.video.id, len(sections))

        # PASS 2 — mine each section on its own slice, concurrently so their latency
        # overlaps. If segmentation gave us nothing, fall back to a single whole-video pass
        # so a video never comes back empty.
        candidates: list[MomentOut] = []
        if sections:
            with ThreadPoolExecutor(max_workers=SECTION_WORKERS) as pool:
                results = list(pool.map(
                    lambda s: _extract_section(s, segments, features), sections
                ))
            for section_moments, usage in results:
                candidates.extend(section_moments)
                _tally(usage)
        else:
            section_moments, usage = _extract(full_script)
            candidates.extend(section_moments)
            _tally(usage)

        logger.info("detect %s: gathered %d candidate moments", ctx.video.id, len(candidates))

        est_cost = round(in_tok / 1_000_000 * GEMINI_IN_PER_MTOK
                    + out_tok / 1_000_000 * GEMINI_OUT_PER_MTOK, 6)

        # One transaction for everything the run produces: marking the run done, the
        # Moment rows, and the Clip rows that point at them. All of it or none of it —
        # a partial write would leave the API serving half a set of moments, since it
        # reads them by video_id with no notion of which run they came from.
        with ctx.tx() as db:
            db.execute(
                update(RankingRun)
                .where(RankingRun.id == run_id)
                .values(status="done", est_cost_usd=est_cost)
            )

            # Build Moment objects in memory first — filter by duration, snap, score — but
            # do NOT add them yet. Dedup compares every candidate's final snapped span
            # against the others, so all of them must exist before any is written.
            in_bounds: list[Moment] = []
            for m in candidates:
                raw_start, raw_end = _parse_ts(m.start), _parse_ts(m.end)
                dur = raw_end - raw_start
                if dur < CORE_MIN or dur > CORE_MAX:
                    continue
                start_sec, end_sec = _snap_moment(
                    raw_start, raw_end, boundaries, silences, ctx.video.duration_sec
                )
                final = 0.4 * m.hook + 0.3 * m.shareability + 0.2 * m.completeness + 0.1 * m.visual
                in_bounds.append(Moment(
                    video_id=ctx.video.id,
                    run_id=run_id,
                    start_sec=start_sec, end_sec=end_sec,
                    raw_start_sec=raw_start, raw_end_sec=raw_end,
                    scores={"hook": m.hook, "completeness": m.completeness,
                            "shareability": m.shareability, "visual": m.visual,
                            "final": round(final, 3)},
                    type=m.type, title=m.title, reason=m.reason,
                    transcript_excerpt=m.transcript_excerpt,
                ))

            # Drop overlapping duplicates, then persist only the survivors.
            kept, dropped = _dedup_overlap(in_bounds, OVERLAPPING_RATIO)
            for moment in kept:
                db.add(moment)

            db.flush()   # mint the moment ids the clips point back to
            clips = _queue_auto_renders(ctx, db, kept)

            coverage_pct, largest_gap = _coverage_metrics(kept, ctx.video.duration_sec)

        ctx.progress(pct=80)

        ctx.metrics.update({
            "model": GEMINI_MODEL,
            "prompt_version": PROMPT_VERSION,
            "sections_count": len(sections),
            "moments_returned": len(candidates),
            "moments_in_bounds": len(in_bounds),
            "dropped_overlap": dropped,
            "moments_kept": len(kept),
            "clips_queued": len(clips),
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "est_cost_usd": est_cost,
            "timeline_coverage_pct": coverage_pct,
            "largest_gap_sec": largest_gap,
        })

    except Exception:
        # The run row is already committed, so this is a plain UPDATE by id rather than
        # the re-insert this used to need. Deliberately touches no ORM object: a lazy
        # load here would raise and bury the real error (a Gemini 503, usually).
        with ctx.tx() as db:
            db.execute(
                update(RankingRun).where(RankingRun.id == run_id).values(status="error")
            )
        raise

    ctx.set_status(VideoStatus.ready)
    ctx.progress(stage="detect", pct=100)
    logger.info(
        "detect %s: done, sections=%d kept=%d clips_queued=%d coverage=%.0f%% gap=%.0fs",
        ctx.video.id, ctx.metrics["sections_count"], ctx.metrics["moments_kept"],
        ctx.metrics["clips_queued"], ctx.metrics["timeline_coverage_pct"],
        ctx.metrics["largest_gap_sec"],
    )





