"""Ingest, run for real: the helpers shell out to ffmpeg/ffprobe against a generated video,
and the task itself runs through the job contract with storage mocked."""
import json
import shutil
import subprocess

import pytest

import app.services.r2_client as r2_module
import app.tasks.ingest as ingest_module
from app.db.models import Job, Video, VideoStatus
from tests.conftest import requires_ffmpeg

pytestmark = requires_ffmpeg


# ---------------------------------------------------------------- probing


def test_duration(sample_video):
    assert ingest_module._ffprobe_duration(str(sample_video)) == pytest.approx(6.0, abs=0.3)


def test_dimensions(sample_video):
    assert ingest_module._ffprobe_dimensions(str(sample_video)) == (320, 240)


def test_dimensions_of_an_audio_only_file_raise(sample_video, tmp_path):
    audio = tmp_path / "a.m4a"
    subprocess.run(["ffmpeg", "-y", "-i", str(sample_video), "-vn", "-c:a", "aac", str(audio)], capture_output=True, check=True)
    with pytest.raises(ValueError, match="no video stream"):
        ingest_module._ffprobe_dimensions(str(audio))


def test_probing_a_non_media_file_fails(tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"not a video")
    with pytest.raises(subprocess.CalledProcessError):
        ingest_module._ffprobe_duration(str(junk))


def test_keyframes_are_sorted_and_start_at_zero(sample_video):
    frames = ingest_module._keyframes(str(sample_video))
    assert frames[0] == 0.0 and frames == sorted(frames)
    assert len(frames) >= 5  # -g 25 at 25fps over 6s


# ---------------------------------------------------------------- audio analysis


@pytest.fixture(scope="module")
def audio(sample_video, tmp_path_factory):
    out = tmp_path_factory.mktemp("audio") / "audio.ogg"
    ingest_module._extract_audio(str(sample_video), str(out))
    return out


def test_extracted_audio_is_small_mono_16k_opus(audio):
    assert audio.stat().st_size > 0
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,channels,sample_rate", "-of", "json", str(audio)],
        capture_output=True, text=True, check=True,
    )
    stream = json.loads(proc.stdout)["streams"][0]
    assert stream["codec_name"] == "opus" and stream["channels"] == 1


def test_silence_window_is_found_where_the_tone_stops(audio):
    silences = ingest_module._detect_silences(str(audio))
    assert silences, "expected the muted stretch to be detected"
    first = silences[0]
    assert first["silence_start"] == pytest.approx(2.0, abs=0.3)
    assert first["silence_end"] == pytest.approx(3.5, abs=0.3)


def test_rms_timeline_marks_the_quiet_stretch(audio):
    timeline = ingest_module._rms_timeline(str(audio))
    assert len(timeline) >= 8
    assert all(set(p) == {"t", "rms_db"} for p in timeline)
    quiet = [p["rms_db"] for p in timeline if 2.3 < p["t"] < 3.2]
    loud = [p["rms_db"] for p in timeline if p["t"] < 1.5]
    assert quiet and loud and max(quiet) < min(loud)


def test_thumbnail_sprite_is_written(sample_video, tmp_path):
    out = tmp_path / "thumbs.jpg"
    ingest_module._thumb_sprite(str(sample_video), str(out), 6.0)
    assert out.stat().st_size > 0


# ---------------------------------------------------------------- the task


@pytest.fixture()
def storage(monkeypatch, sample_video):
    uploaded = {"files": {}, "bytes": {}}

    def download_file(key, local_path):
        shutil.copyfile(sample_video, local_path)
        uploaded["downloaded"] = key

    monkeypatch.setattr(r2_module, "download_file", download_file)
    monkeypatch.setattr(r2_module, "upload_file", lambda path, key: uploaded["files"].update({key: True}))
    monkeypatch.setattr(r2_module, "upload_bytes", lambda data, key, ctype: uploaded["bytes"].update({key: json.loads(data)}))
    return uploaded


@pytest.fixture()
def rq(monkeypatch):
    from types import SimpleNamespace
    import app.workers.contract as contract

    monkeypatch.setattr(contract, "get_current_job", lambda: SimpleNamespace(id="rq-ingest", retries_left=0))


@pytest.fixture()
def pools(monkeypatch):
    from unittest.mock import MagicMock
    import app.workers.queues as queues

    io = MagicMock()
    monkeypatch.setattr(queues, "io_queue", io)
    monkeypatch.setattr(queues, "cpu_queue", MagicMock())
    return io


def test_ingest_produces_every_artifact_and_hands_off_to_transcribe(
    db, make_user, make_video, storage, rq, pools
):
    video = make_video(make_user("ingester"), status=VideoStatus.uploaded, duration_sec=None)
    ingest_module.ingest(video.id)

    db.expire_all()
    row = db.get(Video, video.id)
    prefix = f"artifacts/{video.id}"
    assert row.artifacts == {
        "audio_key": f"{prefix}/audio.ogg",
        "features_key": f"{prefix}/features.json",
        "keyframes_key": f"{prefix}/keyframes.json",
        "thumbs_key": f"{prefix}/thumbs.jpg",
        "width": 320,
        "height": 240,
    }
    assert float(row.duration_sec) == pytest.approx(6.0, abs=0.3)
    assert row.status == VideoStatus.processing
    assert row.pipeline["stage"] == "ingest" and row.pipeline["progress_pct"] == 100

    assert storage["downloaded"] == video.r2_key
    assert set(storage["files"]) == {f"{prefix}/audio.ogg", f"{prefix}/thumbs.jpg"}
    features = storage["bytes"][f"{prefix}/features.json"]
    assert set(features) == {"rms", "silences"} and features["silences"]
    assert storage["bytes"][f"{prefix}/keyframes.json"]

    job = db.query(Job).filter_by(video_id=video.id).one()
    assert job.status == "done"
    assert job.metrics["silences"] >= 1 and job.metrics["keyframes"] >= 5 and job.metrics["est_cost_usd"] == 0.0
    pools.enqueue.assert_called_once()
    assert pools.enqueue.call_args.args == ("app.tasks.transcribe.transcribe", str(video.id))


def test_ingest_is_skipped_once_duration_is_recorded(db, make_user, make_video, storage, rq, pools):
    video = make_video(make_user("ingester"), duration_sec=42)
    ingest_module.ingest(video.id)
    assert "downloaded" not in storage
    pools.enqueue.assert_not_called()
    assert db.query(Job).filter_by(video_id=video.id).one().status == "done"


def test_ingest_failure_marks_the_video_errored_and_leaves_no_duration(db, make_user, make_video, storage, rq, pools, monkeypatch):
    def download_junk(key, local_path):
        with open(local_path, "wb") as f:
            f.write(b"this is not a video")

    monkeypatch.setattr(r2_module, "download_file", download_junk)
    video = make_video(make_user("ingester"), status=VideoStatus.uploaded, duration_sec=None)
    with pytest.raises(subprocess.CalledProcessError):
        ingest_module.ingest(video.id)

    db.expire_all()
    row = db.get(Video, video.id)
    assert row.status == VideoStatus.error and row.duration_sec is None
    pools.enqueue.assert_not_called()
