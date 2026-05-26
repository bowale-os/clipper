from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api import main_router

app = FastAPI(redirect_slashes=True)

app.include_router(main_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins = ["http://localhost:5173", 
                     "https://clippper.vercel.app",
                     "https://clippper.fyi"],

    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

@app.get("/hit-it")
def home():
    return {"message from daniel": "you are home"}

