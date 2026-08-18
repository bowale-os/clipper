import logging
import math
import os
import uuid

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.api.common import get_owned_video
from app.db.models import Moment, User, Video, VideoStatus, Clip
from app.db.session import get_db
from app.dependencies.user import get_current_user_record
from app.dependencies.rate_limit import rate_limit
from app.services.r2_client import (
    abort_multipart_upload,
    complete_multipart_upload,
    create_multipart_upload,
    delete_file,
    delete_prefix,
    generate_part_upload_urls,
    generate_upload_url,
    head_object_size,
    list_uploaded_parts,
)
from app.workers.queues import JOB_RETRY, io_queue
from app.services.embeddings import embed_text

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
    content_type: str = "default"
    parts: list[CompletePart] | None = None


class SignPartsRequest(BaseModel):
    part_numbers: list[int] = Field(min_length=1, max_length=MAX_PARTS_PER_SIGN_BATCH)


v_router = APIRouter()

def _aspect_ratio(width, height) -> str | None:
    if not width or not height:
        return None
    divisor = math.gcd(width, height)
    return f"{width // divisor}:{height //divisor}"

def _video_to_dict(video: Video, clip_count: int = 0) -> dict:
    # video.pipeline also carries upload state (upload_id, part offsets), which is
    # internal, so the stage fields are picked out by name rather than passed through.
    pipeline = video.pipeline or {}
    return {
        "video_id": str(video.id),
        "filename": video.filename,
        "size_bytes": video.size_bytes,
        "status": video.status.value,
        "duration_sec": float(video.duration_sec) if video.duration_sec is not None else None,
        "content_type": video.content_type,
        "created_at": video.created_at.isoformat(),
        "stage": pipeline.get("stage"),
        "stage_pct": pipeline.get("progress_pct"),
        "error": pipeline.get("error"),
        # True while a stage is waiting out its backoff after a transient upstream
        # failure. The video has not failed; it just will not move for a few minutes.
        "retrying": bool(pipeline.get("retrying")),
        "clip_count": clip_count,
        "width": video.artifacts.get("width"),
        "height": video.artifacts.get("height"),
        "aspect_ratio": _aspect_ratio(video.artifacts.get("width"), video.artifacts.get("height"))
    }


def _ready_clip_counts(db: Session, user: User, video_ids=None) -> dict:
    """{video_id: number of ready clips}, one query regardless of how many videos.

    video_ids, if given, narrows the count to just those videos (search scopes it to
    the matched set); omitted, it covers every video the user owns (the full list).
    """
    stmt = select(Clip.video_id, func.count(Clip.id)).where(
        Clip.user_id == user.id, Clip.status == "ready"
    )
    if video_ids is not None:
        stmt = stmt.where(Clip.video_id.in_(video_ids))
    stmt = stmt.group_by(Clip.video_id)
    return dict(db.execute(stmt).all())


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
    _rl: None = Depends(rate_limit("video_init", limit=5, window_seconds=3600)),
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

    try:
        title_embed = embed_text(request.filename)
    except Exception as e:
        logger.exception("Filename was not embedded for video %s. Error is %s", video_id, e)
        title_embed = None

    video = Video(
        id=video_id,
        user_id=user.id,
        filename=request.filename,
        size_bytes=request.size,
        status=VideoStatus.uploading,
        r2_key=r2_key,
        pipeline={"upload": upload_state},
        title_embedding=title_embed
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
    video = get_owned_video(db, video_id, user)
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
    video = get_owned_video(db, video_id, user)

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
    _rl: None = Depends(rate_limit("video_complete", limit=5, window_seconds=3600)),
):
    video = get_owned_video(db, request.video_id, user)

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

    logger.info("Enqueuing ingest job for video %s on queue %s", video.id, io_queue.name)
    job = io_queue.enqueue("app.tasks.ingest.ingest", str(video.id), retry=JOB_RETRY)
    logger.info("Enqueued ingest job id=%s for video %s", job.id, video.id)

    # Every video runs the full ingest -> transcribe -> detect chain; each stage enqueues
    # the next. Clients read the moments back from GET /videos/{id}/moments once ready.

    return {"message": "Upload complete", "video_id": str(video.id)}


@v_router.post("/{video_id}/abort")
def abort_video_upload(
    video_id: uuid.UUID,
    user: User = Depends(get_current_user_record),
    db: Session = Depends(get_db),
):
    video = get_owned_video(db, video_id, user)

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

    counts = _ready_clip_counts(db, user)

    grouped = {status: [] for status in VideoStatus}
    for video in videos:
        grouped[video.status].append(_video_to_dict(video, counts.get(video.id, 0)))

    return {
        "uploaded_videos": grouped[VideoStatus.uploaded],
        "uploading_videos": grouped[VideoStatus.uploading],
        "processing_videos": grouped[VideoStatus.processing],
        "ready_videos": grouped[VideoStatus.ready],
        "error_videos": grouped[VideoStatus.error],
    }


# Cosine distance cutoff for the semantic branch: below this, a title embedding counts
# as a real match rather than just "closest of what's there." Loose until real query
# traffic shows where the useful cutoff is.
SEARCH_DISTANCE_CUTOFF = 0.5
SEARCH_LIMIT = 40


@v_router.get("/search")
def search_videos(
    q: str,
    user: User = Depends(get_current_user_record),
    db: Session = Depends(get_db),
    _rl: None = Depends(rate_limit("video_search", limit=30, window_seconds=60)),
):
    q = q.strip()
    if not q:
        return {"videos": []}

    try:
        query_vec = embed_text(q)
    except Exception:
        logger.exception("Failed to embed search query for user %s", user.id)
        query_vec = None

    # Scoping by user_id first (videos_user_idx) keeps this an exact scan over one
    # user's own rows rather than a filtered approximate-nearest-neighbor search over
    # the whole table, which is both cheap at this scale and avoids the HNSW index
    # returning irrelevant videos when the true match isn't among its top candidates.
    matched: dict[uuid.UUID, Video] = {}

    if query_vec is not None:
        semantic_hits = db.scalars(
            select(Video)
            .where(
                Video.user_id == user.id,
                Video.title_embedding.isnot(None),
                Video.title_embedding.cosine_distance(query_vec) < SEARCH_DISTANCE_CUTOFF,
            )
            .order_by(Video.title_embedding.cosine_distance(query_vec))
            .limit(SEARCH_LIMIT)
        ).all()
        for video in semantic_hits:
            matched[video.id] = video

    lexical_hits = db.scalars(
        select(Video).where(Video.user_id == user.id, Video.filename.ilike(f"%{q}%"))
    ).all()
    for video in lexical_hits:
        matched.setdefault(video.id, video)

    if not matched:
        return {"videos": []}

    counts = _ready_clip_counts(db, user, matched.keys())

    return {"videos": [_video_to_dict(v, counts.get(v.id, 0)) for v in matched.values()]}


@v_router.get("/{video_id}/metadata")
def get_video_metadata(
    video_id: uuid.UUID,
    user: User = Depends(get_current_user_record),
    db: Session = Depends(get_db),
):
    video = get_owned_video(db, video_id, user)
    height = video.artifacts.get("height")
    width = video.artifacts.get("width")
    # TODO(v2): the ingest worker fills duration_sec after upload; until then it may be null.
    return {
        "duration": float(video.duration_sec) if video.duration_sec is not None else None,
        "filename": video.filename,
        "width": width,
        "height": height,
        "aspect_ratio": _aspect_ratio(width=width, height=height)
    }


@v_router.get("/{video_id}/moments")
def get_video_moments(
    video_id: uuid.UUID,
    user: User = Depends(get_current_user_record),
    db: Session = Depends(get_db),
):
    video = get_owned_video(db, video_id, user)

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
    video = get_owned_video(db, video_id, user)

    upload = _upload_state(video)
    if video.status == VideoStatus.uploading and upload.get("mode") == "multipart":
        try:
            abort_multipart_upload(video.r2_key, upload["upload_id"])
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "NoSuchUpload":
                logger.exception("Failed to abort multipart upload during delete: video_id=%s", video_id)

    clip_r2_keys = [
        c.r2_key
        for c in db.scalars(select(Clip).where(Clip.video_id == video.id)).all()
        if c.r2_key
    ]

    try:
        delete_file(video.r2_key)
        delete_prefix(f"artifacts/{video_id}")
        for clip_key in clip_r2_keys:
            delete_file(clip_key)
    except Exception:
        logger.exception("Failed to delete R2 objects during video delete: video_id=%s", video_id)
        raise HTTPException(status_code=500, detail="Failed to delete video from storage")

    # FK cascades cover transcripts, moments, clips, and jobs rows (DB rows only — their R2 objects were deleted above).
    db.delete(video)
    db.commit()

    logger.info("Delete video completed: video_id=%s user_id=%s", video_id, user.id)
    return {"message": "Video deleted successfully", "video_id": str(video_id)}
