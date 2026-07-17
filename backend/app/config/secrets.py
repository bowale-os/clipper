from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",           # Put .env in backend/ root
        env_file_encoding="utf-8",
        extra="ignore",            # Ignore extra env vars
        case_sensitive=True        # Important!
    )

    SECRET_KEY: str
    CLERK_SECRET_KEY: str
    CLERK_WEBHOOK_SIGNING_SECRET: str
    CLERK_FRONTEND_API: str
    CLERK_DEV_FRONTEND_API: str
    R2_ENDPOINT_URL: str
    R2_SECRET_ACCESS_KEY: str
    R2_ACCESS_KEY: str
    R2_BUCKET_NAME: str
    ENV: str

    
    # "v1" (default, Mongo/Modal) | "v2" (Postgres/RQ)
    NEON_DB_CONNECT: str     # Neon Postgres connection string
    REDIS_URL: str            # Railway Redis plugin connection string
    GROQ_API_KEY: str
    GEMINI_API_KEY: str

settings = Settings()
