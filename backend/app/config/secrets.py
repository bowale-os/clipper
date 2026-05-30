from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):

    model_config = SettingsConfigDict(
        env_file=".env",           # Put .env in backend/ root
        env_file_encoding="utf-8",
        extra="ignore",            # Ignore extra env vars
        case_sensitive=True        # Important!
    )

    MONGO_CONNECT: str
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
settings = Settings()