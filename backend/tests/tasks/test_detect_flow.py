"""Detect, end to end: the two-pass DeepSeek flow with a scripted fake model."""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from openai import APIStatusError

import app.tasks.detect as detect_module
import app.workers.contract as contract
import app.workers.queues as queues
from app.db.models import Clip, Job, Moment, RankingRun, Transcript, Video, VideoStatus


def api_error(status):
    request = httpx.Request("POST", "https://api.deepseek.test/chat")
    return APIStatusError("upstream", response=httpx.Response(status, request=request), body=None)


def completion(payload, prompt=100, out=20):
    content = payload if isinstance(payload, str) or payload is None else json.dumps(payload)
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=out),
    )


def moment(start, end, title="A good bit", **scores):
    body = dict(
        start=start, end=end, type="insight", title=title, reason="because", hook=0.9,
        completeness=0.8, shareability=0.7, visual=0.5, transcript_excerpt="words words",
    )
    body.update(scores)
    return body


class FakeDeepSeek:
    """Routes by what is being asked: segmentation vs extraction (and which section)."""

    def __init__(self):
        self.sections = {"sections": []}
        self.moments_by_topic = {}
        self.default_moments = {"moments": []}
        self.calls = []
        self.fail = None   # callable(kind, n) -> exception or None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, model, messages, response_format, temperature):
        system = messages[0]["content"]
        kind = "segment" if "split a timestamped video transcript" in system else "extract"
        self.calls.append((kind, messages[1]["content"], system))
        if self.fail:
            err = self.fail(kind, len(self.calls))
            if err:
                raise err
        if kind == "segment":
            return completion(self.sections)
        for topic, payload in self.moments_by_topic.items():
            if f"This section is about: {topic}." in system:
                return completion(payload)
        return completion(self.default_moments)


@pytest.fixture()
def ds(monkeypatch):
    fake = FakeDeepSeek()
    monkeypatch.setattr(detect_module, "client", fake)
    monkeypatch.setattr(detect_module.time, "sleep", lambda s: None)
    return fake


@pytest.fixture()
def rq(monkeypatch):
    monkeypatch.setattr(contract, "get_current_job", lambda: SimpleNamespace(id="rq-detect", retries_left=0))


@pytest.fixture()
def pools(monkeypatch):
    cpu, io = MagicMock(), MagicMock()
    monkeypatch.setattr(queues, "cpu_queue", cpu)
    monkeypatch.setattr(queues, "io_queue", io)
    return SimpleNamespace(cpu=cpu, io=io)


def make_words(duration=600):
    """Half a second per word, with a clear pause after every ten words (a sentence)."""
    words, t = [], 0.0
    for i in range(int(duration * 1.5)):
        words.append({"word": f"w{i}", "start": round(t, 2), "end": round(t + 0.4, 2)})
        t += 0.5 + (1.0 if i % 10 == 9 else 0.0)
        if t > duration:
            break
    return words


@pytest.fixture()
def video(db, make_user, make_video):
    v = make_video(
        make_user("detector"), status=VideoStatus.processing, duration_sec=600,
        artifacts={"features_key": "artifacts/x/features.json", "words_key": "artifacts/x/words.json"},
    )
    segments = [{"start": float(i * 30), "end": float(i * 30 + 30), "text": f"line {i}", "speaker": None} for i in range(20)]
    db.add(Transcript(video_id=v.id, language="en", provider="groq", model="m", segments=segments, words_r2_key="artifacts/x/words.json"))
    db.commit()
    return v


@pytest.fixture()
def storage(monkeypatch):
    store = {
        "artifacts/x/words.json": make_words(),
        "artifacts/x/features.json": {"rms": [], "silences": []},
    }
    monkeypatch.setattr(detect_module, "download_bytes", lambda key: json.dumps(store[key]).encode())
    return store


def two_sections(ds):
    ds.sections = {"sections": [
        {"start": "0:00:00", "end": "0:05:00", "topic": "intro"},
        {"start": "0:05:00", "end": "0:10:00", "topic": "outro"},
    ]}
    ds.moments_by_topic = {
        "intro": {"moments": [moment("0:01:00", "0:01:30", "Opening hook")]},
        "outro": {"moments": [moment("0:07:00", "0:07:40", "Big finish", hook=0.5)]},
    }


def state(db, video):
    db.expire_all()
    return db.get(Video, video.id)


# ---------------------------------------------------------------- the whole task


def test_detect_stores_moments_queues_a_render_per_moment_and_marks_the_video_ready(db, video, ds, storage, rq, pools):
    two_sections(ds)
    detect_module.detect(video.id)

    assert state(db, video).status == VideoStatus.ready
    moments = db.query(Moment).filter_by(video_id=video.id).all()
    assert sorted(m.title for m in moments) == ["Big finish", "Opening hook"]
    hook = next(m for m in moments if m.title == "Opening hook")
    assert hook.raw_start_sec == 60 and hook.raw_end_sec == 90
    # snapped outward to clean boundaries and padded, so never tighter than the citation
    assert float(hook.start_sec) <= 60 and float(hook.end_sec) >= 90
    assert 20 <= float(hook.end_sec) - float(hook.start_sec) <= detect_module.MAX_LEN
    assert hook.scores["final"] == pytest.approx(0.4 * 0.9 + 0.3 * 0.7 + 0.2 * 0.8 + 0.1 * 0.5, abs=1e-3)
    assert hook.status == "kept" and hook.source == "auto"

    run = db.query(RankingRun).filter_by(video_id=video.id).one()
    assert run.status == "done" and run.prompt_version == detect_module.PROMPT_VERSION
    assert run.est_cost_usd is not None

    clips = db.query(Clip).filter_by(video_id=video.id).all()
    assert len(clips) == 2 and all(c.status == "queued" and c.user_id == video.user_id for c in clips)
    assert all(set(c.params) == {"start", "end", "format", "captions"} for c in clips)
    assert {c.moment_id for c in clips} == {m.id for m in moments}

    assert pools.cpu.enqueue.call_count == 2
    queued = {call.args[2]["clip_id"] for call in pools.cpu.enqueue.call_args_list}
    assert queued == {str(c.id) for c in clips}
    assert all(call.args[0] == "app.tasks.render.render" for call in pools.cpu.enqueue.call_args_list)
    pools.io.enqueue.assert_not_called()


def test_best_scored_moment_is_queued_first(db, video, ds, storage, rq, pools):
    two_sections(ds)
    detect_module.detect(video.id)
    order = [call.args[2]["clip_id"] for call in pools.cpu.enqueue.call_args_list]
    first = db.get(Clip, uuid.UUID(order[0]))
    assert db.get(Moment, first.moment_id).title == "Opening hook"  # hook 0.9 beats 0.5


def test_job_metrics_report_tokens_cost_and_coverage(db, video, ds, storage, rq, pools):
    two_sections(ds)
    detect_module.detect(video.id)
    metrics = db.query(Job).filter_by(video_id=video.id, type="detect").one().metrics
    assert metrics["sections_count"] == 2 and metrics["moments_returned"] == 2
    assert metrics["moments_kept"] == 2 and metrics["clips_queued"] == 2
    assert metrics["input_tokens"] == 300 and metrics["output_tokens"] == 60  # 3 calls x (100, 20)
    expected_cost = round(300 / 1e6 * detect_module.DEEPSEEK_IN_PER_MTOK + 60 / 1e6 * detect_module.DEEPSEEK_OUT_PER_MTOK, 6)
    assert metrics["est_cost_usd"] == expected_cost
    assert 0 < metrics["timeline_coverage_pct"] <= 100


def test_each_section_is_mined_with_only_its_own_slice(db, video, ds, storage, rq, pools):
    two_sections(ds)
    detect_module.detect(video.id)
    extracts = [c for c in ds.calls if c[0] == "extract"]
    assert len(extracts) == 2
    intro = next(c for c in extracts if "intro" in c[2])
    outro = next(c for c in extracts if "outro" in c[2])
    assert "line 1" in intro[1] and "line 15" not in intro[1]
    assert "line 15" in outro[1] and "line 1\n" not in outro[1]


def test_overlapping_duplicates_are_dropped(db, video, ds, storage, rq, pools):
    two_sections(ds)
    ds.moments_by_topic = {
        "intro": {"moments": [moment("0:01:00", "0:01:30", "Original")]},
        "outro": {"moments": [moment("0:01:02", "0:01:31", "Same moment again", hook=0.1)]},
    }
    detect_module.detect(video.id)
    titles = [m.title for m in db.query(Moment).filter_by(video_id=video.id)]
    assert titles == ["Original"]
    assert db.query(Job).filter_by(type="detect").one().metrics["dropped_overlap"] == 1


@pytest.mark.parametrize("start,end", [("0:01:00", "0:01:05"), ("0:01:00", "0:03:30")])
def test_moments_outside_the_allowed_length_are_discarded(db, video, ds, storage, rq, pools, start, end):
    ds.sections = {"sections": [{"start": "0:00:00", "end": "0:05:00", "topic": "intro"}]}
    ds.moments_by_topic = {"intro": {"moments": [moment(start, end)]}}
    detect_module.detect(video.id)
    assert db.query(Moment).count() == 0
    assert state(db, video).status == VideoStatus.ready  # nothing qualified is not a failure
    pools.cpu.enqueue.assert_not_called()


def test_no_sections_falls_back_to_one_whole_video_pass(db, video, ds, storage, rq, pools):
    ds.sections = {"sections": []}
    ds.default_moments = {"moments": [moment("0:02:00", "0:02:30", "Found anyway")]}
    detect_module.detect(video.id)
    kinds = [c[0] for c in ds.calls]
    assert kinds == ["segment", "extract"]
    assert [m.title for m in db.query(Moment)] == ["Found anyway"]


def test_unparseable_model_output_yields_no_moments_but_does_not_fail(db, video, ds, storage, rq, pools):
    ds.sections = {"sections": [{"start": "0:00:00", "end": "0:05:00", "topic": "intro"}]}
    original = ds.create

    def create(model, messages, response_format, temperature):
        if "split a timestamped" in messages[0]["content"]:
            return original(model, messages, response_format, temperature)
        return completion("this is not json {")

    ds.chat.completions.create = create
    detect_module.detect(video.id)
    assert db.query(Moment).count() == 0 and state(db, video).status == VideoStatus.ready


def test_sections_are_capped_in_count(db, video, ds, storage, rq, pools, monkeypatch):
    monkeypatch.setattr(detect_module, "MAX_SECTIONS", 2)
    ds.sections = {"sections": [
        {"start": f"0:0{i}:00", "end": f"0:0{i + 1}:00", "topic": f"t{i}"} for i in range(6)
    ]}
    detect_module.detect(video.id)
    assert len([c for c in ds.calls if c[0] == "extract"]) == 2


def test_features_are_optional(db, video, ds, storage, rq, pools):
    video_row = db.get(Video, video.id)
    video_row.artifacts = {"words_key": "artifacts/x/words.json"}
    db.commit()
    two_sections(ds)
    detect_module.detect(video.id)
    assert db.query(Moment).count() == 2


# ---------------------------------------------------------------- failures and retries


def test_transient_provider_errors_are_retried_locally(db, video, ds, storage, rq, pools):
    two_sections(ds)
    ds.fail = lambda kind, n: api_error(503) if n <= 2 else None
    detect_module.detect(video.id)
    assert state(db, video).status == VideoStatus.ready
    assert len(ds.calls) == 2 + 3  # two failed segment attempts, then segment + 2 extracts


def test_a_provider_that_stays_down_fails_the_run_and_the_video(db, video, ds, storage, rq, pools):
    ds.fail = lambda kind, n: api_error(503)
    with pytest.raises(APIStatusError):
        detect_module.detect(video.id)
    assert len(ds.calls) == detect_module.DEEPSEEK_MAX_ATTEMPTS
    assert db.query(RankingRun).filter_by(video_id=video.id).one().status == "error"
    assert state(db, video).status == VideoStatus.error
    assert db.query(Moment).count() == 0 and db.query(Clip).count() == 0
    pools.cpu.enqueue.assert_not_called()


def test_non_retryable_errors_are_not_retried(db, video, ds, storage, rq, pools):
    ds.fail = lambda kind, n: api_error(401)
    with pytest.raises(APIStatusError):
        detect_module.detect(video.id)
    assert len(ds.calls) == 1


def test_missing_transcript_fails_clearly(db, make_user, make_video, ds, storage, rq, pools):
    v = make_video(make_user("notranscript"), status=VideoStatus.processing)
    with pytest.raises(RuntimeError, match="No transcript"):
        detect_module.detect(v.id)
    assert state(db, v).status == VideoStatus.error


# ---------------------------------------------------------------- idempotency


def test_a_completed_run_is_not_repeated(db, video, ds, storage, rq, pools):
    db.add(RankingRun(video_id=video.id, prompt_version="x", model="m", status="done"))
    db.commit()
    detect_module.detect(video.id)
    assert ds.calls == []
    pools.cpu.enqueue.assert_not_called()


def test_a_half_finished_run_does_not_count_as_done(db, video, ds, storage, rq, pools):
    db.add(RankingRun(video_id=video.id, prompt_version="x", model="m", status="running"))
    db.commit()
    two_sections(ds)
    detect_module.detect(video.id)
    assert state(db, video).status == VideoStatus.ready and ds.calls


# ---------------------------------------------------------------- pieces


def test_retry_helper_returns_the_value_and_only_sleeps_between_attempts(ds, monkeypatch):
    sleeps = []
    monkeypatch.setattr(detect_module.time, "sleep", sleeps.append)
    attempts = iter([api_error(429), api_error(502), "ok"])

    def call():
        item = next(attempts)
        if isinstance(item, Exception):
            raise item
        return item

    assert detect_module._deepseek_with_retry(call) == "ok"
    assert len(sleeps) == 2 and sleeps[0] < sleeps[1] + 1  # backoff grows (plus jitter)


def test_extract_skips_the_call_for_an_empty_slice(ds):
    assert detect_module._extract("   \n") == ([], None)
    assert ds.calls == []


def test_extract_handles_empty_model_content(ds):
    ds.chat.completions.create = lambda **k: completion(None, prompt=7, out=1)
    moments, usage = detect_module._extract("[0:00:01] hi")
    assert moments == [] and usage.prompt_tokens == 7


def test_segmentation_skips_a_window_that_returns_garbage_and_sums_usage(ds, monkeypatch):
    monkeypatch.setattr(detect_module, "SECTION_INPUT_CHAR_BUDGET", 30)
    replies = iter([
        completion({"sections": [{"start": "0:00:00", "end": "0:01:00", "topic": "a"}]}, prompt=10, out=2),
        completion("garbage", prompt=10, out=2),
        completion(None, prompt=10, out=2),
    ])
    ds.chat.completions.create = lambda **k: next(replies)
    script = "\n".join(f"[0:0{i}:00] line number {i}" for i in range(3))
    sections, usage = detect_module._segment_transcript(script)
    assert [s.topic for s in sections] == ["a"]
    assert usage.prompt_tokens == 30 and usage.completion_tokens == 6


def test_segmentation_without_usage_info(ds):
    reply = completion({"sections": []})
    reply.usage = None
    ds.chat.completions.create = lambda **k: reply
    sections, usage = detect_module._segment_transcript("[0:00:01] hi")
    assert sections == [] and usage.prompt_tokens == 0
