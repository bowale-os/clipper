import json
import statistics
from sqlalchemy import select, update
from pydantic import BaseModel
from google import genai
from google.genai import types

from app.config.secrets import settings
from app.db.models import Clip, RankingRun, Transcript, Moment, VideoStatus
from app.tasks.render import DEFAULT_FORMAT
from app.workers.contract import TaskContext, job_contract
from app.workers.queues import io_queue
from app.services.r2_client import download_bytes

GEMINI_MODEL = "gemini-2.5-flash"
# Per-million-token prices for GEMINI_MODEL. VERIFY against current Gemini pricing
# before trusting est_cost_usd — these drift and feed billing rollups.
GEMINI_IN_PER_MTOK = 0.30
GEMINI_OUT_PER_MTOK = 2.50
PROMPT_VERSION = "detect-v2"
MAX_MOMENTS=15
MIN_LEN=60
MAX_LEN=80
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

# How many of the detected moments render without the user asking. Every render
# re-downloads the whole source, so rendering all MAX_MOMENTS would cost far more than
# a user typically uses. The rest stay as moments they can render on demand.
AUTO_RENDER_TOP = 4
AUTO_RENDER_CAPTIONS = True

SYSTEM_INSTRUCTIONS = f"""You find the most clip-worthy moments in a video from its \
timestamped transcript. The script below interleaves spoken lines with energy markers:
  [h:mm:ss] <text>      a spoken line, starting at that timestamp
  <SILENCE Ns>          a pause of N seconds (dramatic beat, or dead air)
  <LOUD +NdB a-b>       a burst of loud audio between a and b (laughter, reaction, emphasis)

Return AT MOST {MAX_MOMENTS} moments, each a self-contained clip that would work posted alone.

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

client = genai.Client(api_key=settings.GEMINI_API_KEY)


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


def _queue_auto_renders(ctx: TaskContext, db, moments: list[Moment]) -> list[Clip]:
    """Create queued Clip rows for the strongest moments and schedule their renders.

    The Clip row is written here rather than by the render job so the frontend can list
    every pending clip the instant detect commits — one that hasn't been picked up yet
    reads as "rendering" on screen instead of only appearing once its file exists.

    Ordering is by the blended `final` score, so the clips that fill the screen first are
    the ones most worth watching.

    Takes the caller's session: the clips belong in the same transaction as the moments
    they point at, so a crash cannot leave clips referencing moments that were never
    written.
    """
    ranked = sorted(moments, key=lambda m: m.scores["final"], reverse=True)

    clips = []
    for moment in ranked[:AUTO_RENDER_TOP]:
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
    segments, words, features = _load_inputs(ctx)
    boundaries = _sentence_boundaries(words)
    silences = features.get("silences", [])

    prompt_inject = _build_annotated(segments=segments, features=features)

    # The run row is committed here, before the Gemini call, so the task holds no
    # transaction across it — Postgres reaps sessions idle inside a transaction after 5
    # minutes, which is how this job died on 2026-07-18. run_id is what everything below
    # uses: no ORM object outlives this block.
    with ctx.tx() as db:
        run = RankingRun(
            video_id=ctx.video.id,
            params={"max_moments": MAX_MOMENTS, "min_len": MIN_LEN, "max_len": MAX_LEN,
                    "core_min": CORE_MIN, "core_max": CORE_MAX, "cushion": CUSHION,
                    "sent_gap": SENT_GAP, "loud_db_over_median": LOUD_DB_OVER_MEDIAN},
            prompt_version=PROMPT_VERSION,
            model=GEMINI_MODEL,
            status="running",
            est_cost_usd=None,   # filled in after the Gemini call
        )
        db.add(run)
        db.flush()
        run_id = run.id

    ctx.progress(stage="detect", pct=30)

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=f"{SYSTEM_INSTRUCTIONS}\n\n---\n\n{prompt_inject}",
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=list[MomentOut],
                temperature=0.4,
                # optionally: system_instruction=SYSTEM_INSTRUCTIONS, and put only
                # the annotated script in `contents`
            ),
        )

        if response.parsed is None:
            raise RuntimeError(f"Gemini returned no parseable moments: {response.text!r}")
        candidates: list[MomentOut] = response.parsed


        usage = response.usage_metadata
        in_tok = usage.prompt_token_count
        out_tok = usage.candidates_token_count

        # Fill these from *current* Gemini 2.5 Flash pricing — verify, don't trust a constant blindly
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

            # Turn candidates into Moment rows. Timestamps come back as the h:mm:ss strings
            # the model cited, so parse them back to seconds. Anything outside the duration
            # window is dropped here — the returned/kept gap is a signal we record in metrics.
            kept: list[Moment] = []
            for m in candidates:
                raw_start, raw_end = _parse_ts(m.start), _parse_ts(m.end)
                dur = raw_end - raw_start
                if dur < CORE_MIN or dur > CORE_MAX:
                    continue
                start_sec, end_sec = _snap_moment(
                    raw_start, raw_end, boundaries, silences, ctx.video.duration_sec
                )
                final = 0.4 * m.hook + 0.3 * m.shareability + 0.2 * m.completeness + 0.1 * m.visual
                moment = Moment(
                    video_id=ctx.video.id,
                    run_id=run_id,
                    start_sec=start_sec, end_sec=end_sec,
                    raw_start_sec=raw_start, raw_end_sec=raw_end,
                    scores={"hook": m.hook, "completeness": m.completeness,
                            "shareability": m.shareability, "visual": m.visual,
                            "final": round(final, 3)},
                    type=m.type, title=m.title, reason=m.reason,
                    transcript_excerpt=m.transcript_excerpt,
                )
                db.add(moment)
                kept.append(moment)

            db.flush()   # mint the moment ids the clips point back to
            clips = _queue_auto_renders(ctx, db, kept)

        ctx.progress(pct=80)

        ctx.metrics.update({
            "model": GEMINI_MODEL,
            "prompt_version": PROMPT_VERSION,
            "moments_returned": len(candidates),
            "moments_kept": len(kept),
            "clips_queued": len(clips),
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "est_cost_usd": est_cost,
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





