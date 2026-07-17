import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time

from app.db.models import VideoStatus
from app.workers.contract import TaskContext, job_contract
from app.workers.queues import io_queue

# Energy timeline resolution: one RMS reading per this many samples at 16 kHz.
RMS_WINDOW_SAMPLES = 8000          # 0.5 s at 16 kHz
SILENCE_NOISE_DB = "-35dB"
SILENCE_MIN_DUR = "0.4"
THUMB_EVERY_SEC = 10               # one scrubber thumbnail per 10 s
THUMB_COLS = 10


def _ingest_done(ctx: TaskContext) -> bool:
    # duration_sec is set last, so it doubles as ingest's "all artifacts written" flag.
    return ctx.video.duration_sec is not None


def _ffprobe_duration(path: str) -> float:
    """Seconds of media at `path`, via ffprobe. Raises if ffprobe fails or has no duration."""
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "json", path,
        ],
        capture_output=True, text=True, check=True,
    )
    duration = json.loads(proc.stdout)["format"]["duration"]
    return float(duration)


def _extract_audio(video_path: str, out_path: str) -> None:
    """The one full read of the source: downmix to 16 kHz mono Opus (~45 MB for 3 h).
    Everything downstream (transcribe, features) works off this small file."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", video_path,
            "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "libopus", "-b:a", "32k",
            out_path,
        ],
        capture_output=True, text=True, check=True,
    )


def _detect_silences(audio_path: str) -> list[dict]:
    """Silence windows via ffmpeg silencedetect (parsed from stderr)."""
    proc = subprocess.run(
        [
            "ffmpeg", "-i", audio_path,
            "-af", f"silencedetect=noise={SILENCE_NOISE_DB}:d={SILENCE_MIN_DUR}",
            "-f", "null", "-",
        ],
        capture_output=True, text=True, check=True,
    )
    starts = [float(m) for m in re.findall(r"silence_start:\s*(-?[\d.]+)", proc.stderr)]
    ends = [float(m) for m in re.findall(r"silence_end:\s*(-?[\d.]+)", proc.stderr)]
    # starts/ends arrive interleaved and in order; a trailing start with no end is dropped.
    return [{"silence_start": s, "silence_end": e} for s, e in zip(starts, ends)]


def _rms_timeline(audio_path: str) -> list[dict]:
    """Coarse energy timeline [{t, rms_db}] at RMS_WINDOW_SAMPLES resolution, so detect
    can mark loud spikes (crowd/laughter). Best-effort: unparseable frames are skipped."""
    proc = subprocess.run(
        [
            "ffmpeg", "-i", audio_path,
            "-af", (
                f"asetnsamples=n={RMS_WINDOW_SAMPLES}:p=0,"
                "astats=metadata=1:reset=1,"
                "ametadata=print:key=lavfi.astats.Overall.RMS_level"
            ),
            "-f", "null", "-",
        ],
        capture_output=True, text=True, check=True,
    )
    timeline: list[dict] = []
    t = None
    for line in proc.stderr.splitlines():
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            t = float(m.group(1))
            continue
        m = re.search(r"lavfi\.astats\.Overall\.RMS_level=(-?[\d.]+|-?inf|nan)", line)
        if m and t is not None:
            raw = m.group(1)
            rms = -90.0 if raw in ("-inf", "nan") else float(raw)
            timeline.append({"t": round(t, 3), "rms_db": round(rms, 2)})
            t = None
    return timeline


def _keyframes(video_path: str) -> list[float]:
    """Keyframe timestamps (seconds) — lets render/preview seek accurately later."""
    proc = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "packet=pts_time,flags",
            "-of", "json", video_path,
        ],
        capture_output=True, text=True, check=True,
    )
    packets = json.loads(proc.stdout).get("packets", [])
    return [
        round(float(p["pts_time"]), 3)
        for p in packets
        if p.get("pts_time") is not None and p.get("flags", "").startswith("K")
    ]


def _thumb_sprite(video_path: str, out_path: str, duration_sec: float) -> None:
    """One JPG sprite sheet, 1 frame / THUMB_EVERY_SEC, tiled THUMB_COLS wide."""
    n_thumbs = max(1, math.ceil(duration_sec / THUMB_EVERY_SEC))
    rows = max(1, math.ceil(n_thumbs / THUMB_COLS))
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", video_path,
            "-vf", f"fps=1/{THUMB_EVERY_SEC},scale=160:-1,tile={THUMB_COLS}x{rows}",
            "-frames:v", "1", out_path,
        ],
        capture_output=True, text=True, check=True,
    )


@job_contract("ingest")
def ingest(ctx: TaskContext) -> None:
    video = ctx.video

    # Idempotency: duration_sec is ingest's final artifact. If it's set, we've run.
    if _ingest_done(ctx):
        return

    video.pipeline = {**(video.pipeline or {}), "stage": "ingest", "progress_pct": 0}
    video.status = VideoStatus.processing

    from app.services.r2_client import download_file, upload_bytes, upload_file

    started = time.monotonic()
    workdir = tempfile.mkdtemp()
    suffix = os.path.splitext(video.r2_key)[1] or ".mp4"
    video_path = os.path.join(workdir, f"source{suffix}")
    audio_path = os.path.join(workdir, "audio.ogg")
    thumbs_path = os.path.join(workdir, "thumbs.jpg")

    prefix = f"artifacts/{video.id}"
    audio_key = f"{prefix}/audio.ogg"
    features_key = f"{prefix}/features.json"
    keyframes_key = f"{prefix}/keyframes.json"
    thumbs_key = f"{prefix}/thumbs.jpg"

    try:
        download_file(video.r2_key, video_path)
        probed_size = os.path.getsize(video_path)
        duration = _ffprobe_duration(video_path)
        video.pipeline = {**video.pipeline, "progress_pct": 20}

        # audio.ogg — the only full read of the source; everything else is cheap.
        _extract_audio(video_path, audio_path)
        upload_file(audio_path, audio_key)
        video.pipeline = {**video.pipeline, "progress_pct": 50}

        # features.json — energy + silence timeline (drives detect's markers & snapping).
        features = {"rms": _rms_timeline(audio_path), "silences": _detect_silences(audio_path)}
        upload_bytes(json.dumps(features).encode("utf-8"), features_key, "application/json")
        video.pipeline = {**video.pipeline, "progress_pct": 70}

        # keyframes.json — seek math for later render/preview.
        keyframes = _keyframes(video_path)
        upload_bytes(json.dumps(keyframes).encode("utf-8"), keyframes_key, "application/json")
        video.pipeline = {**video.pipeline, "progress_pct": 85}

        # thumbs.jpg — scrubber sprite for the review UI.
        _thumb_sprite(video_path, thumbs_path, duration)
        upload_file(thumbs_path, thumbs_key)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    video.artifacts = {
        **(video.artifacts or {}),
        "audio_key": audio_key,
        "features_key": features_key,
        "keyframes_key": keyframes_key,
        "thumbs_key": thumbs_key,
    }
    video.duration_sec = duration
    video.pipeline = {**video.pipeline, "progress_pct": 100}

    ctx.metrics.update({
        "duration_sec": duration,
        "size_bytes": probed_size,
        "silences": len(features["silences"]),
        "keyframes": len(keyframes),
        "ingest_ms": int((time.monotonic() - started) * 1000),
        "est_cost_usd": 0.0,   # own CPU only; recorded so cost sums are uniform per stage
    })

    # Enqueue next stage. String path avoids importing transcribe before it exists.
    io_queue.enqueue("app.tasks.transcribe.transcribe", str(video.id))
