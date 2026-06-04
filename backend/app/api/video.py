from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone
from pydantic import BaseModel
from enum import Enum
import uuid
import os
import modal
import logging

from app.services.mongo_client import database
from app.dependencies.auth import get_current_user
from app.services.r2_client import generate_upload_url, get_r2_client
from app.config.secrets import settings

logger = logging.getLogger(__name__)

class VideoStatus(str, Enum):
    uploading = "uploading"
    uploaded = "uploaded"
    processing = "processing"
    analyzed = "analyzed"
    error = "error"

class InitialVideoRequest(BaseModel):
    filename: str
    size: int

class CompleteVideoRequest(BaseModel):
    video_id: str
    auto_detect: bool = False
    content_type: str = "default"

v_router = APIRouter()

@v_router.post("/init")
async def video_metadata_storage(
    request: InitialVideoRequest,
    user_id: str = Depends(get_current_user)
):
    file_extension = os.path.splitext(request.filename)[1].lower()
    video_id = str(uuid.uuid4())
    r2_key = f"uploads/{video_id}{file_extension}"

    video_doc = {
        "_id": video_id,
        "user_id": user_id,
        "filename": request.filename,
        "size": request.size,
        "status": VideoStatus.uploading,
        "created_at": datetime.now(timezone.utc),
        "r2_key": r2_key
    }

    content_types = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska"
    }
    content_type = content_types.get(file_extension, "video/mp4")

    try:
        upload_url = generate_upload_url(r2_key, content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate upload URL: {str(e)}")

    try:
        await database.videos.insert_one(video_doc)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to store video metadata: {str(e)}")

    return {
        "video_id": video_id,
        "upload_url": upload_url
    }


@v_router.post('/complete')
async def complete_video_upload(
    request: CompleteVideoRequest,
    user_id: str = Depends(get_current_user)
):
    video_r2_key = None
    try:
        video = await database.videos.find_one({
            "_id": request.video_id,
            "user_id": user_id
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to find video: {str(e)}")

    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    video_r2_key = video.get("r2_key")

    try:
        await database.videos.update_one(
            {"_id": request.video_id, "user_id": user_id},
            {"$set": {"status": VideoStatus.uploaded}}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to mark video upload complete: {str(e)}")
    
    if request.auto_detect:
        try:
            get_moments = modal.Function.from_name("clip-maker", "detect_moments")
            await get_moments.spawn.aio(
                request.video_id, 
                video_r2_key,
                request.content_type
            )
            return {"message": "Upload complete, analyzing video", "video_id": request.video_id}

        except Exception as e:
           # video is uploaded successfully, detection just failed to start
            return {
                "message": "Upload complete but analysis failed to start",
                "video_id": request.video_id,
                "warning": str(e)
            }
    return {"message": "Upload complete", "video_id": request.video_id}
        

        




@v_router.get('/')
async def get_videos(
    user_id: str = Depends(get_current_user)
):
    try:
        all_videos = await database.videos.find({
            "user_id": user_id
        }).to_list()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve videos: {str(e)}")

    uploaded_videos = [v for v in all_videos if v.get("status") == VideoStatus.uploaded]
    uploading_videos = [v for v in all_videos if v.get("status") == VideoStatus.uploading]
    processing_videos = [v for v in all_videos if v.get("status") == VideoStatus.processing]
    analyzed_videos = [v for v in all_videos if v.get("status") == VideoStatus.analyzed]
    error_videos = [v for v in all_videos if v.get("status") == VideoStatus.error]


    return {
        "uploaded_videos": uploaded_videos,
        "uploading_videos": uploading_videos,
        "processing_videos": processing_videos,
        "analyzed_videos": analyzed_videos,
        "error_videos": error_videos
    }


@v_router.get('/{video_id}/metadata')
async def get_video_metadata(
    video_id: str,
    user_id: str = Depends(get_current_user)
):
    try:
        video = await database.videos.find_one({
            "_id": video_id,
            "user_id": user_id
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    r2_key = video.get("r2_key")
    if not r2_key:
        raise HTTPException(status_code=400, detail="Video has no r2_key")

    # return cached duration immediately
    if video.get("duration"):
        return {
            "duration": video["duration"],
            "filename": video["filename"]
        }

    # no cached duration — call Modal to probe it
    try:
        get_duration = modal.Function.from_name("clip-maker", "get_video_duration")
        result = await get_duration.remote.aio(r2_key)
        duration = result["duration"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get duration: {str(e)}")

    # cache in MongoDB
    try:
        await database.videos.update_one(
            {"_id": video_id},
            {"$set": {"duration": duration}}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to cache duration: {str(e)}")

    return {
        "duration": round(duration, 2),
        "filename": video["filename"]
    }


@v_router.get('/{video_id}/moments')
async def get_video_moments(
    video_id: str,
    user_id: str = Depends(get_current_user)
):
    try:
        video = await database.videos.find_one({
            "_id": video_id,
            "user_id": user_id
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    return {
        "status": video.get("status"),
        "moments": video.get("moments", []),
        "transcript": video.get("transcript", []),
        "duration": video.get("duration"),
        "filename": video.get("filename"),
    }


@v_router.delete('/{video_id}')
async def delete_video(
    video_id: str,
    user_id: str = Depends(get_current_user)
):
    logger.info("Delete video requested: video_id=%s user_id=%s", video_id, user_id)

    try:
        video = await database.videos.find_one({
            "_id": video_id,
            "user_id": user_id
        })
    except Exception as e:
        logger.exception("Delete video failed while finding video: video_id=%s user_id=%s", video_id, user_id)
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    if not video:
        logger.warning("Delete video requested for missing video: video_id=%s user_id=%s", video_id, user_id)
        raise HTTPException(status_code=404, detail="Video not found")

    video_r2_key = video.get("r2_key")
    logger.info(
        "Delete video found record: video_id=%s user_id=%s status=%s r2_key=%s",
        video_id,
        user_id,
        video.get("status"),
        video_r2_key,
    )

    # delete from R2
    if video_r2_key:
        try:
            logger.info("Deleting video object from R2: video_id=%s r2_key=%s", video_id, video_r2_key)
            r2 = get_r2_client()
            r2.delete_object(
                Bucket=settings.R2_BUCKET_NAME,
                Key=video_r2_key
            )
            logger.info("Deleted video object from R2: video_id=%s r2_key=%s", video_id, video_r2_key)
        except Exception as e:
            logger.exception("Delete video failed while deleting R2 video object: video_id=%s r2_key=%s", video_id, video_r2_key)
            raise HTTPException(status_code=500, detail=f"Failed to delete video from storage: {str(e)}")
    else:
        logger.warning("Video has no r2_key, skipping R2 delete: video_id=%s", video_id)
    
    # delete all clips belonging to this video from R2
    try:
        logger.info("Looking up clips to delete for video: video_id=%s user_id=%s", video_id, user_id)
        clips = await database.clips.find({
            "original_video_id": video_id,
            "user_id": user_id
        }).to_list()

        logger.info("Found %s clips to delete for video: video_id=%s", len(clips), video_id)
        r2 = get_r2_client()
        for clip in clips:
            if clip.get("clip_r2_key"):
                logger.info(
                    "Deleting clip object from R2: video_id=%s clip_id=%s clip_r2_key=%s",
                    video_id,
                    clip.get("_id"),
                    clip["clip_r2_key"],
                )
                r2.delete_object(
                    Bucket=settings.R2_BUCKET_NAME,
                    Key=clip["clip_r2_key"]
                )
            else:
                logger.warning(
                    "Skipping clip without clip_r2_key during video delete: video_id=%s clip_id=%s",
                    video_id,
                    clip.get("_id"),
                )
    except Exception as e:
        logger.exception("Delete video failed while deleting clip objects: video_id=%s", video_id)
        raise HTTPException(status_code=500, detail=f"Failed to delete clips from storage: {str(e)}")

    # delete clips from MongoDB
    try:
        clip_delete_result = await database.clips.delete_many({
            "original_video_id": video_id,
            "user_id": user_id
        })
        logger.info(
            "Deleted clip metadata records: video_id=%s deleted_count=%s",
            video_id,
            clip_delete_result.deleted_count,
        )
    except Exception as e:
        logger.exception("Delete video failed while deleting clip metadata: video_id=%s", video_id)
        raise HTTPException(status_code=500, detail=f"Failed to delete clips from database: {str(e)}")

    # delete video from MongoDB
    try:
        video_delete_result = await database.videos.delete_one({
            "_id": video_id,
            "user_id": user_id
        })
        logger.info(
            "Deleted video metadata record: video_id=%s deleted_count=%s",
            video_id,
            video_delete_result.deleted_count,
        )
    except Exception as e:
        logger.exception("Delete video failed while deleting video metadata: video_id=%s", video_id)
        raise HTTPException(status_code=500, detail=f"Failed to delete video from database: {str(e)}")

    logger.info("Delete video completed: video_id=%s user_id=%s", video_id, user_id)
    return {"message": "Video deleted successfully", "video_id": video_id}
