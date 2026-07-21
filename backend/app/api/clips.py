from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel
import logging
import uuid

from sqlalchemy import select

from sqlalchemy.orm import Session

from app.db.models import User, VideoStatus, Moment, Video, Clip
from app.dependencies.user import get_current_user_record
from app.dependencies.rate_limit import rate_limit
from app.api.common import get_owned_video
from app.db.session import get_db
from app.tasks.render import FORMATS, DEFAULT_FORMAT
from app.workers.queues import JOB_RETRY, cpu_queue
from app.services.r2_client import generate_download_url

logger = logging.getLogger(__name__)



class ClipRequest(BaseModel):
    video_id: uuid.UUID
    start_sec: float
    end_sec: float
    captions: bool = False
    format: str = DEFAULT_FORMAT
    moment_id: uuid.UUID | None = None



c_router = APIRouter()


@c_router.post("/create", status_code=status.HTTP_202_ACCEPTED)
def create_clip(
    request: ClipRequest,
    user: User = Depends(get_current_user_record),
    db: Session = Depends(get_db),
    _rl: None = Depends(rate_limit("clip_create", limit=10, window_seconds=60)),
):
    video = get_owned_video(db, request.video_id, user)
    if video.status != VideoStatus.ready:
        raise HTTPException(
            status_code=409,
            detail="Video is not ready for rendering"
        )
    
    if (request.end_sec <= request.start_sec) or (request.end_sec > video.duration_sec):
        raise HTTPException(
            status_code=400,
            detail="Video bounds are not appropriate"
        )
    
    if request.format not in FORMATS: 
        raise HTTPException(
            status_code=400,
            detail="invalid video format received from request"
        )

    
    if request.moment_id:
        stmt = select(Moment).where(Moment.id == request.moment_id, Moment.video_id == video.id)
        moment = db.execute(stmt).scalar_one_or_none()

        if not moment:
            raise HTTPException(
                status_code=400,
                detail="Moment is not tied to any video"
            )
        
    clip = Clip(
        moment_id= request.moment_id if request.moment_id else None,
        video_id=video.id,
        user_id=user.id,
        status="queued",
        params={
            "start": request.start_sec,
            "end": request.end_sec,
            "format": request.format,
            "captions": request.captions,
        },
    )

    db.add(clip)
    db.commit()
    cpu_queue.enqueue(
        "app.tasks.render.render", str(video.id), {"clip_id": str(clip.id)}, retry=JOB_RETRY
    )

    return {
        "clip_id": str(clip.id),
        "status": "queued"
    }


@c_router.get("", status_code=status.HTTP_200_OK)
def list_clips(
    video_id: uuid.UUID,
    user: User = Depends(get_current_user_record),
    db: Session = Depends(get_db),
):
    """Every clip for a video, in rank order, whatever state it is in.

    This is what the grid polls while a video finishes. Clips that detect queued but no
    worker has finished come back with status "queued" or "rendering" and a null url, so
    the UI can hold a placeholder in the right slot instead of having the card pop in
    late. Ordering is by created_at, which detect writes in descending score order.
    """
    video = get_owned_video(db, video_id, user)

    rows = db.execute(
        select(Clip, Moment)
        .outerjoin(Moment, Clip.moment_id == Moment.id)   # outer: manual clips have no moment
        .where(Clip.video_id == video.id, Clip.user_id == user.id)
        .order_by(Clip.created_at)
    ).all()

    return {
        "video_id": str(video.id),
        "video_status": video.status.value,
        "clips": [
            {
                "clip_id": str(clip.id),
                # The grid keys its tiles on the moment, so without this it cannot tell
                # which tile an already-rendered clip belongs to.
                "moment_id": str(clip.moment_id) if clip.moment_id else None,
                "status": clip.status,
                "url": generate_download_url(clip.r2_key) if clip.status == "ready" else None,
                "start": clip.params.get("start"),
                "end": clip.params.get("end"),
                "format": clip.params.get("format"),
                "captions": clip.params.get("captions"),
                "title": moment.title if moment else None,
                "score": moment.scores.get("final") if moment else None,
            }
            for clip, moment in rows
        ],
    }


@c_router.get("/{clip_id}", status_code=status.HTTP_200_OK)
def get_clip(
    clip_id: uuid.UUID,
    user: User = Depends(get_current_user_record),
    db: Session = Depends(get_db),
):  
    
    stmt = select(Clip).where(Clip.user_id == user.id, Clip.id == clip_id)
    clip = db.execute(stmt).scalar_one_or_none()

    if not clip:
        raise HTTPException(
                status_code=400,
                detail="clip_id doesnt reference any clip (it is invalid)"
            )


    return {
        "clip_id": clip_id,
        "url": generate_download_url(clip.r2_key) if clip.status == "ready" else None,
        "status": clip.status
    }

    

