import boto3
from botocore.config import Config

from app.config.secrets import settings

def get_r2_client():
    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=Config(signature_version="s3v4"),
        region_name="auto"
    )


def generate_upload_url(r2_key: str, content_type: str) -> str:
    r2 = get_r2_client()
    return r2.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": settings.R2_BUCKET_NAME,
            "Key": r2_key,
            "ContentType": content_type
        },
        ExpiresIn=3600
    )