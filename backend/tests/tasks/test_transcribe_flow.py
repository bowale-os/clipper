"""Transcribe: chunk planning, timestamp shifting, and the whole task with Groq faked."""
import json
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.services.r2_client as r2_module
import app.tasks.transcribe as tr
import app.workers.contract as contract
import app.workers.queues as queues
from app.db.models import Job, Transcript, Video, VideoStatus


def response(segments=(), words=(), language="en"):
    return SimpleNamespace(segments=list(segments), words=list(words), language=language)


class FakeGroq:
    """Groq(api_key=...) stand-in. `replies` maps an uploaded filename to its response."""

    replies: dict = {}
    calls: list = []

    def __init__(self, api_key=None):
        self.audio = SimpleNamespace(transcriptions=SimpleNamespace(create=self._create))

    def _create(self, file, model, response_format, timestamp_granularities):
        FakeGroq.calls.append((file[0], model, response_format, tuple(timestamp_granularities)))
        reply = FakeGroq.replies[file[0]]
        if isinstance(reply, Exception):
            raise reply
        return reply


@pytest.fixture(autouse=True)
def fake_groq(monkeypatch):
    import groq

    FakeGroq.replies, FakeGroq.calls = {}, []
    monkeypatch.setattr(groq, "Groq", FakeGroq)
    return FakeGroq


# ---------------------------------------------------------------- _transcribe_file


def test_timestamps_are_shifted_by_the_chunk_offset_and_text_is_trimmed(tmp_path, fake_groq):
    f = tmp_path / "chunk.ogg"
    f.write_bytes(b"audio")
    fake_groq.replies["chunk.ogg"] = response(
        segments=[{"start": 1.0, "end": 2.5, "text": "  hello there  "}],
        words=[{"word": "hello", "start": 1.0, "end": 1.4}],
        language="fr",
    )
    segments, words, language = tr._transcribe_file(fake_groq(), str(f), offset=100.0)
    assert segments == [{"start": 101.0, "end": 102.5, "text": "hello there", "speaker": None}]
    assert words == [{"word": "hello", "start": 101.0, "end": 101.4}]
    assert language == "fr"
    assert fake_groq.calls == [("chunk.ogg", "whisper-large-v3", "verbose_json", ("segment", "word"))]


def test_pydantic_style_rows_are_accepted(tmp_path, fake_groq):
    class Row:
        def __init__(self, d):
            self.d = d

        def model_dump(self):
            return self.d

    f = tmp_path / "c.ogg"
    f.write_bytes(b"x")
    fake_groq.replies["c.ogg"] = response(
        segments=[Row({"start": 0, "end": 1, "text": "a"})], words=[Row({"word": "a", "start": 0, "end": 1})]
    )
    segments, words, _ = tr._transcribe_file(fake_groq(), str(f), 0.0)
    assert segments[0]["text"] == "a" and words[0]["word"] == "a"


def test_response_without_segments_or_words(tmp_path, fake_groq):
    f = tmp_path / "c.ogg"
    f.write_bytes(b"x")
    fake_groq.replies["c.ogg"] = SimpleNamespace()
    assert tr._transcribe_file(fake_groq(), str(f), 0.0) == ([], [], None)


# ---------------------------------------------------------------- _split_audio


def test_split_windows_tile_the_whole_timeline_exactly_once(tmp_path, monkeypatch):
    monkeypatch.setattr(tr.subprocess, "run", MagicMock())
    plans = tr._split_audio("audio.ogg", duration_sec=100.0, stride=30.0, workdir=str(tmp_path))
    assert len(plans) == 4
    windows = [(w_start, w_end) for _, _, w_start, w_end in plans]
    assert windows[0][0] == 0.0 and windows[-1][1] == 100.0
    for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
        assert prev_end == next_start  # no gap, no double coverage


def test_split_chunks_carry_overlap_and_absolute_offsets(tmp_path, monkeypatch):
    run = MagicMock()
    monkeypatch.setattr(tr.subprocess, "run", run)
    plans = tr._split_audio("audio.ogg", 100.0, 30.0, str(tmp_path))
    assert [p[1] for p in plans] == [0.0, 25.0, 55.0, 85.0]
    # every kept window sits at least OVERLAP/2 inside the chunk's own audio
    for _, offset, w_start, _ in plans[1:]:
        assert w_start - offset == tr.OVERLAP_SEC / 2
    assert run.call_count == 4
    first_cmd = run.call_args_list[0].args[0]
    assert first_cmd[0] == "ffmpeg" and "libopus" in first_cmd and run.call_args_list[0].kwargs["check"] is True


def test_split_last_chunk_stops_at_the_end_of_the_audio(tmp_path, monkeypatch):
    run = MagicMock()
    monkeypatch.setattr(tr.subprocess, "run", run)
    tr._split_audio("audio.ogg", 70.0, 30.0, str(tmp_path))
    last = run.call_args_list[-1].args[0]
    start, length = float(last[last.index("-ss") + 1]), float(last[last.index("-t") + 1])
    assert start + length == pytest.approx(70.0)


# ---------------------------------------------------------------- the task


@pytest.fixture()
def storage(monkeypatch):
    saved = {"bytes": {}}

    def download_file(key, local_path):
        saved["downloaded"] = key
        with open(local_path, "wb") as f:
            f.write(b"x" * saved.get("audio_size", 100))

    monkeypatch.setattr(r2_module, "download_file", download_file)
    monkeypatch.setattr(r2_module, "upload_bytes", lambda data, key, ctype: saved["bytes"].update({key: json.loads(data)}))
    return saved


@pytest.fixture()
def rq(monkeypatch):
    monkeypatch.setattr(contract, "get_current_job", lambda: SimpleNamespace(id="rq-t", retries_left=0))


@pytest.fixture()
def io_queue(monkeypatch):
    io = MagicMock()
    monkeypatch.setattr(queues, "io_queue", io)
    monkeypatch.setattr(queues, "cpu_queue", MagicMock())
    return io


@pytest.fixture()
def video(make_user, make_video):
    return make_video(
        make_user("speaker"),
        status=VideoStatus.processing,
        duration_sec=3600,
        artifacts={"audio_key": "artifacts/v/audio.ogg"},
    )


def test_single_request_transcription_saves_everything_and_enqueues_detect(
    db, video, storage, rq, io_queue, fake_groq
):
    fake_groq.replies["audio.ogg"] = response(
        segments=[{"start": 0, "end": 2, "text": " hi "}, {"start": 2, "end": 4, "text": "bye"}],
        words=[{"word": "hi", "start": 0, "end": 1}, {"word": "bye", "start": 2, "end": 3}],
    )
    tr.transcribe(video.id)

    db.expire_all()
    transcript = db.get(Transcript, video.id)
    assert transcript.provider == "groq" and transcript.model == "whisper-large-v3" and transcript.language == "en"
    assert [s["text"] for s in transcript.segments] == ["hi", "bye"]
    assert transcript.words_r2_key == f"artifacts/{video.id}/words.json"
    assert storage["bytes"][transcript.words_r2_key] == [
        {"word": "hi", "start": 0.0, "end": 1.0},
        {"word": "bye", "start": 2.0, "end": 3.0},
    ]
    assert storage["downloaded"] == "artifacts/v/audio.ogg"

    row = db.get(Video, video.id)
    assert row.artifacts["words_key"] == transcript.words_r2_key
    assert row.pipeline["progress_pct"] == 100 and row.status == VideoStatus.processing

    job = db.query(Job).filter_by(video_id=video.id).one()
    assert job.status == "done" and job.metrics["segments"] == 2 and job.metrics["words"] == 2
    assert job.metrics["est_cost_usd"] == pytest.approx(0.111, abs=1e-3)  # 1 hour of audio
    assert len(fake_groq.calls) == 1
    io_queue.enqueue.assert_called_once()
    assert io_queue.enqueue.call_args.args == ("app.tasks.detect.detect", str(video.id))


def test_long_audio_is_chunked_and_merged_without_duplicates(db, video, storage, rq, io_queue, fake_groq, monkeypatch, tmp_path):
    storage["audio_size"] = 2000
    monkeypatch.setattr(tr, "GROQ_MAX_BYTES", 1000)
    video.duration_sec = 100  # 20 bytes/sec -> 50s per request -> stride 45s

    parts = []
    for i in range(3):
        p = tmp_path / f"chunk_{i}.ogg"
        p.write_bytes(b"x")
        parts.append(str(p))
    # path, absolute offset of the chunk's audio, authoritative window
    plans = [(parts[0], 0.0, 0.0, 42.5), (parts[1], 40.0, 42.5, 87.5), (parts[2], 85.0, 87.5, 100.0)]
    monkeypatch.setattr(tr, "_split_audio", lambda *a, **k: plans)

    def words(*starts):  # chunk-relative times
        return [{"word": f"w{s}", "start": s, "end": s + 0.5} for s in starts]

    # Whisper reports chunk-relative times. "X" (abs 43) and "Y" (abs 88) fall in the
    # overlaps, so two chunks hear each of them; only the chunk whose window owns the
    # timestamp may keep it.
    fake_groq.replies["chunk_0.ogg"] = response(
        segments=[{"start": 1, "end": 2, "text": "a"}, {"start": 43, "end": 44, "text": "X"}],
        words=words(1, 43),
    )
    fake_groq.replies["chunk_1.ogg"] = response(
        segments=[{"start": 3, "end": 4, "text": "X"}, {"start": 20, "end": 21, "text": "b"}, {"start": 48, "end": 49, "text": "Y"}],
        words=words(3, 20, 48),
    )
    fake_groq.replies["chunk_2.ogg"] = response(
        segments=[{"start": 3, "end": 4, "text": "Y"}, {"start": 10, "end": 12, "text": "c"}],
        words=words(3, 10),
    )
    tr.transcribe(video.id)

    db.expire_all()
    transcript = db.get(Transcript, video.id)
    assert [s["text"] for s in transcript.segments] == ["a", "X", "b", "Y", "c"]
    assert [s["start"] for s in transcript.segments] == [1.0, 43.0, 60.0, 88.0, 95.0]
    assert [w["start"] for w in storage["bytes"][transcript.words_r2_key]] == [1.0, 43.0, 60.0, 88.0, 95.0]
    assert len(fake_groq.calls) == 3


def test_missing_audio_artifact_fails_the_video(db, make_user, make_video, storage, rq, io_queue):
    v = make_video(make_user("noaudio"), status=VideoStatus.processing, artifacts={})
    with pytest.raises(ValueError, match="audio_key"):
        tr.transcribe(v.id)
    db.expire_all()
    assert db.get(Video, v.id).status == VideoStatus.error
    io_queue.enqueue.assert_not_called()


def test_provider_error_propagates_and_nothing_is_saved(db, video, storage, rq, io_queue, fake_groq):
    fake_groq.replies["audio.ogg"] = RuntimeError("groq 503")
    with pytest.raises(RuntimeError, match="groq 503"):
        tr.transcribe(video.id)
    db.expire_all()
    assert db.get(Transcript, video.id) is None
    assert db.get(Video, video.id).status == VideoStatus.error
    io_queue.enqueue.assert_not_called()


def test_work_directory_is_always_cleaned_up(db, video, storage, rq, io_queue, fake_groq, monkeypatch):
    made = []
    real = tr.tempfile.mkdtemp
    monkeypatch.setattr(tr.tempfile, "mkdtemp", lambda: made.append(real()) or made[-1])
    fake_groq.replies["audio.ogg"] = RuntimeError("fail")
    with pytest.raises(RuntimeError):
        tr.transcribe(video.id)
    assert made and not os.path.exists(made[0])


def test_already_transcribed_videos_are_skipped(db, video, storage, rq, io_queue, fake_groq):
    db.add(Transcript(video_id=video.id, provider="groq", model="m", segments=[], words_r2_key="k"))
    db.commit()
    tr.transcribe(video.id)
    assert fake_groq.calls == [] and "downloaded" not in storage
    io_queue.enqueue.assert_not_called()
