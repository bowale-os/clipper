from fastapi import APIRouter, Request, HTTPException, status, Depends
from datetime import datetime, timezone
from pydantic import BaseModel
from enum import Enum
import json
import uuid
import os


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
    request:InitialVideoRequest, 
    user_id: str = Depends(get_current_user)):

    file_extension = os.path.splitext(request.filename)[1].lower()

    video_id = str(uuid.uuid4())
    r2_key = f"uploads/{video_id}{file_extension}"

    video_doc = {
        "_id" : video_id,
        "user_id" : user_id,
        "filename": request.filename,
        "size" : request.size,
        "status" : VideoStatus.uploading,
        "created_at" : datetime.now(timezone.utc)
    }

    await database.videos.insert_one(video_doc)

    # content type based on extension
    content_types = {
        ".mp4": "video/mp4",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
        ".mkv": "video/x-matroska"
    }
    content_type = content_types.get(file_extension, "video/mp4")

    upload_url = generate_upload_url(r2_key, content_type)

    return {
        "video_id": video_id,
        "upload_url": upload_url
    }

    

@v_router.post('/complete')
async def complete_video_upload(
    request: CompleteVideoRequest,
    user_id: str = Depends(get_current_user)
):
    video = await database.videos.find_one({
        "_id": request.video_id,
        "user_id": user_id  # must be their video
    })

    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    await database.videos.update_one(
        {"_id": request.video_id},
        {"$set": {"status": VideoStatus.uploaded}}
    )

    return {"message": "Upload complete", "video_id": request.video_id}


@v_router.get('/')
async def get_videos(
    user_id: str = Depends(get_current_user)
):
    
    try: 
        # get ALL uploaded videos for this user
        uploaded_videos = await database.videos.find({
            "user_id": user_id,
            "status": VideoStatus.uploaded
        }).to_list()

        uploading_videos =  await database.videos.find({
            "user_id": user_id,
            "status": VideoStatus.uploading
        }).to_list()

        return {
            "uploaded_videos": uploaded_videos,
            "uploading_videos": uploading_videos
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail="Videos not retrieved successfully")
