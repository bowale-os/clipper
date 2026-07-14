from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
import logging

from app.db.models import User
from app.dependencies.user import get_current_user_record

logger = logging.getLogger(__name__)


class ClipRequest(BaseModel):
    video_id: str
    start_sec: float
    end_sec: float


c_router = APIRouter()


@c_router.post("/create")
def create_clip(
    request: ClipRequest,
    user: User = Depends(get_current_user_record),
):
    # TODO(v2): create a Clip row and enqueue an RQ render job (ARCHITECTURE §8.5)
    raise HTTPException(
        status_code=501,
        detail="Clip rendering is being migrated to the new pipeline and is temporarily unavailable",
    )
