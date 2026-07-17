import json
import statistics
from sqlalchemy import select
from pydantic import BaseModel
from google import genai
from google.genai import types

from app.config.secrets import settings
from app.db.models import RankingRun, Transcript, Moment, VideoStatus
from app.workers.contract import TaskContext, job_contract
from app.workers.queues import io_queue
from app.services.r2_client import download_bytes

GEMINI_MODEL = "gemini-2.5-flash"
# Per-million-token prices for GEMINI_MODEL. VERIFY against current Gemini pricing
# before trusting est_cost_usd — these drift and feed billing rollups.
GEMINI_IN_PER_MTOK = 0.30
GEMINI_OUT_PER_MTOK = 2.50
PROMPT_VERSION = "detect-v1"
MAX_MOMENTS=10
MIN_LEN=15
MAX_LEN=90
SENT_GAP=0.6
START_PAD=0.25
SILENCE_EXTEND=2.0
LOUD_DB_OVER_MEDIAN = 8.0   
LOUD_MIN_DUR = 1.0

SYSTEM_INSTRUCTIONS = f"""You find the most clip-worthy moments in a video from its \
timestamped transcript. The script below interleaves spoken lines with energy markers:
  [h:mm:ss] <text>      a spoken line, starting at that timestamp
  <SILENCE Ns>          a pause of N seconds (dramatic beat, or dead air)
  <LOUD +NdB a-b>       a burst of loud audio between a and b (laughter, reaction, emphasis)

Return AT MOST {MAX_MOMENTS} moments, each a self-contained clip that would work posted alone.

Rules:
- start/end MUST be timestamps that appear in the script (use the [h:mm:ss] markers).
- Each clip must run between {MIN_LEN} and {MAX_LEN} seconds. Do not exceed {MAX_LEN}.
- Begin on a clean thought, not mid-sentence; end on a punchline, payoff, or resolved point.
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
    stmt = select(RankingRun).where(RankingRun.video_id == ctx.video.id)
    return ctx.db.execute(stmt).scalar_one_or_none() is not None


def _load_inputs(ctx):
    video = ctx.video

    transcript = ctx.db.execute(
        select(Transcript).where(Transcript.video_id == video.id)
    ).scalar_one_or_none()

    if transcript is None:
        raise RuntimeError(f"No transcript for video {video.id}; transcribe must run first")

    words = json.loads(download_bytes(transcript.words_r2_key))          # [{word,start,end}, ...]

    features = {"rms": [], "silences": []}                               # defensive default
    features_key = (video.artifacts or {}).get("features_key")
    if features_key:
        features = json.loads(download_bytes(features_key))              # {rms:[...], silences:[...]}

    return transcript, words, features


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


@job_contract("detect")
def detect(ctx: TaskContext) -> None:
    if _detect_done(ctx):
        return
    
    transcript, words, features = _load_inputs(ctx)
    segments = transcript.segments

    prompt_inject = _build_annotated(segments=segments, features=features)
    run = RankingRun(
        video_id=ctx.video.id,
        params={"max_moments": MAX_MOMENTS, "min_len": MIN_LEN, "max_len": MAX_LEN,
                "sent_gap": SENT_GAP, "loud_db_over_median": LOUD_DB_OVER_MEDIAN},
        prompt_version=PROMPT_VERSION,
        model=GEMINI_MODEL,
        status="running",
        est_cost_usd=None,   # fill in after the Gemini call
        )
    ctx.db.add(run)
    ctx.db.flush()   

    ctx.video.pipeline = {**(ctx.video.pipeline or {}), "stage": "detect", "progress_pct": 30}


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

        run.est_cost_usd = est_cost
        run.status = "done"

        # Turn candidates into Moment rows. Timestamps come back as the h:mm:ss strings
        # the model cited, so parse them back to seconds. Anything outside the duration
        # window is dropped here — the returned/kept gap is a signal we record in metrics.
        kept = 0
        for m in candidates:
            raw_start, raw_end = _parse_ts(m.start), _parse_ts(m.end)
            dur = raw_end - raw_start
            if dur < MIN_LEN or dur > MAX_LEN:
                continue
            final = 0.4 * m.hook + 0.3 * m.shareability + 0.2 * m.completeness + 0.1 * m.visual
            ctx.db.add(Moment(
                video_id=ctx.video.id,
                run_id=run.id,
                start_sec=raw_start, end_sec=raw_end,      # snapping is a later concern
                raw_start_sec=raw_start, raw_end_sec=raw_end,
                scores={"hook": m.hook, "completeness": m.completeness,
                        "shareability": m.shareability, "visual": m.visual,
                        "final": round(final, 3)},
                type=m.type, title=m.title, reason=m.reason,
                transcript_excerpt=m.transcript_excerpt,
            ))
            kept += 1
        
        ctx.video.pipeline = {**(ctx.video.pipeline or {}), "stage": "detect", "progress_pct": 80}


        ctx.metrics.update({
            "model": GEMINI_MODEL,
            "prompt_version": PROMPT_VERSION,
            "moments_returned": len(candidates),
            "moments_kept": kept,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "est_cost_usd": est_cost,
        })

    except Exception as e:
        from app.db.session import session_scope
        run.status = "error"
        with session_scope() as s2:
            s2.merge(run)      # run is detached; merge re-inserts it with status="error"
        raise

    ctx.video.status = VideoStatus.ready
    ctx.video.pipeline = {**(ctx.video.pipeline or {}), "stage": "detect", "progress_pct": 100}





