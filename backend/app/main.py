from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import main_router
app = FastAPI(redirect_slashes=False)

# CORS Middleware - Put this RIGHT AFTER creating the app
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://clippper.fyi",
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