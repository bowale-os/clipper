import json
import logging
import math
import os
import shutil
import subprocess
import tempfile
import time

from sqlalchemy import select

from app.config.secrets import settings
from app.db.models import Transcript, VideoStatus
from app.workers.contract import TaskContext, job_contract

logger = logging.getLogger(__name__)

GROQ_MODEL = "whisper-large-v3"
GROQ_MAX_BYTES = 24 * 1024 * 1024   # Groq rejects uploads over 25MB; stay under.
GROQ_COST_PER_HOUR = 0.111          # whisper-large-v3, for the metrics row only.
OVERLAP_SEC = 5.0                   # each chunk re-transcribes this much of its neighbours.


def _transcribe_done(ctx: TaskContext) -> bool:
    # The Transcript row is transcribe's output artifact. If it exists, we've run.
    stmt = select(Transcript).where(Transcript.video_id == ctx.video.id)
    with ctx.tx() as db:
        return db.execute(stmt).scalars().first() is not None


def _as_dicts(items) -> list[dict]:
    """Groq may hand back plain dicts or pydantic rows depending on SDK version."""
    return [it if isinstance(it, dict) else it.model_dump() for it in (items or [])]


def _split_audio(audio_path: str, duration_sec: float, stride: float, workdir: str) -> list[tuple[str, float, float, float]]:
    """Cut the audio into overlapping windows so no word ever sits on a hard cut.

    Chunk i covers audio [i*stride - OVERLAP, (i+1)*stride], i.e. it re-transcribes
    OVERLAP seconds of each neighbour. To merge without dupes or gaps, each chunk also
    carries an authoritative window [win_start, win_end): a contiguous slice of the
    timeline placed in the *middle* of the overlap, so every kept word is at least
    OVERLAP/2 inside the chunk's audio and never near a truncating edge.

    Returns (path, offset, win_start, win_end) per chunk. `offset` is the chunk audio's
    absolute start — added back to Whisper's chunk-relative timestamps.
    """
    plans: list[tuple[str, float, float, float]] = []
    n = math.ceil(duration_sec / stride)
    for i in range(n):
        audio_start = max(0.0, i * stride - OVERLAP_SEC)
        audio_end = min((i + 1) * stride, duration_sec)
        win_start = 0.0 if i == 0 else i * stride - OVERLAP_SEC / 2
        win_end = duration_sec if i == n - 1 else (i + 1) * stride - OVERLAP_SEC / 2

        part = os.path.join(workdir, f"chunk_{i}.ogg")
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss", str(audio_start), "-t", str(audio_end - audio_start),
                "-i", audio_path,
                "-ac", "1", "-ar", "16000", "-c:a", "libopus", "-b:a", "24k",
                part,
            ],
            capture_output=True, text=True, check=True,
        )
        plans.append((part, audio_start, win_start, win_end))
    return plans


def _transcribe_file(client, path: str, offset: float) -> tuple[list, list, str | None]:
    """Transcribe one audio file and shift every timestamp by `offset` so that chunk N's
    times are absolute against the original video, not relative to the chunk."""
    with open(path, "rb") as f:
        resp = client.audio.transcriptions.create(
            file=(os.path.basename(path), f.read()),
            model=GROQ_MODEL,
            response_format="verbose_json",
            timestamp_granularities=["segment", "word"],
        )

    segments = [
        {
            "start": float(s["start"]) + offset,
            "end": float(s["end"]) + offset,
            "text": s["text"].strip(),
            "speaker": None,          # diarization is a later concern
        }
        for s in _as_dicts(getattr(resp, "segments", None))
    ]
    words = [
        {"word": w["word"], "start": float(w["start"]) + offset, "end": float(w["end"]) + offset}
        for w in _as_dicts(getattr(resp, "words", None))
    ]
    return segments, words, getattr(resp, "language", None)


@job_contract("transcribe", skip_if=_transcribe_done)
def transcribe(ctx: TaskContext) -> None:
    video = ctx.video

    ctx.progress(stage="transcribe", pct=0)
    ctx.set_status(VideoStatus.processing)

    from app.services.r2_client import download_file, upload_bytes
    from groq import Groq

    started = time.monotonic()
    workdir = tempfile.mkdtemp()
    audio_path = os.path.join(workdir, "audio.ogg")

    logger.info("transcribe %s: start", video.id)

    try:
        # Reuse ingest's 16 kHz mono Opus — no need to re-download or re-decode the source.
        if "audio_key" not in (video.artifacts or {}):
            logger.error("transcribe %s: missing audio_key in artifacts: %r", video.id, video.artifacts)
            raise ValueError(f"Job artifacts missing 'audio_key' for video {video.id}")
        download_file(video.artifacts["audio_key"], audio_path)
        ctx.progress(pct=40)

        client = Groq(api_key=settings.GROQ_API_KEY)
        audio_bytes = os.path.getsize(audio_path)

        segments: list = []
        words: list = []
        language: str | None = None

        if audio_bytes <= GROQ_MAX_BYTES:
            logger.info("transcribe %s: single-shot request (%d bytes)", video.id, audio_bytes)
            segments, words, language = _transcribe_file(client, audio_path, 0.0)
        else:
            # duration_sec is set upstream by ingest; size the stride so each chunk
            # (stride + OVERLAP of audio) still fits inside the byte budget.
            duration = float(video.duration_sec)
            max_req_sec = GROQ_MAX_BYTES / (audio_bytes / duration)
            stride = max(1.0, max_req_sec - OVERLAP_SEC)
            chunks = _split_audio(audio_path, duration, stride, workdir)
            logger.info("transcribe %s: %d bytes over budget, splitting into %d chunks", video.id, audio_bytes, len(chunks))
            for i, (part_path, offset, win_start, win_end) in enumerate(chunks):
                seg, wrd, lang = _transcribe_file(client, part_path, offset)
                # Keep only what falls in this chunk's authoritative window — the
                # windows tile the timeline exactly once, so nothing is missed or doubled.
                segments += [s for s in seg if win_start <= s["start"] < win_end]
                words += [w for w in wrd if win_start <= w["start"] < win_end]
                language = language or lang
                logger.info("transcribe %s: chunk %d/%d done", video.id, i + 1, len(chunks))

        ctx.progress(pct=85)
        logger.info("transcribe %s: groq done (segments=%d, words=%d)", video.id, len(segments), len(words))

        # Segments (small) live inline in the DB; word-level timing (large) goes to R2.
        words_key = f"artifacts/{video.id}/words.json"
        upload_bytes(json.dumps(words).encode("utf-8"), words_key, "application/json")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    ctx.set_artifacts(words_key=words_key)
    with ctx.tx() as db:
        db.add(
            Transcript(
                video_id=video.id,
                language=language,
                provider="groq",
                model=GROQ_MODEL,
                segments=segments,
                words_r2_key=words_key,
            )
        )

    duration_sec = float(video.duration_sec) if video.duration_sec is not None else 0.0
    ctx.progress(pct=100)
    ctx.metrics.update({
        "segments": len(segments),
        "words": len(words),
        "transcribe_ms": int((time.monotonic() - started) * 1000),
        "est_cost_usd": round(duration_sec / 3600 * GROQ_COST_PER_HOUR, 6),
    })

    logger.info("transcribe %s: done in %dms, enqueuing detect", video.id, ctx.metrics["transcribe_ms"])

    # Deferred until this job's transaction commits — see TaskContext.enqueue_next.
    ctx.enqueue_next("app.tasks.detect.detect", str(video.id))
