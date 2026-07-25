"""RQ worker entrypoint.

Run from `backend/` so that `app` resolves as a top-level package:

    python -m app.workers.worker_setup

RQ stores tasks as import strings ("app.tasks.render.render") and resolves them when
the job runs, so a worker started from anywhere else boots and idles happily, then
fails every job it pops with ModuleNotFoundError.
"""

import logging
import os

from rq import SimpleWorker, Worker

from app.workers.queues import cpu_queue, io_queue, redis_conn

logger = logging.getLogger(__name__)

# Worker forks a work-horse per job, which isolates crashes and enforces job timeouts
# via signals. Windows has no os.fork, so local runs fall back to SimpleWorker, which
# performs jobs in-process and gives up both. Linux (Railway) gets the real thing.
WorkerClass = Worker if hasattr(os, "fork") else SimpleWorker

_QUEUES_BY_NAME = {cpu_queue.name: cpu_queue, io_queue.name: io_queue}


def _selected_queues() -> list:
    """Which queues this worker drains, from WORKER_QUEUES (comma-separated queue names).

    Defaults to both, drained left to right — a queued render is a user waiting on an
    export, so cpu comes first — which is the old single-worker behaviour. Set it per
    Railway service to isolate the CPU-bound renders from the I/O-bound
    ingest/transcribe/detect: a cpu-worker with WORKER_QUEUES=cpu, an io-worker with
    WORKER_QUEUES=io, so a long ingest can no longer stall an export.

    An unknown name raises at startup: draining nothing would look like a healthy worker
    that silently never picks up a job, which is worse than failing to boot.
    """
    raw = os.getenv("WORKER_QUEUES", "cpu,io")
    names = [n.strip() for n in raw.split(",") if n.strip()]
    try:
        return [_QUEUES_BY_NAME[name] for name in names]
    except KeyError as e:
        raise RuntimeError(
            f"WORKER_QUEUES names an unknown queue {e}; expected some of {sorted(_QUEUES_BY_NAME)}"
        ) from None


QUEUES = _selected_queues()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Starting %s on queues: %s", WorkerClass.__name__, ", ".join(q.name for q in QUEUES))
    # with_scheduler is required, not optional: jobs enqueued with JOB_RETRY back off by
    # an interval, and RQ parks those in the ScheduledJobRegistry. Without a scheduler
    # nothing ever moves them back onto a queue, so a failed job would vanish instead of
    # retrying — quieter and worse than no retry at all.
    WorkerClass(QUEUES, connection=redis_conn).work(with_scheduler=True)


if __name__ == "__main__":
    main()