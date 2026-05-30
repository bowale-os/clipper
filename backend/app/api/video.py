from fastapi import APIRouter, HTTPException, Depends
from datetime import datetime, timezone
from pydantic import BaseModel
from enum import Enum
import uuid
import os
import modal

from app.services.mongo_client import database
from app.dependencies.auth import get_current_user
from app.services.r2_client import generate_upload_url

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
    try:
        video = await database.videos.find_one({
            "_id": request.video_id,
            "user_id": user_id
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to find video: {str(e)}")

    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    try:
        await database.videos.update_one(
            {"_id": request.video_id, "user_id": user_id},
            {"$set": {"status": VideoStatus.uploaded}}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to mark video upload complete: {str(e)}")

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

    return {
        "uploaded_videos": uploaded_videos,
        "uploading_videos": uploading_videos,
        "processing_videos": processing_videos,
        "analyzed_videos": analyzed_videos
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