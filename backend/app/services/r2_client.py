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
    """Generate presigned URL for uploading (PUT)"""
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


def generate_download_url(r2_key: str, expires_in: int = 3600) -> str:
    """Generate presigned URL for downloading (GET) - This is what you need in get_clip_from_r2"""
    r2 = get_r2_client()
    return r2.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": settings.R2_BUCKET_NAME,
            "Key": r2_key
        },
        ExpiresIn=expires_in
    )


def upload_file(local_file_path: str, r2_key: str):
    """Upload a file from disk to R2 (used after cutting the clip)"""
    r2 = get_r2_client()
    r2.upload_file(
        Filename=local_file_path,
        Bucket=settings.R2_BUCKET_NAME,
        Key=r2_key
    )


def delete_file(r2_key: str):
    """Optional: Delete a file from R2"""
    r2 = get_r2_client()
    r2.delete_object(
        Bucket=settings.R2_BUCKET_NAME,
        Key=r2_key
    )
