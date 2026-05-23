from fastapi import APIRouter

from .auth import a_router

main_router = APIRouter()

main_router.include_router(a_router, prefix="/auth")