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

def download_file(r2_key: str, local_path: str) -> None:
    r2 = get_r2_client()
    r2.download_file(
        Bucket=settings.R2_BUCKET_NAME,
        Key=r2_key,
        Filename=local_path)


def delete_file(r2_key: str):
    """Optional: Delete a file from R2"""
    r2 = get_r2_client()
    r2.delete_object(
        Bucket=settings.R2_BUCKET_NAME,
        Key=r2_key
    )

def upload_bytes(data: bytes, r2_key: str, content_type: str) -> None:
    r2 = get_r2_client()
    r2.put_object(
        Bucket=settings.R2_BUCKET_NAME,
        Key=r2_key,
        Body=data,
        ContentType=content_type,
    )

def download_bytes(r2_key: str) -> bytes:
    """Read a whole object into memory — for small JSON artifacts (words, features)."""
    r2 = get_r2_client()
    resp = r2.get_object(Bucket=settings.R2_BUCKET_NAME, Key=r2_key)
    return resp["Body"].read()

def delete_prefix(prefix: str) -> int:
    r2 = get_r2_client()

    paginator = r2.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=settings.R2_BUCKET_NAME, Prefix=prefix)

    deleted_count = 0
    for page in pages:
        if "Contents" not in page:
            continue  # No files found for this page

        # Prepare delete request (max 1000 keys per request)
        objects_to_delete = [{"Key": obj["Key"]} for obj in page["Contents"]]
        r2.delete_objects(
            Bucket=settings.R2_BUCKET_NAME,
            Delete={"Objects": objects_to_delete}
        )
        deleted_count += len(objects_to_delete)

    return deleted_count


# --- Multipart upload (large files) ---

PART_URL_EXPIRES = 3600  # frontend re-signs on 403, so 1h is plenty


def create_multipart_upload(r2_key: str, content_type: str) -> str:
    """Start a multipart upload, returns the R2 UploadId."""
    r2 = get_r2_client()
    resp = r2.create_multipart_upload(
        Bucket=settings.R2_BUCKET_NAME,
        Key=r2_key,
        ContentType=content_type
    )
    return resp["UploadId"]


def generate_part_upload_urls(r2_key: str, upload_id: str, part_numbers: list[int]) -> dict[int, str]:
    """Presigned PUT URL per part number (signing is local, no network calls)."""
    r2 = get_r2_client()
    return {
        n: r2.generate_presigned_url(
            "upload_part",
            Params={
                "Bucket": settings.R2_BUCKET_NAME,
                "Key": r2_key,
                "UploadId": upload_id,
                "PartNumber": n
            },
            ExpiresIn=PART_URL_EXPIRES
        )
        for n in part_numbers
    }


def list_uploaded_parts(r2_key: str, upload_id: str) -> list[dict]:
    """All parts uploaded so far -> [{part_number, etag, size}]. Raises NoSuchUpload if expired/aborted."""
    r2 = get_r2_client()
    parts = []
    marker = 0
    while True:
        resp = r2.list_parts(
            Bucket=settings.R2_BUCKET_NAME,
            Key=r2_key,
            UploadId=upload_id,
            PartNumberMarker=marker,
            MaxParts=1000
        )
        parts += [
            {"part_number": p["PartNumber"], "etag": p["ETag"], "size": p["Size"]}
            for p in resp.get("Parts", [])
        ]
        if not resp.get("IsTruncated"):
            return parts
        marker = resp["NextPartNumberMarker"]


def complete_multipart_upload(r2_key: str, upload_id: str, parts: list[dict]) -> None:
    """parts: [{part_number, etag}] in any order. ETags must be passed exactly as R2 returned them (quotes included)."""
    r2 = get_r2_client()
    r2.complete_multipart_upload(
        Bucket=settings.R2_BUCKET_NAME,
        Key=r2_key,
        UploadId=upload_id,
        MultipartUpload={
            "Parts": [
                {"PartNumber": p["part_number"], "ETag": p["etag"]}
                for p in sorted(parts, key=lambda p: p["part_number"])
            ]
        }
    )


def abort_multipart_upload(r2_key: str, upload_id: str) -> None:
    r2 = get_r2_client()
    r2.abort_multipart_upload(
        Bucket=settings.R2_BUCKET_NAME,
        Key=r2_key,
        UploadId=upload_id
    )


def head_object_size(r2_key: str) -> int | None:
    """ContentLength of an object, or None if it doesn't exist."""
    r2 = get_r2_client()
    try:
        return r2.head_object(Bucket=settings.R2_BUCKET_NAME, Key=r2_key)["ContentLength"]
    except r2.exceptions.ClientError:
        return None
