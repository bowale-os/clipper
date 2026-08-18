import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Clip
from app.workers.contract import TaskContext, WorkCancelled, job_contract
from app.services.r2_client import (
    download_bytes,
    download_file,
    generate_download_url,
    upload_file,
)

logger = logging.getLogger(__name__)

# Output presets: aspect ratio -> exact (width, height). 9:16 is the short-form default.
ORIGINAL_FORMAT = "original"
FORMATS = {
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
    "16:9": (1920, 1080),
}
ALLOWED_FORMATS = {*FORMATS, ORIGINAL_FORMAT}
DEFAULT_FORMAT = ORIGINAL_FORMAT
X264_CRF = "20"           # quality; lower = better + bigger. 20 is a good social default.
X264_PRESET = "veryfast"  # encode speed vs filesize. Workers are CPU-bound, so favour speed.

# Input options for reading the source straight out of R2 over HTTP instead of pulling the
# whole file down first — see _source_url. A remote read can drop mid-encode where a local
# file cannot, so ffmpeg is told to reconnect rather than fail the job over one blip.
STREAM_INPUT_OPTS = [
    "-reconnect", "1",
    "-reconnect_streamed", "1",
    "-reconnect_delay_max", "5",
]
SOURCE_URL_EXPIRES = 6 * 3600   # must outlive the encode, not just the seek

# How far short of the requested length a streamed cut may come back before it is treated
# as truncated. Some slack is needed because video.duration_sec is itself an estimate, so
# a clip running to the very end of a source can legitimately land a little short.
STREAM_SHORTFALL_TOLERANCE = 3.0

# Caption cue shaping. A cue is the group of words shown on screen at one time.
CAPTION_MAX_CHARS = 42    # longer than this wraps badly on a phone
CAPTION_MAX_SEC = 3.0     # a cue held longer than this reads as stalled
CAPTION_GAP_SEC = 0.6     # a pause at least this long ends the current cue

# Sizes in an ASS style are script units, NOT output pixels. ffmpeg generates the ASS
# header for an SRT with a hardcoded PlayResY of 288 (verified against lavc 62.28) and
# libass scales that space up to the frame, so one unit is 6.7px on the 1920-tall 9:16
# default. Writing pixel-looking numbers here is the trap: MarginV=180 reads as a modest
# offset and actually puts the text 1200px up, most of the way up the frame.
#
# So sizes are declared as a fraction of frame height and converted. That also keeps them
# consistent across the 1080-tall formats, where a unit is worth 3.75px instead.
ASS_PLAY_RES_Y = 288


def _units(fraction_of_height: float) -> str:
    """Fraction of the output height -> ASS script units."""
    return f"{fraction_of_height * ASS_PLAY_RES_Y:.1f}"


# Outline is deliberately thin. It exists so white text survives bright footage, and the
# old value was thick enough that the black swallowed the letterforms and the captions
# stopped reading as white at all.
CAPTION_STYLE = (
    f"Fontname=Inter,FontSize={_units(0.05)},Bold=1,"
    "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
    f"BorderStyle=1,Outline={_units(0.02)},Shadow=0,"
    # Sits just above the phone UI that overlays the bottom of a full-screen player.
    f"Alignment=2,MarginV={_units(0.060)}"
)
SRT_FILENAME = "captions.srt"

# The typeface is shipped in the repo rather than named and hoped for. libass can only
# use fonts installed in the image, the backend deploys on a Nixpacks base we do not
# control, and a missing font is not an error: libass quietly falls back to its default,
# so a deploy would look completely unchanged with nothing in the logs to say why.
FONT_FILENAME = "Inter-Bold.ttf"
FONT_SOURCE = os.path.join(os.path.dirname(__file__), "..", "assets", "fonts", FONT_FILENAME)


def _load_clip(ctx: TaskContext, db) -> Clip:
    """Load the Clip this job renders, in the caller's transaction.

    The contract keys jobs on video_id, but render works on one clip, so create_clip
    passes the target through params.
    """
    clip_id = ctx.params.get("clip_id")
    if not clip_id:
        raise RuntimeError("render requires params['clip_id']")
    clip = db.get(Clip, uuid.UUID(clip_id))
    if clip is None:
        # Gone rather than broken: the clip's video was deleted, or the row was
        # replaced by a newer version, so there is nothing left to render. Retrying
        # would fail identically four times over.
        raise WorkCancelled(f"Clip {clip_id} no longer exists")
    return clip


def _render_done(ctx: TaskContext) -> bool:
    """Render's artifact is the file in R2, not the Clip row — create_clip already made
    that before this job was enqueued. A populated r2_key is the proof it rendered."""
    with ctx.tx() as db:
        clip = _load_clip(ctx, db)
        return clip.status == "ready" and clip.r2_key is not None


def _mark_clip_failed(session: Session, params: dict, err: Exception) -> None:
    """Record the clip as errored inside the contract's failure transaction.

    Without this the clip would stay "rendering" forever and the frontend would poll a
    clip that never resolves. render commits that "rendering" status before the encode,
    so unlike the task's later writes it survives the rollback — which is exactly why it
    needs an explicit tombstone rather than being undone for free.
    """
    clip_id = params.get("clip_id")
    if not clip_id:
        return
    clip = session.get(Clip, uuid.UUID(clip_id))
    if clip is None:
        return
    clip.status = "error"


def _load_words(ctx: TaskContext) -> list[dict]:
    """Fetch the word-level timings transcribe wrote to R2.

    Returns an empty list when the video has no words artifact, so a missing transcript
    degrades to an uncaptioned clip instead of failing the render.
    """
    words_key = (ctx.video.artifacts or {}).get("words_key")
    if not words_key:
        return []
    return json.loads(download_bytes(words_key))


def _words_in_window(words: list[dict], start: float, end: float) -> list[dict]:
    """Keep the words spoken inside [start, end], rebased so the clip begins at zero.

    ffmpeg burns subtitles against the output timeline, which starts at 0, but the words
    carry absolute source timestamps — so each one is shifted back by `start`. Words that
    straddle a boundary are clamped to it rather than dropped.
    """
    selected = []
    for word in words:
        word_start = float(word["start"])
        word_end = float(word["end"])

        if word_end <= start:
            continue
        if word_start >= end:
            continue

        clamped_start = max(word_start, start)
        clamped_end = min(word_end, end)
        selected.append({
            "text": word["word"].strip(),
            "start": clamped_start - start,
            "end": clamped_end - start,
        })
    return selected


def _should_end_cue(current: list[dict], word: dict) -> bool:
    """Decide whether `word` starts a new cue instead of joining the current one.

    A cue ends when adding the word would overflow the line, hold the cue on screen too
    long, or when there is a real pause between the words.
    """
    pending_text = " ".join(entry["text"] for entry in current) + " " + word["text"]
    if len(pending_text) > CAPTION_MAX_CHARS:
        return True

    cue_duration = word["end"] - current[0]["start"]
    if cue_duration > CAPTION_MAX_SEC:
        return True

    gap = word["start"] - current[-1]["end"]
    if gap >= CAPTION_GAP_SEC:
        return True

    return False


def _group_into_cues(words: list[dict]) -> list[list[dict]]:
    """Group words into on-screen cues."""
    cues = []
    current = []

    for word in words:
        if not current:
            current.append(word)
            continue

        if _should_end_cue(current, word):
            cues.append(current)
            current = [word]
        else:
            current.append(word)

    if current:
        cues.append(current)

    return cues


def _srt_timestamp(seconds: float) -> str:
    """Seconds -> 'HH:MM:SS,mmm', the timestamp format SRT requires."""
    if seconds < 0:
        seconds = 0.0
    total_ms = int(round(seconds * 1000))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def _write_srt(cues: list[list[dict]], path: str) -> None:
    """Write cues out as SRT: an index, a time range, the text, then a blank line."""
    blocks = []
    for index, cue in enumerate(cues, start=1):
        start = _srt_timestamp(cue[0]["start"])
        end = _srt_timestamp(cue[-1]["end"])
        text = " ".join(word["text"] for word in cue)
        blocks.append(f"{index}\n{start} --> {end}\n{text}\n")

    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(blocks))


def _build_srt(ctx: TaskContext, workdir: str, start: float, end: float) -> str | None:
    """Produce the caption file for this clip's window.

    Returns the path, or None when there is nothing to burn in — no transcript, or no
    speech inside the window. The caller then renders without the subtitles filter.
    """
    words = _load_words(ctx)
    if not words:
        return None

    windowed = _words_in_window(words, start, end)
    if not windowed:
        return None

    cues = _group_into_cues(windowed)
    if not cues:
        return None

    path = os.path.join(workdir, SRT_FILENAME)
    _write_srt(cues, path)
    return path


def _video_filter(crop: dict | None, srt_filename: str | None, fmt = ORIGINAL_FORMAT) -> str:
    """Build the -vf chain: crop to aspect, scale to the preset, optionally burn captions.

    The crop expressions pick the largest rect of the target aspect that still fits inside
    the source (crop centres it by default), so a 16:9 podcast becomes 9:16 by taking the
    middle column rather than letterboxing. An explicit `crop` from the editor wins.
    """
    if fmt not in ALLOWED_FORMATS:
        raise RuntimeError(f"Unsupported format {fmt}; expected one of {sorted(ALLOWED_FORMATS)}")

    if fmt == ORIGINAL_FORMAT:
        stages = ["scale=trunc(iw/2)*2:trunc(ih/2)*2"]
    else:
        width, height = FORMATS[fmt]
        crop_stage = f"crop='min(iw,ih*{width}/{height})':'min(ih,iw*{height}/{width})'"
        stages = [crop_stage, f"scale={width}:{height}"]

    if srt_filename:
        # Captions are burnt in after the scale so the font size means the same thing
        # regardless of the source resolution.
        #
        # fontsdir is '.' for the same reason srt_filename is bare: ffmpeg runs with
        # cwd=workdir, and the filter parser treats ':' as its own separator, so an
        # absolute path would need escaping and would break outright on a Windows drive
        # letter during local runs.
        stages.append(f"subtitles={srt_filename}:fontsdir=.:force_style='{CAPTION_STYLE}'")

    return ",".join(stages)


def _parse_ffmpeg_stats(stderr: str) -> dict:
    """Pull timing out of ffmpeg's own output so a slow render can say *why* it was slow.

    Two independent signals, which together separate "the CPU is starved" from "the read
    is stalling":
      * speed/fps come from the progress line ffmpeg already prints, and measure throughput
        — speed=1.0x is real-time, below that is slower than real-time.
      * -benchmark adds a 'bench: utime=.. stime=.. rtime=..' line: CPU time actually burnt
        (utime+stime) versus wall time (rtime). cpu_fraction near 1 means the encode was
        CPU-bound; well under 1 means most of the wall clock was spent waiting, i.e. on I/O.

    Best-effort: any field ffmpeg did not emit is simply left out.
    """
    stats: dict = {}

    speeds = re.findall(r"speed=\s*([\d.]+)x", stderr)
    if speeds:
        stats["encode_speed"] = float(speeds[-1])

    fpses = re.findall(r"\bfps=\s*([\d.]+)", stderr)
    if fpses:
        stats["encode_fps"] = float(fpses[-1])

    bench = re.search(r"utime=([\d.]+)s.*?stime=([\d.]+)s.*?rtime=([\d.]+)s", stderr)
    if bench:
        utime, stime, rtime = (float(g) for g in bench.groups())
        stats["ffmpeg_cpu_s"] = round(utime + stime, 3)
        stats["ffmpeg_wall_s"] = round(rtime, 3)
        if rtime > 0:
            stats["cpu_fraction"] = round((utime + stime) / rtime, 3)

    return stats


def _cut(
    workdir: str,
    src: str,
    out_path: str,
    start: float,
    duration: float,
    vf: str,
    input_opts: list[str] | None = None,
) -> dict:
    """Cut [start, start+duration] out of src and re-encode it to out_path.

    `src` is a local path or a URL; `input_opts` carries whatever that source needs (see
    STREAM_INPUT_OPTS) and must sit before `-i`, since ffmpeg applies input options to the
    input that follows them.

    `-ss` before `-i` seeks before decoding (fast — it does not walk the whole file, and
    over HTTP it range-requests the window instead of streaming from byte zero), and
    `-t` after `-i` measures the duration from that seek point.

    ffmpeg runs with cwd=workdir so the subtitles filter can name the SRT by filename.
    The filter parses ':' as its own option separator, so an absolute path would need
    escaping — on Windows the drive letter alone ("C:\\...") breaks it.

    Returns the timing ffmpeg reported for this run (see _parse_ffmpeg_stats).
    """
    cmd = [
        "ffmpeg", "-y",
        "-benchmark",                 # appends CPU-vs-wall timing so we can tell why a cut was slow
        *(input_opts or []),
        "-ss", f"{start:.3f}",
        "-i", src,
        "-t", f"{duration:.3f}",
        "-vf", vf,
        "-c:v", "libx264", "-preset", X264_PRESET, "-crf", X264_CRF,
        "-pix_fmt", "yuv420p",        # some sources decode to a pix_fmt Safari/social won't play
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",    # moov atom up front so the clip streams before it fully downloads
        out_path,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir)
    if proc.returncode != 0:
        # Surface ffmpeg's own words — check=True would raise with them buried on .stderr,
        # and the contract only persists str(e) into job.error.
        raise RuntimeError(f"ffmpeg failed ({proc.returncode}): {proc.stderr[-2000:]}")
    return _parse_ffmpeg_stats(proc.stderr)


def _probe_duration(path: str) -> float | None:
    """Length of a rendered file in seconds, or None if it cannot be determined.

    None means "do not judge this file", not "the file is bad" — ffprobe ships with
    ffmpeg but the caller must not fail a perfectly good clip over a missing binary.
    """
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        return None
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return None


def _cut_from_source(ctx: TaskContext, workdir, src_path, out_path, start, duration, vf) -> tuple[str, dict]:
    """Cut the clip, reading the source over HTTP if it can and off disk if it must.

    Streaming is the fast path and the reason a video can auto-render every one of its
    moments: `-ss` before `-i` makes ffmpeg range-request only the window it needs, so a
    one-minute clip out of a two-hour source moves tens of megabytes instead of the whole
    file. Rendering fifteen clips used to mean downloading the source fifteen times.

    It is not universally safe, though. It needs an ffmpeg built with https support, and it
    needs a container that seeks well remotely — fragmented MP4 and raw .ts do not. So a
    failed remote read falls back to the download this used to always do, rather than
    failing the clip. Returns which path produced the file, for the job metrics.

    The output is measured before it is trusted, which matters far more here than it would
    for a local file: when reconnection finally gives up, ffmpeg does not treat the dead
    connection as an error. It sees end of input, closes the file it has, and exits 0. That
    would upload a clip cut short in the middle and mark it ready, which is worse than any
    failure — nothing anywhere would say something went wrong.

    Returns which path produced the file and the timing ffmpeg reported for it.
    """
    reason = None
    try:
        url = generate_download_url(ctx.video.r2_key, expires_in=SOURCE_URL_EXPIRES)
        stats = _cut(workdir, url, out_path, start, duration, vf, input_opts=STREAM_INPUT_OPTS)

        actual = _probe_duration(out_path)
        if actual is None or actual >= duration - STREAM_SHORTFALL_TOLERANCE:
            return "stream", stats

        reason = f"streamed clip is {actual:.1f}s, expected {duration:.1f}s"
    except RuntimeError as e:
        reason = str(e)

    # Not fatal, and logged in full: this is the only place the reason shows up, and the
    # answer to "why is every render slow again" is in ffmpeg's own words here.
    logger.warning(
        "render %s: streaming source failed, falling back to download: %s",
        ctx.video.id, reason,
    )

    download_file(ctx.video.r2_key, src_path)
    stats = _cut(workdir, src_path, out_path, start, duration, vf)
    return "download", stats


# render only reads the video (r2_key, words_key) and writes its own Clip row, so it
# never needs the video lock — ctx.tx() takes one only when a helper asks for it.
@job_contract(
    "render", skip_if=_render_done, fail_video=False, on_failure=_mark_clip_failed
)
def render(ctx: TaskContext) -> None:
    # Claim the clip and read what the encode needs, in one short transaction. Everything
    # after this block is download/ffmpeg/upload, which must hold no transaction.
    with ctx.tx() as db:
        clip = _load_clip(ctx, db)
        clip_id = clip.id
        params = clip.params or {}

        start = float(params["start"])
        end = float(params["end"])
        duration = end - start
        if duration <= 0:
            raise RuntimeError(f"Clip {clip_id} has a non-positive duration ({start} -> {end})")

        clip.status = "rendering"

    fmt = params.get("format", DEFAULT_FORMAT)

    logger.info("render %s: start (clip=%s, format=%s)", ctx.video.id, clip_id, fmt)

    started = time.monotonic()
    workdir = tempfile.mkdtemp()
    suffix = os.path.splitext(ctx.video.r2_key)[1] or ".mp4"
    src_path = os.path.join(workdir, f"source{suffix}")   # INPUT  — only if we have to download
    out_path = os.path.join(workdir, "clip.mp4")          # OUTPUT — ffmpeg writes here

    try:
        # Captions and the filter come first: both are cheap, and both can reject the
        # job. Better to fail here than partway through reading the source.
        srt_path = None
        if params.get("captions"):
            srt_path = _build_srt(ctx, workdir, start, end)
            if srt_path:
                # Next to the SRT so the filter can reach it with fontsdir=. — see
                # _video_filter for why that path cannot be absolute.
                shutil.copyfile(FONT_SOURCE, os.path.join(workdir, FONT_FILENAME))

        vf = _video_filter(params.get("crop"), SRT_FILENAME if srt_path else None, fmt)

        source, cut_stats = _cut_from_source(
            ctx, workdir, src_path, out_path, start, duration, vf
        )

        out_bytes = os.path.getsize(out_path)
        out_key = f"clips/{clip_id}.mp4"
        upload_file(out_path, out_key)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    with ctx.tx() as db:
        db.execute(
            update(Clip).where(Clip.id == clip_id).values(r2_key=out_key, status="ready")
        )

    ctx.metrics.update({
        "clip_id": str(clip_id),
        "format": fmt,
        "source": source,
        "captions": srt_path is not None,
        "duration_sec": round(duration, 3),
        "output_bytes": out_bytes,
        "render_ms": int((time.monotonic() - started) * 1000),
        # ffmpeg's own timing for this cut — see _parse_ffmpeg_stats. cpu_fraction near 1
        # is a CPU-bound encode; well under 1 means the wall clock went on waiting (I/O).
        **cut_stats,
    })

    logger.info(
        "render %s: done in %dms, clip=%s source=%s speed=%sx cpu_fraction=%s",
        ctx.video.id, ctx.metrics["render_ms"], clip_id, source,
        cut_stats.get("encode_speed", "?"), cut_stats.get("cpu_fraction", "?"),
    )