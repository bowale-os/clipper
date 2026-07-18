from dataclasses import dataclass, field
from rq import get_current_job
from sqlalchemy import select
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from typing import Callable, Optional
import functools

from app.db.session import session_scope
from app.db.models import Job, Video, VideoStatus


@dataclass
class TaskContext:
    db: Session
    video: Video
    job: Job
    params: dict
    metrics: dict = field(default_factory=dict)
    next_stages: list = field(default_factory=list)

    def enqueue_next(self, task_path: str, *args, queue: str = "io") -> None:
        """Record a follow-on job to enqueue once this job's transaction commits.

        Must not call Queue.enqueue directly from a task — a stage's durable state
        (e.g. ingest's audio_key) isn't real until this job's own commit succeeds, and
        the next stage would read a video row that doesn't have it yet if enqueued any
        earlier.

        Call more than once to fan out: detect queues one render per moment. `queue`
        picks the worker pool, since renders are CPU work and the pipeline stages are IO.
        """
        self.next_stages.append((task_path, args, queue))

SkipIf = Callable[["TaskContext"], bool]

# Runs inside the failure transaction so a task can record its own error state
# (e.g. marking one Clip failed) alongside the generic Job bookkeeping.
FailureHook = Callable[[Session, dict, Exception], None]


def _mark_video_failed(session: Session, video_id, err: Exception) -> None:
    """Put the source video into the error state."""
    video = session.get(Video, video_id)
    if video is None:
        return
    video.status = VideoStatus.error
    video.pipeline = {**(video.pipeline or {}), "error": str(err)}


def _mark_job_failed(session: Session, job_type: str, video_id, cjob_id, err: Exception) -> None:
    """Put the Job row into the error state, recreating it if the rollback erased it."""
    job = session.execute(select(Job).where(Job.rq_job_id == cjob_id)).scalar_one_or_none()
    if job is None:
        job = Job(
            video_id=video_id,
            type=job_type,
            rq_job_id=cjob_id,
            started_at=datetime.now(timezone.utc),
            metrics={},
        )
        session.add(job)
    job.status = "error"
    job.error = str(err)
    job.finished_at = datetime.now(timezone.utc)


def _record_failure(
    job_type: str,
    video_id,
    cjob_id,
    params: dict,
    err: Exception,
    fail_video: bool,
    on_failure: Optional[FailureHook],
) -> None:
    """Persist the error in a fresh transaction.

    The task's own session is rolled back on the way out (session_scope discards it), so
    any error bookkeeping written there never commits. This second, independent
    transaction is the only durable record that the job failed.
    """
    with session_scope() as session:
        if fail_video:
            _mark_video_failed(session, video_id, err)

        _mark_job_failed(session, job_type, video_id, cjob_id, err)

        if on_failure is not None:
            on_failure(session, params, err)


def job_contract(
    job_type: str,
    skip_if: Optional[SkipIf] = None,
    fail_video: bool = True,
    on_failure: Optional[FailureHook] = None,
    lock_video: bool = True,
):
    """Wrap a task with session, Job bookkeeping, and durable failure recording.

    fail_video:  whether a crash marks the whole source Video as errored. True for the
                 pipeline stages, where a failure really does mean the video is unusable.
                 False for per-item work like render, where one bad clip says nothing
                 about the video or the other clips.
    on_failure:  optional callback run inside the failure transaction, for a task to
                 record its own error state (see render's clip tombstone).
    lock_video:  whether to SELECT ... FOR UPDATE the video row. True for the pipeline
                 stages: they merge keys into video.pipeline/artifacts, and a JSON column
                 rewrites the whole document, so two concurrent stages would lose one
                 another's writes. False for tasks that only read the video and write
                 their own rows — the lock is held until this job commits, so a render
                 would otherwise hold it across its download, encode and upload, and
                 renders of the same video could never run in parallel.
    """
    def decorator(main_fn):
        @functools.wraps(main_fn)
        def wrapper(video_id, params=None):
            next_stages = []
            with session_scope() as session:
                current_job = get_current_job()
                cjob_id = current_job.id if current_job else None
                video = session.get(Video, video_id, with_for_update=lock_video)
                if not video:
                    raise RuntimeError(f"Video {video_id} not found")

                stmt = select(Job).where(Job.rq_job_id == cjob_id)
                job = session.execute(stmt).scalar_one_or_none()

                if job is None:
                    job = Job(
                        video_id=video.id,
                        type=job_type,
                        status="running",
                        rq_job_id=cjob_id,
                        started_at=datetime.now(timezone.utc),
                        metrics={},
                    )
                    session.add(job)
                    session.flush()

                ctx = TaskContext(session, video, job,params or {}, {})
                if skip_if is not None and skip_if(ctx):
                    job.status = "done"
                    job.finished_at = datetime.now(timezone.utc)
                    return

                try:
                    main_fn(ctx)
                    job.status = "done"
                    job.finished_at = datetime.now(timezone.utc)
                    job.metrics = ctx.metrics
                    next_stages = ctx.next_stages
                except Exception as e:
                    # Discard the poisoned session, then record the failure in its own
                    # transaction — writing it here would just roll back with everything else.
                    session.rollback()
                    _record_failure(
                        job_type, video_id, cjob_id, params or {}, e, fail_video, on_failure
                    )
                    raise

            # Only reachable once `with session_scope()` has exited *without* raising,
            # i.e. session.commit() actually succeeded — so the next stage never starts
            # before this job's own durable state (audio_key, transcript, ...) is real.
            if next_stages:
                from app.workers.queues import cpu_queue, io_queue
                pools = {"io": io_queue, "cpu": cpu_queue}
                for task_path, args, queue_name in next_stages:
                    pools[queue_name].enqueue(task_path, *args)
        return wrapper
    return decorator


