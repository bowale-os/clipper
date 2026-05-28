from fastapi import APIRouter, Request, HTTPException, status, Depends
from datetime import datetime, timezone
from pydantic import BaseModel
from enum import Enum
import json
import uuid
import os
import ffmpeg
import asyncio

from app.services.mongo_client import database
from app.dependencies.auth import get_current_user
from app.services.r2_client import generate_upload_url
from app.services.r2_client import generate_download_url

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
        "created_at" : datetime.now(timezone.utc),
        "r2_key": r2_key
    }


    # content type based on extension
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
            "user_id": user_id  # must be their video
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
        # get ALL uploaded videos for this user
        uploaded_videos = await database.videos.find({
            "user_id": user_id,
            "status": VideoStatus.uploaded
        }).to_list()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve uploaded videos: {str(e)}")

    try:
        uploading_videos =  await database.videos.find({
            "user_id": user_id,
            "status": VideoStatus.uploading
        }).to_list()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to retrieve uploading videos: {str(e)}")

    return {
        "uploaded_videos": uploaded_videos,
        "uploading_videos": uploading_videos
    }



@v_router.get('/{video_id}/metadata')
async def get_video_metadata(
    video_id, user_id: str = Depends(get_current_user)
    ):

    try:
        video = await database.videos.find_one({
            "_id": video_id, "user_id": user_id
        })
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to find video metadata: {str(e)}")

    if not video:
        raise HTTPException(404, "Video was not found")
    
    video_r2_key = video.get("r2_key")
    if not video_r2_key:
        file_extension = os.path.splitext(video.get("filename", ""))[1].lower()
        if not file_extension:
            raise HTTPException(status_code=400, detail="Video r2_key not found")
        video_r2_key = f"uploads/{video_id}{file_extension}"

    try:
        download_url = generate_download_url(video_r2_key, 300)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate video download URL: {str(e)}")

    try:
        # this should return immediately on second call
        if video.get("duration"):
            return {
                "duration": video["duration"],
                "filename": video["filename"]
            }
        probe = await asyncio.to_thread(ffmpeg.probe, download_url)
        duration = float(probe['format']['duration'])

        # save duration to MongoDB so next call is instant
        await database.videos.update_one(
            {"_id": video_id},
            {"$set": {"duration": duration}}
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to probe video metadata: {str(e)}")

    return {
        "duration": round(duration, 2),
        "filename": video["filename"]
    }

