from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User, Video


def get_owned_video(db: Session, video_id, user: User) -> Video:
    """Load a video, scoped to its owner.

    Scoping the lookup by user_id rather than checking ownership afterwards means an
    id belonging to someone else is indistinguishable from one that doesn't exist.
    """
    video = db.scalar(select(Video).where(Video.id == video_id, Video.user_id == user.id))
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return video
