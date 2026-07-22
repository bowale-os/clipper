"""One-off: render the moments that predate auto-rendering everything.

detect used to only render the top 3 moments of a video, and it will not run again on a
video it has already finished — _detect_done skips any video with a completed RankingRun.
So videos processed before that change keep 3 clips and a dozen moments with nothing
behind them, and the grid tells the owner "3 of 15 ready. The rest are on the way." when
in fact nothing is coming.

This finds those moments and queues them, so old videos end up looking like new ones.

Run it from the backend service, where REDIS_URL points at the internal Redis address:

    python backfill_clips.py                # show what it would do, change nothing
    python backfill_clips.py --apply        # do it
    python backfill_clips.py --apply --limit 50

Safe to run twice: a moment with any clip row is skipped, so a second pass finds nothing.
Delete this file once it has done its job.
"""

import argparse
import logging
import sys

from sqlalchemy import select

from app.db.models import Clip, Moment, Video, VideoStatus
from app.db.session import session_scope
from app.tasks.detect import AUTO_RENDER_CAPTIONS
from app.tasks.render import DEFAULT_FORMAT
from app.workers.queues import JOB_RETRY, cpu_queue

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("backfill")


def find_orphan_moments(db, limit=None):
    """Moments on a ready video that no clip points at, best score first.

    A moment with a clip in ANY state is left alone — queued and rendering ones are
    already on their way, and a moment whose clip errored would only fail again, four
    attempts at a time, for whatever reason it failed the first time. Those are worth
    looking at by hand rather than re-queueing in bulk.
    """
    stmt = (
        select(Moment, Video)
        .join(Video, Moment.video_id == Video.id)
        .outerjoin(Clip, Clip.moment_id == Moment.id)
        .where(Video.status == VideoStatus.ready, Clip.id.is_(None))
        .order_by(Video.created_at.desc(), Moment.start_sec)
    )
    if limit:
        stmt = stmt.limit(limit)
    return db.execute(stmt).all()


def check_redis() -> None:
    """Fail before writing anything if the queue is unreachable.

    Redis.from_url only parses the URL — nothing connects until the first enqueue. Without
    this the script would commit every clip row and then die queueing the first job,
    leaving clips stuck on "queued" with no work behind them. Re-running would not repair
    them either: they have clip rows now, so the orphan query skips them, and someone
    would have to go delete them by hand.

    The usual cause is running this outside Railway, where REDIS_URL is the internal
    address and does not resolve.
    """
    cpu_queue.connection.ping()


def backfill(apply: bool, limit) -> int:
    """Create the missing clips and queue their renders. Returns how many."""
    # Written and committed before anything is enqueued, for the same reason
    # TaskContext.enqueue_next defers: a worker can pick a job up the instant it lands,
    # and render would not find a clip row that is still sitting in this transaction.
    clip_ids = []

    with session_scope() as db:
        rows = find_orphan_moments(db, limit)

        if not rows:
            logger.info("Nothing to backfill. Every moment on a ready video has a clip.")
            return 0

        by_video = {}
        for moment, video in rows:
            by_video.setdefault(video.id, []).append(moment)

        logger.info(
            "%d moments with no clip, across %d videos.", len(rows), len(by_video)
        )
        for video_id, moments in by_video.items():
            logger.info("  %s: %d moments", video_id, len(moments))

        if not apply:
            logger.info("\nDry run. Re-run with --apply to queue these.")
            return 0

        check_redis()

        for moment, video in rows:
            moment.status = "kept"
            clip = Clip(
                moment_id=moment.id,
                video_id=video.id,
                user_id=video.user_id,
                status="queued",
                params={
                    # float() because these columns are Numeric and come back as Decimal,
                    # which json cannot serialise into the job params.
                    "start": float(moment.start_sec),
                    "end": float(moment.end_sec),
                    "format": DEFAULT_FORMAT,
                    "captions": AUTO_RENDER_CAPTIONS,
                },
            )
            db.add(clip)
            db.flush()
            clip_ids.append((str(video.id), str(clip.id)))

    for video_id, clip_id in clip_ids:
        cpu_queue.enqueue(
            "app.tasks.render.render", video_id, {"clip_id": clip_id}, retry=JOB_RETRY
        )

    logger.info("Queued %d renders.", len(clip_ids))
    return len(clip_ids)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply", action="store_true", help="actually write and queue (default: dry run)"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="cap how many clips to queue, so one run cannot swamp the render queue",
    )
    args = parser.parse_args()

    backfill(apply=args.apply, limit=args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
