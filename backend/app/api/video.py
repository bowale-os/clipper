import logging
import math
import os
import uuid

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Moment, User, Video, VideoStatus
from app.db.session import get_db
from app.dependencies.user import get_current_user_record
from app.services.r2_client import (
    abort_multipart_upload,
    complete_multipart_upload,
    create_multipart_upload,
    delete_file,
    generate_part_upload_urls,
    generate_upload_url,
    head_object_size,
    list_uploaded_parts,
)

logger = logging.getLogger(__name__)

MULTIPART_THRESHOLD = 100 * 1024 * 1024   # below this, a single presigned PUT is faster
PART_SIZE = 16 * 1024 * 1024              # R2: all parts except the last must be the same size
MAX_PARTS = 10_000                        # S3/R2 hard limit
MAX_SIZE = PART_SIZE * MAX_PARTS
MAX_PARTS_PER_SIGN_BATCH = 100

CONTENT_TYPES = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
}


class InitialVideoRequest(BaseModel):
    filename: str
    size: int = Field(gt=0)


class CompletePart(BaseModel):
    part_number: int = Field(ge=1)
    etag: str


class CompleteVideoRequest(BaseModel):
    video_id: uuid.UUID
    auto_detect: bool = False
    content_type: str = "default"
    parts: list[CompletePart] | None = None


class SignPartsRequest(BaseModel):
    part_numbers: list[int] = Field(min_length=1, max_length=MAX_PARTS_PER_SIGN_BATCH)


v_router = APIRouter()


def _get_owned_video(db: Session, video_id: uuid.UUID, user: User) -> Video:
    video = db.scalar(select(Video).where(Video.id == video_id, Video.user_id == user.id))
    if video is None:
        raise HTTPException(status_code=404, detail="Video not found")
    return video


def _video_to_dict(video: Video) -> dict:
    return {
        "video_id": str(video.id),
        "filename": video.filename,
        "size_bytes": video.size_bytes,
        "status": video.status.value,
        "duration_sec": float(video.duration_sec) if video.duration_sec is not None else None,
        "content_type": video.content_type,
        "created_at": video.created_at.isoformat(),
    }


def _upload_state(video: Video) -> dict:
    return video.pipeline.get("upload", {})


def _clear_upload_state(video: Video) -> None:
    # Reassign instead of mutating: in-place JSONB changes aren't tracked by SQLAlchemy.
    video.pipeline = {k: v for k, v in video.pipeline.items() if k != "upload"}


@v_router.post("/init")
def init_video_upload(
    request: InitialVideoRequest,
    user: User = Depends(get_current_user_record),
    db: Session = Depends(get_db),
):
    if request.size > MAX_SIZE:
        raise HTTPException(status_code=413, detail=f"File exceeds the {MAX_SIZE // 1024**3} GiB upload limit")

    video_id = uuid.uuid4()
    file_extension = os.path.splitext(request.filename)[1].lower()
    r2_key = f"sources/{video_id}/original{file_extension}"
    mime_type = CONTENT_TYPES.get(file_extension, "video/mp4")

    if request.size < MULTIPART_THRESHOLD:
        try:
            upload_url = generate_upload_url(r2_key, mime_type)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to generate upload URL: {str(e)}")

        upload_state = {"mode": "single"}
        response = {"mode": "single", "video_id": str(video_id), "upload_url": upload_url}
        upload_id = None
    else:
        try:
            upload_id = create_multipart_upload(r2_key, mime_type)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to start multipart upload: {str(e)}")

        part_count = math.ceil(request.size / PART_SIZE)
        upload_state = {
            "mode": "multipart",
            "upload_id": upload_id,
            "part_size": PART_SIZE,
            "part_count": part_count,
        }
        response = {
            "mode": "multipart",
            "video_id": str(video_id),
            "upload_id": upload_id,
            "part_size": PART_SIZE,
            "part_count": part_count,
        }

    video = Video(
        id=video_id,
        user_id=user.id,
        filename=request.filename,
        size_bytes=request.size,
        status=VideoStatus.uploading,
        r2_key=r2_key,
        pipeline={"upload": upload_state},
    )
    db.add(video)
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        if upload_id:
            try:
                abort_multipart_upload(r2_key, upload_id)
            except Exception:
                logger.exception("Failed to abort orphaned multipart upload: %s", upload_id)
        raise HTTPException(status_code=500, detail=f"Failed to store video metadata: {str(e)}")

    return response


@v_router.post("/{video_id}/parts")
def sign_upload_parts(
    video_id: uuid.UUID,
    request: SignPartsRequest,
    user: User = Depends(get_current_user_record),
    db: Session = Depends(get_db),
):
    video = _get_owned_video(db, video_id, user)
    upload = _upload_state(video)

    if video.status != VideoStatus.uploading or upload.get("mode") != "multipart":
        raise HTTPException(status_code=409, detail="Video is not in a multipart upload")

    part_count = upload["part_count"]
    invalid = [n for n in request.part_numbers if n < 1 or n > part_count]
    if invalid:
        raise HTTPException(status_code=400, detail=f"Part numbers out of range 1..{part_count}: {invalid}")

    try:
        urls = generate_part_upload_urls(video.r2_key, upload["upload_id"], request.part_numbers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sign part URLs: {str(e)}")

    return {"urls": {str(n): url for n, url in urls.items()}, "expires_in": 3600}


@v_router.get("/{video_id}/upload-status")
def get_upload_status(
    video_id: uuid.UUID,
    user: User = Depends(get_current_user_record),
    db: Session = Depends(get_db),
):
    video = _get_owned_video(db, video_id, user)

    if video.status != VideoStatus.uploading:
        return {"status": video.status.value, "resumable": False}

    upload = _upload_state(video)
    base = {
        "status": video.status.value,
        "mode": upload.get("mode"),
        "filename": video.filename,
        "size_bytes": video.size_bytes,
    }

    if upload.get("mode") != "multipart":
        # Single PUT has no server-side part state; the client restarts the PUT with a fresh URL.
        file_extension = os.path.splitext(video.filename)[1].lower()
        mime_type = CONTENT_TYPES.get(file_extension, "video/mp4")
        try:
            upload_url = generate_upload_url(video.r2_key, mime_type)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to generate upload URL: {str(e)}")
        return {**base, "resumable": True, "upload_url": upload_url}

    try:
        uploaded_parts = list_uploaded_parts(video.r2_key, upload["upload_id"])
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "NoSuchUpload":
            # R2's lifecycle rule aborted it; the upload can't be resumed.
            video.status = VideoStatus.error
            _clear_upload_state(video)
            db.commit()
            return {**base, "status": VideoStatus.error.value, "resumable": False, "reason": "upload_expired"}
        raise HTTPException(status_code=500, detail=f"Failed to list uploaded parts: {str(e)}")

    return {
        **base,
        "resumable": True,
        "upload_id": upload["upload_id"],
        "part_size": upload["part_size"],
        "part_count": upload["part_count"],
        "uploaded_parts": uploaded_parts,
    }


@v_router.post("/complete")
def complete_video_upload(
    request: CompleteVideoRequest,
    user: User = Depends(get_current_user_record),
    db: Session = Depends(get_db),
):
    video = _get_owned_video(db, request.video_id, user)

    if video.status != VideoStatus.uploading:
        # Retried/duplicated complete calls are fine.
        return {"message": "Upload complete", "video_id": str(video.id)}

    upload = _upload_state(video)

    if upload.get("mode") == "multipart":
        part_count = upload["part_count"]
        if not request.parts:
            raise HTTPException(status_code=400, detail="Multipart upload requires the parts list")
        part_numbers = {p.part_number for p in request.parts}
        if len(request.parts) != part_count or part_numbers != set(range(1, part_count + 1)):
            raise HTTPException(status_code=400, detail=f"Expected exactly parts 1..{part_count}")

        try:
            complete_multipart_upload(
                video.r2_key,
                upload["upload_id"],
                [{"part_number": p.part_number, "etag": p.etag} for p in request.parts],
            )
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "UploadError")
            raise HTTPException(status_code=400, detail=f"Failed to finalize upload ({code}); please restart the upload")
    else:
        object_size = head_object_size(video.r2_key)
        if object_size is None or object_size != video.size_bytes:
            raise HTTPException(status_code=400, detail="Uploaded object is missing or its size doesn't match")

    video.status = VideoStatus.uploaded
    if request.content_type:
        video.content_type = request.content_type
    _clear_upload_state(video)
    db.commit()

    # TODO(v2): enqueue ingest -> transcribe -> detect pipeline (RQ workers, ARCHITECTURE §7)
    if request.auto_detect:
        logger.info("auto_detect requested for video %s; pipeline enqueue not implemented yet", video.id)

    return {"message": "Upload complete", "video_id": str(video.id)}


@v_router.post("/{video_id}/abort")
def abort_video_upload(
    video_id: uuid.UUID,
    user: User = Depends(get_current_user_record),
    db: Session = Depends(get_db),
):
    video = _get_owned_video(db, video_id, user)

    if video.status != VideoStatus.uploading:
        raise HTTPException(status_code=409, detail="Video is not uploading")

    upload = _upload_state(video)
    if upload.get("mode") == "multipart":
        try:
            abort_multipart_upload(video.r2_key, upload["upload_id"])
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "NoSuchUpload":
                raise HTTPException(status_code=500, detail=f"Failed to abort upload: {str(e)}")

    db.delete(video)
    db.commit()
    return {"message": "Upload aborted", "video_id": str(video_id)}


@v_router.get("/")
def get_videos(
    user: User = Depends(get_current_user_record),
    db: Session = Depends(get_db),
):
    videos = db.scalars(
        select(Video).where(Video.user_id == user.id).order_by(Video.created_at.desc())
    ).all()

    grouped = {status: [] for status in VideoStatus}
    for video in videos:
        grouped[video.status].append(_video_to_dict(video))

    return {
        "uploaded_videos": grouped[VideoStatus.uploaded],
        "uploading_videos": grouped[VideoStatus.uploading],
        "processing_videos": grouped[VideoStatus.processing],
        "ready_videos": grouped[VideoStatus.ready],
        "error_videos": grouped[VideoStatus.error],
    }


@v_router.get("/{video_id}/metadata")
def get_video_metadata(
    video_id: uuid.UUID,
    user: User = Depends(get_current_user_record),
    db: Session = Depends(get_db),
):
    video = _get_owned_video(db, video_id, user)
    # TODO(v2): the ingest worker fills duration_sec after upload; until then it may be null.
    return {
        "duration": float(video.duration_sec) if video.duration_sec is not None else None,
        "filename": video.filename,
    }


@v_router.get("/{video_id}/moments")
def get_video_moments(
    video_id: uuid.UUID,
    user: User = Depends(get_current_user_record),
    db: Session = Depends(get_db),
):
    video = _get_owned_video(db, video_id, user)

    moments = db.scalars(
        select(Moment).where(Moment.video_id == video.id).order_by(Moment.created_at)
    ).all()

    return {
        "status": video.status.value,
        "moments": [
            {
                "id": str(m.id),
                "start_sec": float(m.start_sec),
                "end_sec": float(m.end_sec),
                "type": m.type,
                "title": m.title,
                "reason": m.reason,
                "scores": m.scores,
                "status": m.status,
            }
            for m in moments
        ],
        "duration": float(video.duration_sec) if video.duration_sec is not None else None,
        "filename": video.filename,
    }


@v_router.delete("/{video_id}")
def delete_video(
    video_id: uuid.UUID,
    user: User = Depends(get_current_user_record),
    db: Session = Depends(get_db),
):
    logger.info("Delete video requested: video_id=%s user_id=%s", video_id, user.id)
    video = _get_owned_video(db, video_id, user)

    upload = _upload_state(video)
    if video.status == VideoStatus.uploading and upload.get("mode") == "multipart":
        try:
            abort_multipart_upload(video.r2_key, upload["upload_id"])
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "NoSuchUpload":
                logger.exception("Failed to abort multipart upload during delete: video_id=%s", video_id)

    try:
        delete_file(video.r2_key)
    except Exception:
        logger.exception("Failed to delete R2 object: video_id=%s r2_key=%s", video_id, video.r2_key)
        raise HTTPException(status_code=500, detail="Failed to delete video from storage")

    # FK cascades cover transcripts, moments, clips, and jobs rows.
    db.delete(video)
    db.commit()

    logger.info("Delete video completed: video_id=%s user_id=%s", video_id, user.id)
    return {"message": "Video deleted successfully", "video_id": str(video_id)}
