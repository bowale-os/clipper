"""job_contract run against a real (SQLite) database: claiming, skipping, retrying,
failing, cancelling, and fanning out follow-on jobs."""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import app.workers.contract as contract
import app.workers.queues as queues_module
from app.db.models import Job, Video, VideoStatus
from app.workers.contract import ReadOnlyVideo, WorkCancelled, job_contract


@pytest.fixture()
def rq_job(monkeypatch):
    """Stands in for the RQ job currently executing."""
    job = SimpleNamespace(id="rq-1", retries_left=0)
    monkeypatch.setattr(contract, "get_current_job", lambda: job)
    return job


@pytest.fixture()
def pools(monkeypatch):
    io, cpu = MagicMock(), MagicMock()
    monkeypatch.setattr(queues_module, "io_queue", io)
    monkeypatch.setattr(queues_module, "cpu_queue", cpu)
    return SimpleNamespace(io=io, cpu=cpu)


@pytest.fixture()
def video(make_user, make_video):
    return make_video(make_user("owner"), status=VideoStatus.processing, pipeline={}, artifacts={})


def state(db, video_id):
    db.expire_all()
    return db.get(Video, video_id)


def jobs(db, video_id):
    db.expire_all()
    return db.query(Job).filter_by(video_id=video_id).all()


# ---------------------------------------------------------------- success


def test_success_records_a_done_job_with_metrics(db, video, rq_job):
    @job_contract("ingest")
    def task(ctx):
        ctx.metrics["frames"] = 12

    task(video.id)
    (job,) = jobs(db, video.id)
    assert job.type == "ingest" and job.status == "done"
    assert job.rq_job_id == "rq-1" and job.finished_at is not None
    assert job.metrics == {"frames": 12}


def test_task_receives_params_and_a_context_for_its_video(db, video, rq_job):
    seen = {}

    @job_contract("render")
    def task(ctx):
        seen.update(params=ctx.params, video_id=ctx.video_id, filename=ctx.video.filename)

    task(video.id, {"clip_id": "c1"})
    assert seen == {"params": {"clip_id": "c1"}, "video_id": video.id, "filename": "talk.mp4"}


def test_missing_params_default_to_empty(db, video, rq_job):
    seen = []

    @job_contract("ingest")
    def task(ctx):
        seen.append(ctx.params)

    task(video.id)
    assert seen == [{}]


def test_wrapper_keeps_the_task_name_for_rq_and_logs():
    @job_contract("ingest")
    def my_task(ctx):
        pass

    assert my_task.__name__ == "my_task"


def test_runs_without_an_rq_job(db, video, monkeypatch):
    monkeypatch.setattr(contract, "get_current_job", lambda: None)

    @job_contract("ingest")
    def task(ctx):
        pass

    task(video.id)
    assert jobs(db, video.id)[0].rq_job_id is None


def test_an_existing_job_row_is_reused_not_duplicated(db, video, rq_job):
    db.add(Job(video_id=video.id, type="ingest", rq_job_id="rq-1", status="queued"))
    db.commit()

    @job_contract("ingest")
    def task(ctx):
        pass

    task(video.id)
    assert len(jobs(db, video.id)) == 1 and jobs(db, video.id)[0].status == "done"


def test_job_is_marked_running_while_the_task_executes(db, video, rq_job):
    during = []

    @job_contract("ingest")
    def task(ctx):
        during.append(jobs(db, ctx.video_id)[0].status)

    task(video.id)
    assert during == ["running"]


# ---------------------------------------------------------------- follow-on jobs


def test_follow_on_jobs_are_enqueued_after_success_on_the_right_pools(db, video, rq_job, pools):
    @job_contract("detect")
    def task(ctx):
        ctx.enqueue_next("app.tasks.render.render", str(video.id), {"clip_id": "a"}, queue="cpu")
        ctx.enqueue_next("app.tasks.transcribe.transcribe", str(video.id))
        pools.cpu.enqueue.assert_not_called()  # nothing is queued while the task is still running

    task(video.id)
    pools.cpu.enqueue.assert_called_once()
    assert pools.cpu.enqueue.call_args.args == ("app.tasks.render.render", str(video.id), {"clip_id": "a"})
    assert pools.cpu.enqueue.call_args.kwargs["retry"] is queues_module.JOB_RETRY
    pools.io.enqueue.assert_called_once()
    assert pools.io.enqueue.call_args.args[0] == "app.tasks.transcribe.transcribe"


def test_follow_on_jobs_are_not_enqueued_when_the_task_fails(db, video, rq_job, pools):
    @job_contract("ingest")
    def task(ctx):
        ctx.enqueue_next("app.tasks.transcribe.transcribe", str(video.id))
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        task(video.id)
    pools.io.enqueue.assert_not_called()


def test_follow_on_state_is_committed_before_it_is_enqueued(db, video, rq_job, pools):
    committed_at_enqueue = []
    pools.io.enqueue.side_effect = lambda *a, **k: committed_at_enqueue.append(
        (jobs(db, video.id)[0].status, state(db, video.id).artifacts.get("audio_key"))
    )

    @job_contract("ingest")
    def task(ctx):
        ctx.set_artifacts(audio_key="audio/x.wav")
        ctx.enqueue_next("app.tasks.transcribe.transcribe", str(video.id))

    task(video.id)
    assert committed_at_enqueue == [("done", "audio/x.wav")]


# ---------------------------------------------------------------- skip_if


def test_skip_if_true_skips_the_work_and_marks_done(db, video, rq_job, pools):
    ran = []

    @job_contract("ingest", skip_if=lambda ctx: True)
    def task(ctx):
        ran.append(1)

    task(video.id)
    assert ran == [] and jobs(db, video.id)[0].status == "done"
    pools.io.enqueue.assert_not_called()


def test_skip_if_false_runs_the_work(db, video, rq_job):
    ran = []

    @job_contract("ingest", skip_if=lambda ctx: False)
    def task(ctx):
        ran.append(1)

    task(video.id)
    assert ran == [1]


def test_skip_if_can_cancel_the_job(db, video, rq_job):
    def gone(ctx):
        raise WorkCancelled("clip was deleted")

    ran = []

    @job_contract("render", skip_if=gone)
    def task(ctx):
        ran.append(1)

    task(video.id)  # returns normally so RQ does not retry
    assert ran == []


# ---------------------------------------------------------------- cancellation


def test_deleted_video_cancels_instead_of_failing(db, rq_job):
    @job_contract("ingest")
    def task(ctx):
        raise AssertionError("must not run")

    task(uuid.uuid4())  # no exception, so RQ will not retry
    assert db.query(Job).count() == 0


def test_task_raising_work_cancelled_closes_the_job_as_cancelled(db, video, rq_job):
    @job_contract("render")
    def task(ctx):
        raise WorkCancelled("clip row is gone")

    task(video.id)
    (job,) = jobs(db, video.id)
    assert job.status == "cancelled" and job.error == "clip row is gone"
    assert state(db, video.id).status == VideoStatus.processing  # video untouched


def test_cancelled_tasks_skip_the_failure_hook(db, video, rq_job):
    hook = MagicMock()

    @job_contract("render", fail_video=False, on_failure=hook)
    def task(ctx):
        raise WorkCancelled("gone")

    task(video.id)
    hook.assert_not_called()


# ---------------------------------------------------------------- failure


def test_final_failure_errors_the_video_and_the_job_and_reraises(db, video, rq_job):
    rq_job.retries_left = 0

    @job_contract("transcribe")
    def task(ctx):
        raise RuntimeError("groq exploded")

    with pytest.raises(RuntimeError, match="groq exploded"):
        task(video.id)
    v = state(db, video.id)
    assert v.status == VideoStatus.error and v.pipeline["error"] == "groq exploded"
    (job,) = jobs(db, video.id)
    assert job.status == "error" and job.error == "groq exploded" and job.finished_at is not None


def test_failure_with_retries_left_flags_retrying_but_does_not_fail_the_video(db, video, rq_job):
    rq_job.retries_left = 2

    @job_contract("transcribe")
    def task(ctx):
        raise RuntimeError("503 from provider")

    with pytest.raises(RuntimeError):
        task(video.id)
    v = state(db, video.id)
    assert v.status == VideoStatus.processing
    assert v.pipeline["retrying"] is True and "error" not in v.pipeline
    assert jobs(db, video.id)[0].status == "error"


def test_retry_flag_is_cleared_when_the_next_attempt_starts(db, video, rq_job):
    rq_job.retries_left = 1
    attempts = []

    @job_contract("transcribe")
    def task(ctx):
        attempts.append(state(db, ctx.video_id).pipeline.get("retrying"))
        if len(attempts) == 1:
            raise RuntimeError("transient")

    with pytest.raises(RuntimeError):
        task(video.id)
    assert state(db, video.id).pipeline["retrying"] is True

    rq_job.retries_left = 0
    task(video.id)
    assert attempts == [None, None]
    assert "retrying" not in state(db, video.id).pipeline
    assert len(jobs(db, video.id)) == 1 and jobs(db, video.id)[0].status == "done"


def test_fail_video_false_leaves_the_video_alone(db, video, rq_job):
    @job_contract("render", fail_video=False)
    def task(ctx):
        raise RuntimeError("bad clip")

    with pytest.raises(RuntimeError):
        task(video.id)
    v = state(db, video.id)
    assert v.status == VideoStatus.processing and "error" not in v.pipeline
    assert jobs(db, video.id)[0].status == "error"


def test_failure_hook_runs_in_the_failure_transaction_with_params(db, video, rq_job):
    received = {}

    def hook(session, params, err):
        received.update(params=params, err=str(err), same_video=session.get(Video, video.id) is not None)

    @job_contract("render", fail_video=False, on_failure=hook)
    def task(ctx):
        raise RuntimeError("encode failed")

    with pytest.raises(RuntimeError):
        task(video.id, {"clip_id": "c9"})
    assert received == {"params": {"clip_id": "c9"}, "err": "encode failed", "same_video": True}


def test_failure_recreates_a_missing_job_row(db, video, rq_job):
    @job_contract("ingest")
    def task(ctx):
        db.query(Job).delete()
        db.commit()
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        task(video.id)
    (job,) = jobs(db, video.id)
    assert job.status == "error" and job.rq_job_id == "rq-1"


# ---------------------------------------------------------------- context helpers


def test_progress_set_status_artifacts_and_columns_persist_and_refresh_the_snapshot(db, video, rq_job):
    snapshots = {}

    @job_contract("ingest")
    def task(ctx):
        alias = ctx.video  # tasks bind this once at the top
        ctx.progress(stage="extracting", pct=40)
        ctx.progress(pct=60)
        ctx.set_artifacts(audio_key="a.wav")
        ctx.set_artifacts(width=1920)
        ctx.update_video(duration_sec=12.5)
        ctx.set_status(VideoStatus.ready)
        snapshots["pipeline"] = dict(alias.pipeline)
        snapshots["status"] = alias.status

    task(video.id)
    v = state(db, video.id)
    assert v.pipeline["stage"] == "extracting" and v.pipeline["progress_pct"] == 60
    assert v.artifacts == {"audio_key": "a.wav", "width": 1920}
    assert float(v.duration_sec) == 12.5 and v.status == VideoStatus.ready
    assert snapshots["pipeline"]["progress_pct"] == 60 and snapshots["status"] == VideoStatus.ready


def test_updates_merge_instead_of_replacing(db, make_user, make_video, rq_job):
    v0 = make_video(make_user("m"), pipeline={"keep": 1}, artifacts={"keep": 2})

    @job_contract("ingest")
    def task(ctx):
        ctx.progress(stage="s")
        ctx.set_artifacts(new=3)

    task(v0.id)
    v = state(db, v0.id)
    assert v.pipeline["keep"] == 1 and v.pipeline["stage"] == "s"
    assert v.artifacts == {"keep": 2, "new": 3}


def test_mutating_a_video_that_vanished_mid_task_raises(db, video, rq_job):
    @job_contract("ingest")
    def task(ctx):
        db.query(Video).delete()
        db.commit()
        ctx.progress(pct=1)

    with pytest.raises(RuntimeError, match="not found"):
        task(video.id)


def test_context_video_is_read_only(db, video, rq_job):
    @job_contract("ingest")
    def task(ctx):
        ctx.video.status = VideoStatus.ready

    with pytest.raises(AttributeError, match="read-only"):
        task(video.id)


def test_tx_lock_option_and_commit(db, video, rq_job):
    @job_contract("ingest")
    def task(ctx):
        with ctx.tx(lock_video=True) as session:
            session.get(Video, ctx.video_id).filename = "renamed.mp4"

    task(video.id)
    assert state(db, video.id).filename == "renamed.mp4"


def test_readonly_wrapper_reads_through_and_has_a_repr(video):
    wrapped = ReadOnlyVideo(video)
    assert wrapped.filename == "talk.mp4" and "ReadOnlyVideo" in repr(wrapped)
