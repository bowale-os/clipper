from fastapi import APIRouter, Request, HTTPException, status, Depends
from pydantic import BaseModel
from datetime import datetime, timezone
from enum import Enum
import uuid
import modal


from app.services.mongo_client import database
from app.dependencies.auth import get_current_user
from app.services.modal_client import get_clip_from_r2
from app.services.r2_client import generate_download_url

class VideoStatus(str, Enum):
    uploading = "uploading"
    uploaded = "uploaded"
    processing = "processing"
    analyzed = "analyzed"
    error = "error"

class ClipRequest(BaseModel):
    video_id: str
    start_sec: float
    end_sec: float


c_router = APIRouter()

@c_router.post("/create")
async def video_metadata_storage(
    request:ClipRequest, 
    user_id: str = Depends(get_current_user)):

    try:
        video = await database.videos.find_one({"_id": request.video_id})
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to find video: {str(e)}")

    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    video_r2_key = video.get("r2_key")
    if not video_r2_key:
        raise HTTPException(status_code=400, detail="Video r2_key not found")

    clip_id = str(uuid.uuid4())

    try:
        get_clip = modal.Function.from_name("clip-maker", "get_clip_from_r2")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load Modal clip function: {str(e)}")

    try:
        modal_response = await get_clip.remote.aio(
            video_r2_key,
            clip_id,
            request.start_sec,
            request.end_sec,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create clip with Modal: {str(e)}")

    print(f"Modal response: {modal_response}")  # add this

    
    if modal_response.get("error"):
        raise HTTPException(status_code=500, detail=modal_response["error"])


    clip_r2_key = modal_response.get("clip_r2_key")

    # Save clip info to MongoDB
    clip_doc = {
        "_id": clip_id,
        "user_id": user_id,
        "original_video_id": request.video_id,
        "clip_r2_key": clip_r2_key,
        "start_sec": float(request.start_sec),
        "end_sec": float(request.end_sec),
        "created_at": datetime.now(timezone.utc),
        "status": "ready"
    }

    try:
        await database.clips.insert_one(clip_doc)   # ← Save it!
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to store clip metadata: {str(e)}")

    try:
        download_url = generate_download_url(clip_r2_key, expires_in=86400)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate clip download URL: {str(e)}")

    return {
        "success": True,
        "clip_id": clip_id,
        "clip_r2_key": clip_r2_key,
        "url": download_url,              
        "message": "Clip created successfully"
    }
