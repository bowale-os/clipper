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

# Drained left to right: a queued render is a user waiting on an export, while ingest
# is background work nobody is blocked on. With a single worker a long ingest still
# stalls renders — that is what a separate cpu-only worker service would fix.
QUEUES = [cpu_queue, io_queue]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Starting %s on queues: %s", WorkerClass.__name__, ", ".join(q.name for q in QUEUES))
    WorkerClass(QUEUES, connection=redis_conn).work()


if __name__ == "__main__":
    main()