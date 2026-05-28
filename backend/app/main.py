import logging

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import main_router

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

app = FastAPI(redirect_slashes=True)

logger = logging.getLogger(__name__)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception occurred")
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "path": request.url.path,
            "method": request.method,
        },
    )

# CORS Middleware - Put this RIGHT AFTER creating the app
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://clippper.vercel.app",
        "https://clippper.fyi",
        "https://www.clippper.fyi",   # add www variant just in case
    ],
    allow_credentials=True,
    allow_methods=["*"],           # Use "*" for debugging
    allow_headers=["*"],           # Use "*" for debugging
    expose_headers=["*"],
)

app.include_router(main_router)

@app.get("/hit-it")
def home():
    return {"message from daniel": "you are home"}
