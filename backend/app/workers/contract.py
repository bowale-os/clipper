from dataclasses import dataclass, field
from rq import get_current_job
from sqlalchemy import select
from sqlalchemy.orm import Session
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Optional
import functools
import logging

from app.db.session import session_scope
from app.db.models import Job, Video, VideoStatus

logger = logging.getLogger(__name__)


class WorkCancelled(Exception):
    """The row this job exists to work on is gone, so the job can never succeed.

    Distinct from a failure on purpose. A Groq 503 is transient and worth the four
    attempts JOB_RETRY buys; a deleted video is not, and retrying one only fills the
    log with the same traceback every few minutes for a quarter of an hour. Contract
    catches this, closes the job out as cancelled, and returns normally so RQ sees a
    finished job rather than a failed one with retries left.

    Raise it from a task whose own subject has been deleted (see render's clip lookup).
    """


class ReadOnlyVideo:
    """A detached snapshot of the Video row, with writes made impossible.

    Tasks used to hold a live Session for their whole run and mutate `ctx.video`
    directly. They no longer hold a session at all (see job_contract), so a plain
    detached instance would accept `video.pipeline = ...` and silently drop it — the
    attribute would change in memory and never reach the database. That failure is
    invisible: progress would stop advancing, and ingest's artifacts would never appear,
    surfacing one stage later as a baffling "missing audio_key".

    So writes raise instead. Persisting a change means going through ctx.progress(),
    ctx.set_status(), ctx.set_artifacts() or ctx.update_video(), each of which opens its
    own short transaction.
    """

    __slots__ = ("_video",)

    def __init__(self, video: Video):
        object.__setattr__(self, "_video", video)

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_video"), name)

    def __setattr__(self, name, value):
        raise AttributeError(
            f"ctx.video is a read-only snapshot, so setting {name!r} would be silently "
            f"lost. Use ctx.progress(...) / ctx.set_status(...) / ctx.set_artifacts(...) "
            f"/ ctx.update_video(...) to persist it."
        )

    def __repr__(self):
        return f"ReadOnlyVideo({object.__getattribute__(self, '_video')!r})"


@dataclass
class TaskContext:
    video_id: object
    job_id: object
    params: dict
    video: ReadOnlyVideo
    metrics: dict = field(default_factory=dict)
    next_stages: list = field(default_factory=list)

    @contextmanager
    def tx(self, lock_video: bool = False):
        """Open a short transaction for a burst of database work.

        Slow work — an API call, an ffmpeg run, an R2 transfer — must happen OUTSIDE
        this block. Postgres terminates any session left idle inside a transaction for
        idle_in_transaction_session_timeout (5 minutes on this database), which is how a
        detect job died mid-Gemini-call on 2026-07-18. Between `with` blocks the task
        holds no connection at all, and an idle *pooled* connection is never reaped
        (idle_session_timeout is 0), so the wait costs nothing.

        lock_video takes SELECT ... FOR UPDATE on the video row for the duration of this
        block. Needed when read-modify-writing video.pipeline or video.artifacts, since a
        JSON column rewrites the whole document and two stages would clobber each other.
        The lock lasts only as long as the block, not the whole job.
        """
        with session_scope() as session:
            if lock_video:
                session.get(Video, self.video_id, with_for_update=True)
            yield session

    def _mutate_video(self, pipeline_updates=None, artifacts_updates=None, **columns):
        """Apply changes to the video row in one short, locked transaction, then refresh
        the local snapshot so subsequent reads see what was written."""
        with self.tx(lock_video=True) as session:
            video = session.get(Video, self.video_id)
            if video is None:
                raise RuntimeError(f"Video {self.video_id} not found")

            if pipeline_updates:
                video.pipeline = {**(video.pipeline or {}), **pipeline_updates}
            if artifacts_updates:
                video.artifacts = {**(video.artifacts or {}), **artifacts_updates}
            for name, value in columns.items():
                setattr(video, name, value)

            session.flush()

        # session_scope closed the session, so `video` is now detached but still carries
        # its loaded values (expire_on_commit=False). Swap it into the *existing* proxy
        # rather than building a new one: tasks bind `video = ctx.video` once at the top,
        # and replacing the proxy would leave that alias pointing at a stale snapshot.
        object.__setattr__(self.video, "_video", video)

    def progress(self, *, stage: str | None = None, pct: int | None = None) -> None:
        """Merge stage/progress into video.pipeline."""
        updates = {}
        if stage is not None:
            updates["stage"] = stage
        if pct is not None:
            updates["progress_pct"] = pct
        self._mutate_video(pipeline_updates=updates)

    def set_status(self, status: VideoStatus) -> None:
        self._mutate_video(status=status)

    def set_artifacts(self, **keys) -> None:
        """Merge keys into video.artifacts (audio_key, features_key, ...)."""
        self._mutate_video(artifacts_updates=keys)

    def update_video(self, **columns) -> None:
        """Set plain columns on the video row (duration_sec, ...)."""
        self._mutate_video(**columns)

    def enqueue_next(self, task_path: str, *args, queue: str = "io") -> None:
        """Record a follow-on job to enqueue once this job has finished successfully.

        Must not call Queue.enqueue directly from a task — a stage's durable state
        (e.g. ingest's audio_key) has to be committed before the next stage reads it, and
        the next stage would see a video row without it if enqueued any earlier.

        Call more than once to fan out: detect queues one render per moment. `queue`
        picks the worker pool, since renders are CPU work and the pipeline stages are IO.
        """
        self.next_stages.append((task_path, args, queue))


# A guard that reports whether this stage's work is already done, so a retry can skip it.
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


def _mark_video_retrying(session: Session, video_id) -> None:
    """Flag that this video is between attempts, without failing it.

    The video keeps its own status: nothing has gone wrong from the user's side yet,
    and it may well succeed on the next attempt. This only exists so the frontend can
    say something during the backoff, which is up to ten minutes of a frozen stage.
    """
    video = session.get(Video, video_id)
    if video is None:
        return
    video.pipeline = {**(video.pipeline or {}), "retrying": True}


def _clear_video_retrying(video: Video) -> None:
    """Drop the retry flag as soon as an attempt is actually running again."""
    pipeline = video.pipeline or {}
    if "retrying" in pipeline:
        video.pipeline = {k: v for k, v in pipeline.items() if k != "retrying"}


def _mark_job_failed(session: Session, job_type: str, video_id, cjob_id, err: Exception) -> None:
    """Put the Job row into the error state, recreating it if it somehow went missing."""
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
    will_retry: bool,
    on_failure: Optional[FailureHook],
) -> None:
    """Persist the error in its own transaction, independent of anything the task held."""
    with session_scope() as session:
        if fail_video:
            _mark_video_failed(session, video_id, err)
        elif will_retry:
            _mark_video_retrying(session, video_id)

        _mark_job_failed(session, job_type, video_id, cjob_id, err)

        if on_failure is not None:
            on_failure(session, params, err)


def _close_cancelled(job_type: str, video_id, job_id, err: Exception) -> None:
    """Close a job out as cancelled and say so in the log.

    job_id may be None, or may name a row that no longer exists: a cancel raised from
    skip_if rolls back the transaction that had just inserted it, and a cancel caused
    by a deleted video took the Job rows with it on cascade. Both are fine, and neither
    is worth a second error on top of the first.
    """
    logger.info("%s cancelled for video %s: %s", job_type, video_id, err)

    if job_id is None:
        return

    with session_scope() as session:
        job = session.get(Job, job_id)
        if job is not None:
            job.status = "cancelled"
            job.error = str(err)
            job.finished_at = datetime.now(timezone.utc)


def _will_retry(current_job) -> bool:
    """Whether RQ will run this job again after the current failure.

    retries_left is decremented in Job.retry(), which the worker calls only after the
    job function has already raised — so inside the failure path below it still holds
    this attempt's value. Mirrors RQ's own Job.should_retry.
    """
    return bool(current_job is not None and current_job.retries_left)


def job_contract(
    job_type: str,
    skip_if: Optional[SkipIf] = None,
    fail_video: bool = True,
    on_failure: Optional[FailureHook] = None,
):
    """Wrap a task with Job bookkeeping and durable failure recording.

    The task body runs holding NO database transaction. Contract takes one short
    transaction to claim the job, releases it, runs the task, then takes another to
    close the job out. A task that needs the database opens its own short transaction
    via ctx.tx(); a task that needs to change the video row calls ctx.progress() and
    friends. This is deliberate: the previous design held one transaction for the whole
    job, so any stage doing minutes of network IO sat idle inside a transaction and was
    reaped by Postgres at the 5 minute mark.

    fail_video:  whether a crash marks the whole source Video as errored. True for the
                 pipeline stages, where a failure really does mean the video is unusable.
                 False for per-item work like render, where one bad clip says nothing
                 about the video or the other clips. Suppressed while retries remain, so
                 a video does not flap into the error state between attempts.
    on_failure:  optional callback run inside the failure transaction, for a task to
                 record its own error state (see render's clip tombstone).
    """
    def decorator(main_fn):
        @functools.wraps(main_fn)
        def wrapper(video_id, params=None):
            current_job = get_current_job()
            cjob_id = current_job.id if current_job else None

            # Phase 1 — claim the job. Short transaction; released before any real work.
            ctx = None
            try:
                with session_scope() as session:
                    video = session.get(Video, video_id)
                    if not video:
                        # Deleted while this job sat on the queue.
                        raise WorkCancelled(f"video {video_id} was deleted")

                    stmt = select(Job).where(Job.rq_job_id == cjob_id)
                    job = session.execute(stmt).scalar_one_or_none()

                    if job is None:
                        job = Job(
                            video_id=video.id,
                            type=job_type,
                            rq_job_id=cjob_id,
                            started_at=datetime.now(timezone.utc),
                            metrics={},
                        )
                        session.add(job)
                    job.status = "running"
                    # A previous attempt may have left the retry flag on. This attempt
                    # is running now, so the video is moving again either way.
                    _clear_video_retrying(video)
                    session.flush()

                    ctx = TaskContext(
                        video_id=video.id,
                        job_id=job.id,
                        params=params or {},
                        video=ReadOnlyVideo(video),
                    )
                    skip = skip_if is not None and skip_if(ctx)
                    if skip:
                        job.status = "done"
                        job.finished_at = datetime.now(timezone.utc)
            except WorkCancelled as e:
                # Two ways to land here: the video is gone, or skip_if went looking for
                # the task's own subject and found it gone too (render loads its Clip
                # there). Either way the work no longer exists, so close it out rather
                # than letting it raise into four attempts at the same dead row.
                _close_cancelled(job_type, video_id, ctx.job_id if ctx else None, e)
                return

            if skip:
                return

            # Phase 2 — the actual work, holding no transaction and no connection.
            try:
                main_fn(ctx)
            except WorkCancelled as e:
                # Returning rather than re-raising is the point: RQ only retries a job
                # whose function raised, and this one is never going to succeed. Note
                # this skips on_failure too, so render leaves no error tombstone on a
                # clip row that is already gone.
                _close_cancelled(job_type, video_id, ctx.job_id, e)
                return
            except Exception as e:
                # Only fail the video once RQ has run out of retries; otherwise a
                # transient upstream error would show the user a failed video that
                # silently fixes itself minutes later.
                logger.exception("%s failed for video %s", job_type, video_id)
                _record_failure(
                    job_type,
                    video_id,
                    cjob_id,
                    params or {},
                    e,
                    fail_video and not _will_retry(current_job),
                    _will_retry(current_job),
                    on_failure,
                )
                raise

            # Phase 3 — close the job out. Short transaction.
            with session_scope() as session:
                job = session.get(Job, ctx.job_id)
                if job is not None:
                    job.status = "done"
                    job.finished_at = datetime.now(timezone.utc)
                    job.metrics = ctx.metrics

            # Only reachable once the task and its bookkeeping have both committed, so
            # the next stage never starts before this one's durable state is real.
            if ctx.next_stages:
                from app.workers.queues import JOB_RETRY, cpu_queue, io_queue
                pools = {"io": io_queue, "cpu": cpu_queue}
                for task_path, args, queue_name in ctx.next_stages:
                    pools[queue_name].enqueue(task_path, *args, retry=JOB_RETRY)
        return wrapper
    return decorator
