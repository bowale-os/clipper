import modal
import tempfile
import boto3
import os
from botocore.config import Config

app = modal.App("clip-maker")

image = modal.Image.debian_slim().pip_install(
    "boto3",
    "ffmpeg-python",  # fixed missing comma
    "google-generativeai",
    "faster-whisper",
    "pymongo",
).apt_install("ffmpeg")


def get_r2():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY"],  # fixed key name
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4"),
        region_name="auto"
    )

def get_download_url(r2_key: str, expires: int = 3600):
    r2 = get_r2()
    return r2.generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["R2_BUCKET_NAME"], "Key": r2_key},
        ExpiresIn=expires
    )

def download_video(url: str, output_path: str, start_sec: float = None, end_sec: float = None):
    import subprocess
    cmd = ["ffmpeg", "-i", url]
    if start_sec is not None:
        cmd += ["-ss", str(start_sec)]
    if end_sec is not None:
        cmd += ["-to", str(end_sec)]
    cmd += ["-c", "copy", output_path, "-y"]
    subprocess.run(cmd, check=True)


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
        download_url = get_download_url(video_r2_key)

        probe = ffmpeg.probe(download_url)
        duration = float(probe['format']['duration'])

        if start_sec < 0 or start_sec >= end_sec or end_sec > duration:
            raise ValueError(
                f"Invalid clip range: require 0 <= start ({start_sec}) "
                f"< end ({end_sec}) <= duration ({duration})"
            )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = f"{tmp_dir}/{clip_id}.mp4"
            download_video(download_url, output_path, start_sec=start_sec, end_sec=end_sec)
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

    download_url = get_download_url(video_r2_key)
    probe = ffmpeg.probe(download_url)
    duration = round(float(probe['format']['duration']), 2)

    return {"duration": duration}


@app.function(
    image=image,
    timeout=3600,
    secrets=[
        modal.Secret.from_name("r2-secrets"),
        modal.Secret.from_name("gemini-secrets"),
        modal.Secret.from_name("mongo-secrets")
    ]
)
def detect_moments(video_id: str, video_r2_key: str, content_type: str):
    import json
    import ffmpeg
    from google import genai
    from faster_whisper import WhisperModel
    from pymongo import MongoClient

    mongo_uri = os.environ["MONGO_CONNECT"]
    client = MongoClient(mongo_uri)
    db = client["clipper"]

    try:
        # mark as processing
        db.videos.update_one(
            {"_id": video_id},
            {"$set": {"status": "processing"}}
        )

        genai.configure(api_key=os.environ["GEMINI_API_KEY"])

        whisper_model = WhisperModel(
            "base",
            device="cpu",
            compute_type="int8"
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = f"{tmp_dir}/{video_id}.mp4"

            download_url = get_download_url(video_r2_key)
            download_video(download_url, output_path)

            # get duration
            probe = ffmpeg.probe(output_path)
            duration = round(float(probe['format']['duration']), 2)

            # whisper transcript
            segments, info = whisper_model.transcribe(output_path)
            transcript = [
                {
                    "start": round(segment.start, 2),
                    "end": round(segment.end, 2),
                    "text": segment.text.strip()
                }
                for segment in segments
            ]

            # gemini prompts
            prompts = {
                "football": """
                    Watch this football match footage and find all the key moments.
                    Look for: goals, saves, tackles, fouls, cards, big chances, celebrations.
                    For each moment return a JSON object with:
                    - t: timestamp in seconds as an integer
                    - type: type of moment in 1-2 words e.g. "goal", "save", "tackle"
                    - description: one sentence describing what happens
                    - confidence: float between 0.0 and 1.0
                    Return ONLY a valid JSON array, no other text, no markdown, no code blocks.
                    Example: [{"t": 120, "type": "goal", "description": "Striker fires into top corner", "confidence": 0.95}]
                """,
                "stream": """
                    Watch this gaming stream and find the most exciting and clipworthy moments.
                    Look for: big plays, clutch moments, funny reactions, fails, hype moments.
                    For each moment return a JSON object with:
                    - t: timestamp in seconds as an integer
                    - type: type of moment in 1-2 words
                    - description: one sentence describing what happens
                    - confidence: float between 0.0 and 1.0
                    Return ONLY a valid JSON array, no other text, no markdown, no code blocks.
                """,
                "podcast": """
                    Listen to this podcast and find the most interesting and shareable moments.
                    Look for: key insights, strong opinions, funny moments, surprising statements, quotable lines.
                    For each moment return a JSON object with:
                    - t: timestamp in seconds as an integer
                    - type: type of moment in 1-2 words e.g. "insight", "joke", "opinion"
                    - description: one sentence or the actual quote
                    - confidence: float between 0.0 and 1.0
                    Return ONLY a valid JSON array, no other text, no markdown, no code blocks.
                """,
                "default": """
                    Watch this video and find all the interesting, exciting, or clipworthy moments.
                    Use your judgment based on what kind of content this is.
                    For each moment return a JSON object with:
                    - t: timestamp in seconds as an integer
                    - type: type of moment in 1-2 words
                    - description: one sentence describing what happens
                    - confidence: float between 0.0 and 1.0
                    Return ONLY a valid JSON array, no other text, no markdown, no code blocks.
                """
            }

            prompt = prompts.get(content_type, prompts["default"])

            # upload to gemini and analyze
            gemini_model = genai.GenerativeModel("gemini-1.5-pro")
            video_file = genai.upload_file(path=output_path)
            response = gemini_model.generate_content([video_file, prompt])

            # parse moments — handle markdown wrapping
            try:
                moments = json.loads(response.text)
            except json.JSONDecodeError:
                cleaned = response.text.strip().strip("```json").strip("```").strip()
                moments = json.loads(cleaned)

            # save everything to MongoDB
            db.videos.update_one(
                {"_id": video_id},
                {"$set": {
                    "status": "analyzed",
                    "moments": moments,
                    "transcript": transcript,
                    "duration": duration
                }}
            )

        return {"moments": moments, "transcript": transcript}

    except Exception as e:
        db.videos.update_one(
            {"_id": video_id},
            {"$set": {"status": "error", "error": str(e)}}
        )
        return {"error": str(e)}

    finally:
        client.close()