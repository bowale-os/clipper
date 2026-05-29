import modal
import tempfile
import boto3
import os
from botocore.config import Config

app = modal.App("clip-maker")

image = modal.Image.debian_slim().pip_install(
    "boto3",
    "ffmpeg-python"
).apt_install("ffmpeg")

def get_r2():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4"),
        region_name="auto"
    )


@app.function(
    image=image,
    min_containers=1,
    timeout=300,
    secrets=[modal.Secret.from_name("r2-secrets")]
)


def get_clip_from_r2(
    video_r2_key: str,
    clip_id: str,
    start_sec: float,
    end_sec: float,
):
    
    import ffmpeg
    
    try:

        r2 = get_r2()
        bucket = os.environ["R2_BUCKET_NAME"]

        # generate download URL for the source video
        download_url = r2.generate_presigned_url(
            "get_object",
            Params={"Bucket": bucket, "Key": video_r2_key},
            ExpiresIn=3600
        )
        probe = ffmpeg.probe(download_url)
        duration = float(probe['format']['duration'])

        if start_sec < 0 or start_sec >= end_sec or end_sec > duration:
            raise ValueError(
                f"Invalid clip range: require 0 <= start ({start_sec}) "
                f"< end ({end_sec}) <= duration ({duration})"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = f"{tmp_dir}/{clip_id}.mp4"

            # ffmpeg downloads only the bytes it needs
            (
                ffmpeg
                .input(download_url, ss=start_sec, to=end_sec)
                .output(output_path, c="copy")
                .overwrite_output()
                .run()
            )

            # upload clip to R2
            clip_r2_key = f"clips/{clip_id}.mp4"
            r2.upload_file(output_path, bucket, clip_r2_key)

        return {"clip_r2_key": clip_r2_key}

    except Exception as e:
        return {"error": f"This error {e} occurred"}
    

@app.function(
    image=image,
    timeout=60,
    secrets=[modal.Secret.from_name("r2-secrets")]
)

def get_video_duration(video_r2_key: str):
    import ffmpeg
    
    r2 = get_r2()
    bucket = os.environ["R2_BUCKET_NAME"]
    
    download_url = r2.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": video_r2_key},
        ExpiresIn=3600
    )
    
    probe = ffmpeg.probe(download_url)
    duration = round(float(probe['format']['duration']), 2)
    
    return {"duration": duration}