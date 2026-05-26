from fastapi import APIRouter

from .auth import a_router
from .video import v_router

main_router = APIRouter()

main_router.include_router(a_router, prefix="/auth")
main_router.include_router(v_router, prefix="/videos")
