from fastapi import APIRouter

from .auth import a_router
from .video import v_router
from .clips import c_router

main_router = APIRouter()

main_router.include_router(a_router, prefix="/auth")
main_router.include_router(v_router, prefix="/videos")
main_router.include_router(c_router, prefix="/clips")

