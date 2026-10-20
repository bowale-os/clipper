"""Render, end to end: a real ffmpeg cut of a generated video, with storage mocked."""
import json
import shutil
import subprocess
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.tasks.render as render_module
import app.workers.contract as contract
from app.db.models import Clip, Job, VideoStatus
from tests.conftest import requires_ffmpeg

pytestmark = requires_ffmpeg


def probe(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    )
    data = json.loads(out.stdout)
    return data["streams"][0]["width"], data["streams"][0]["height"], float(data["format"]["duration"])


@pytest.fixture()
def storage(monkeypatch, sample_video, tmp_path):
    state = SimpleNamespace(downloads=0, uploaded={}, words=None, streamed_url=None)

    def download_file(key, local_path):
        state.downloads += 1
        shutil.copyfile(sample_video, local_path)

    def upload_file(path, key):
        kept = tmp_path / f"out_{uuid.uuid4().hex}.mp4"
        shutil.copyfile(path, kept)
        state.uploaded[key] = kept

    def download_bytes(key):
        if state.words is None:
            raise AssertionError("words were not expected to be fetched")
        return json.dumps(state.words).encode()

    def download_url(key, expires_in=3600):
        state.streamed_url = key
        return str(tmp_path / "missing.mp4")  # unreadable source -> forces the fallback

    monkeypatch.setattr(render_module, "download_file", download_file)
    monkeypatch.setattr(render_module, "upload_file", upload_file)
    monkeypatch.setattr(render_module, "download_bytes", download_bytes)
    monkeypatch.setattr(render_module, "generate_download_url", download_url)
    return state


@pytest.fixture()
def rq(monkeypatch):
    monkeypatch.setattr(contract, "get_current_job", lambda: SimpleNamespace(id="rq-render", retries_left=0))


@pytest.fixture()
def video(make_user, make_video):
    return make_video(make_user("renderer"), status=VideoStatus.ready, duration_sec=6, artifacts={})


def make_clip(db, video, **params):
    full = {"start": 1.0, "end": 3.0, "format": "original", "captions": False}
    full.update(params)
    clip = Clip(video_id=video.id, user_id=video.user_id, status="queued", params=full)
    db.add(clip)
    db.commit()
    return clip


def run(video, clip):
    render_module.render(video.id, {"clip_id": str(clip.id)})


def reload(db, clip):
    db.expire_all()
    return db.get(Clip, clip.id)


# ---------------------------------------------------------------- happy paths


def test_original_format_keeps_the_source_dimensions(db, video, storage, rq):
    clip = make_clip(db, video)
    run(video, clip)

    row = reload(db, clip)
    assert row.status == "ready" and row.r2_key == f"clips/{clip.id}.mp4"
    width, height, duration = probe(storage.uploaded[row.r2_key])
    assert (width, height) == (320, 240)
    assert duration == pytest.approx(2.0, abs=0.35)


@pytest.mark.parametrize("fmt,size", [("9:16", (1080, 1920)), ("1:1", (1080, 1080)), ("16:9", (1920, 1080))])
def test_preset_formats_produce_exact_dimensions(db, video, storage, rq, fmt, size):
    clip = make_clip(db, video, format=fmt)
    run(video, clip)
    width, height, _ = probe(storage.uploaded[reload(db, clip).r2_key])
    assert (width, height) == size


def test_job_metrics_describe_the_cut(db, video, storage, rq):
    clip = make_clip(db, video)
    run(video, clip)
    job = db.query(Job).filter_by(video_id=video.id).one()
    assert job.status == "done"
    assert job.metrics["clip_id"] == str(clip.id) and job.metrics["format"] == "original"
    assert job.metrics["source"] == "download" and job.metrics["captions"] is False
    assert job.metrics["duration_sec"] == 2.0 and job.metrics["output_bytes"] > 0
    assert "render_ms" in job.metrics and "encode_speed" in job.metrics


def test_render_does_not_change_the_source_video(db, video, storage, rq):
    clip = make_clip(db, video)
    run(video, clip)
    db.expire_all()
    db.refresh(video)
    assert video.status == VideoStatus.ready


def test_work_directory_is_removed(db, video, storage, rq, monkeypatch):
    made = []
    real = render_module.tempfile.mkdtemp
    monkeypatch.setattr(render_module.tempfile, "mkdtemp", lambda: made.append(real()) or made[-1])
    run(video, make_clip(db, video))
    import os

    assert made and not os.path.exists(made[0])


# ---------------------------------------------------------------- captions


WORDS = [
    {"word": "hello", "start": 1.2, "end": 1.6},
    {"word": "there", "start": 1.7, "end": 2.1},
    {"word": "friend", "start": 2.2, "end": 2.6},
    {"word": "outside", "start": 5.0, "end": 5.4},
]


def test_captions_are_burned_in_when_speech_falls_in_the_window(db, video, storage, rq):
    video.artifacts = {"words_key": "artifacts/x/words.json"}
    db.commit()
    storage.words = WORDS
    clip = make_clip(db, video, captions=True)
    run(video, clip)

    job = db.query(Job).filter_by(video_id=video.id).one()
    assert job.metrics["captions"] is True
    assert reload(db, clip).status == "ready"


def test_captions_requested_but_no_transcript_still_renders_plain(db, video, storage, rq):
    clip = make_clip(db, video, captions=True)  # video has no words_key
    run(video, clip)
    assert reload(db, clip).status == "ready"
    assert db.query(Job).filter_by(video_id=video.id).one().metrics["captions"] is False


def test_captions_requested_but_silent_window_renders_plain(db, video, storage, rq):
    video.artifacts = {"words_key": "k"}
    db.commit()
    storage.words = [WORDS[-1]]  # only speech outside 1s..3s
    clip = make_clip(db, video, captions=True)
    run(video, clip)
    assert db.query(Job).filter_by(video_id=video.id).one().metrics["captions"] is False


# ---------------------------------------------------------------- streaming vs download


def test_streaming_is_used_when_it_works(db, video, storage, rq, monkeypatch):
    def fake_cut(workdir, src, out_path, start, duration, vf, input_opts=None):
        assert input_opts == render_module.STREAM_INPUT_OPTS and src.endswith("missing.mp4")
        open(out_path, "wb").write(b"clip")
        return {"encode_speed": 3.0}

    monkeypatch.setattr(render_module, "_cut", fake_cut)
    monkeypatch.setattr(render_module, "_probe_duration", lambda p: 2.0)
    clip = make_clip(db, video)
    run(video, clip)

    assert storage.downloads == 0
    metrics = db.query(Job).filter_by(video_id=video.id).one().metrics
    assert metrics["source"] == "stream" and metrics["encode_speed"] == 3.0


def test_truncated_stream_falls_back_to_a_full_download(db, video, storage, rq, monkeypatch):
    calls = []

    def fake_cut(workdir, src, out_path, start, duration, vf, input_opts=None):
        calls.append("stream" if input_opts else "local")
        open(out_path, "wb").write(b"clip")
        return {}

    monkeypatch.setattr(render_module, "_cut", fake_cut)
    monkeypatch.setattr(render_module, "_probe_duration", lambda p: 0.5)  # dropped connection, exit code 0
    clip = make_clip(db, video, start=0.0, end=5.0)  # long enough that 0.5s is clearly short
    run(video, clip)

    assert calls == ["stream", "local"] and storage.downloads == 1
    assert db.query(Job).filter_by(video_id=video.id).one().metrics["source"] == "download"


def test_unknown_stream_length_is_trusted(db, video, storage, rq, monkeypatch):
    monkeypatch.setattr(render_module, "_cut", lambda *a, **k: open(a[2], "wb").write(b"c") and {})
    monkeypatch.setattr(render_module, "_probe_duration", lambda p: None)
    run(video, make_clip(db, video))
    assert storage.downloads == 0


def test_stream_error_falls_back_to_download(db, video, storage, rq, monkeypatch):
    real_cut = render_module._cut

    def flaky(workdir, src, out_path, start, duration, vf, input_opts=None):
        if input_opts:
            raise RuntimeError("ffmpeg failed (1): Protocol not found")
        return real_cut(workdir, src, out_path, start, duration, vf)

    monkeypatch.setattr(render_module, "_cut", flaky)
    clip = make_clip(db, video)
    run(video, clip)
    assert storage.downloads == 1 and reload(db, clip).status == "ready"


# ---------------------------------------------------------------- failures


def test_bad_format_marks_only_the_clip_as_failed(db, video, storage, rq):
    clip = make_clip(db, video, format="4:3")
    with pytest.raises(RuntimeError, match="Unsupported format"):
        run(video, clip)
    assert reload(db, clip).status == "error"
    db.refresh(video)
    assert video.status == VideoStatus.ready and "error" not in (video.pipeline or {})
    assert db.query(Job).filter_by(video_id=video.id).one().status == "error"


@pytest.mark.parametrize("start,end", [(3.0, 3.0), (4.0, 1.0)])
def test_non_positive_duration_fails_the_clip(db, video, storage, rq, start, end):
    clip = make_clip(db, video, start=start, end=end)
    with pytest.raises(RuntimeError, match="non-positive duration"):
        run(video, clip)
    assert reload(db, clip).status == "error"


def test_ffmpeg_failure_surfaces_its_message(db, video, storage, rq, monkeypatch):
    def broken_download(key, local_path):
        open(local_path, "wb").write(b"not a video")

    monkeypatch.setattr(render_module, "download_file", broken_download)
    clip = make_clip(db, video)
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        run(video, clip)
    assert reload(db, clip).status == "error"
    assert "ffmpeg failed" in db.query(Job).filter_by(video_id=video.id).one().error


def test_a_deleted_clip_cancels_quietly(db, video, storage, rq):
    clip = make_clip(db, video)
    run_id = str(clip.id)
    db.delete(clip)
    db.commit()
    render_module.render(video.id, {"clip_id": run_id})  # must not raise, or RQ retries it
    assert storage.downloads == 0 and storage.uploaded == {}


def test_a_deleted_video_cancels_quietly(db, storage, rq):
    render_module.render(uuid.uuid4(), {"clip_id": str(uuid.uuid4())})
    assert storage.uploaded == {}


def test_missing_clip_id_is_an_error(db, video, storage, rq):
    with pytest.raises(RuntimeError, match="clip_id"):
        render_module.render(video.id, {})


def test_an_already_rendered_clip_is_not_rendered_again(db, video, storage, rq):
    clip = make_clip(db, video)
    clip.status, clip.r2_key = "ready", "clips/done.mp4"
    db.commit()
    run(video, clip)
    assert storage.downloads == 0 and storage.uploaded == {}
    assert db.query(Job).filter_by(video_id=video.id).one().status == "done"


def test_an_upload_failure_marks_the_clip_failed(db, video, storage, rq, monkeypatch):
    monkeypatch.setattr(render_module, "upload_file", MagicMock(side_effect=ConnectionError("r2 down")))
    clip = make_clip(db, video)
    with pytest.raises(ConnectionError):
        run(video, clip)
    assert reload(db, clip).status == "error" and reload(db, clip).r2_key is None


# ---------------------------------------------------------------- low-level helpers


def test_cut_reports_ffmpegs_stderr_on_failure(tmp_path):
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"nope")
    with pytest.raises(RuntimeError, match="ffmpeg failed"):
        render_module._cut(str(tmp_path), str(junk), str(tmp_path / "o.mp4"), 0, 1, "scale=2:2")


def test_probe_duration(sample_video, tmp_path):
    assert render_module._probe_duration(str(sample_video)) == pytest.approx(6.0, abs=0.3)
    junk = tmp_path / "junk.mp4"
    junk.write_bytes(b"nope")
    assert render_module._probe_duration(str(junk)) is None
