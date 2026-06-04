import modal
import tempfile
import boto3
import os
from botocore.config import Config

app = modal.App("clip-maker")

image = modal.Image.from_registry(
    "nvidia/cuda:12.1.0-cudnn8-runtime-ubuntu22.04"
).apt_install(
    "python3",
    "python3-pip",
    "ffmpeg"
).run_commands(
    "ln -s /usr/bin/python3 /usr/bin/python"  # so 'python' works not just 'python3'
).pip_install(
    "boto3",
    "ffmpeg-python",
    "google-genai",
    "faster-whisper",
    "pymongo",
)

def get_r2():
    return boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT_URL"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY"],
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
            download_video(download_url, output_path, start_sec=start_sec, end_sec=end_sec)

            # upload clip to R2
            clip_r2_key = f"clips/{clip_id}.mp4"
            r2.upload_file(output_path, bucket, clip_r2_key)

        return {"clip_r2_key": clip_r2_key}

    except Exception as e:
        return {"error": f"This error {e} occurred"}
    

@app.function(
    image=image,
    timeout=70,
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
    gpu="any",
    secrets=[
        modal.Secret.from_name("r2-secrets"),
        modal.Secret.from_name("mongo-secrets"),
        modal.Secret.from_name("gemini-secrets"),
    ]
)

def detect_moments(video_id: str, video_r2_key: str, content_type: str):
    import json
    import ffmpeg
    from google import genai
    from faster_whisper import WhisperModel
    from pymongo import MongoClient

    print(f"🚀 detect_moments started: video_id={video_id} content_type={content_type}")

    mongo_uri = os.environ["MONGO_CONNECT"]
    print(f"🔑 Mongo URI present: {mongo_uri is not None}")
    client = MongoClient(mongo_uri)
    db = client["clipper"]

    try:
        print(f"📝 Updating status to processing: video_id={video_id}")
        db.videos.update_one(
            {"_id": video_id},
            {"$set": {"status": "processing"}}
        )
        print(f"✅ Status updated to processing")

        # ❌ fix 1: double brackets os.environ[["GEMINI_API_KEY"]] → os.environ["GEMINI_API_KEY"]
        gemini_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        print(f"✅ Gemini client created")

        whisper_model = WhisperModel(
            "base",
            device="cuda",
            compute_type="float16"
        )
        print(f"✅ Whisper model loaded")

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = f"{tmp_dir}/{video_id}.mp4"
            print(f"📁 Temp dir created: {tmp_dir}")

            download_url = get_download_url(video_r2_key)
            print(f"🔗 Download URL generated for r2_key={video_r2_key}")

            download_video(download_url, output_path)
            print(f"⬇️ Video downloaded to {output_path}")

            print(f"🎙️ Starting Whisper transcription...")
            segments, info = whisper_model.transcribe(output_path)
            duration = round(info.duration, 2)
            print(f"✅ Whisper done: duration={duration}s language={info.language}")

            transcript = [
                {
                    "start": round(segment.start, 2),
                    "end": round(segment.end, 2),
                    "text": segment.text.strip()
                }
                for segment in segments
            ] ##how can these processes be faster??!! for loop is o of n, talk about this in interviews
            print(f"📝 Transcript segments: {len(transcript)}")

            prompts = {
                "football": """
                    Watch this football match footage and find all the key moments.
                    Look for: goals, saves, tackles, fouls, cards, big chances, celebrations.
                    For each moment return a JSON object with:
                    - start: timestamp in seconds, 3 seconds before the moment begins (integer)
                    - end: timestamp in seconds 3 seconds after the moment ends (integer)
                    - type: type of moment in 1-2 words e.g. "goal", "save", "tackle"
                    - description: one sentence describing what happens
                    - confidence: float between 0.0 and 1.0
                    Return ONLY a valid JSON array, no other text, no markdown, no code blocks.
                    Example: [{"start": 117, "end": 135, "type": "goal", "description": "Striker fires into top corner", "confidence": 0.95}]
                """,
                "stream": """
                    Watch this gaming stream and find the most exciting and clipworthy moments.
                    Look for: big plays, clutch moments, funny reactions, fails, hype moments.
                    For each moment return a JSON object with:
                    - start: timestamp in seconds, 3 seconds before the moment begins (integer)
                    - end: timestamp in seconds 3 seconds after the moment ends (integer)
                    - type: type of moment in 1-2 words
                    - description: one sentence describing what happens
                    - confidence: float between 0.0 and 1.0
                    Return ONLY a valid JSON array, no other text, no markdown, no code blocks.
                """,
                "podcast": """
                    Listen to this podcast and find the most interesting and shareable moments.
                    Look for: key insights, strong opinions, funny moments, surprising statements, quotable lines.
                    For each moment return a JSON object with:
                    - start: timestamp in seconds, 3 seconds before the moment begins (integer)
                    - end: timestamp in seconds 3 seconds after the moment ends (integer)
                    - type: type of moment in 1-2 words e.g. "insight", "joke", "opinion"
                    - description: one sentence or the actual quote
                    - confidence: float between 0.0 and 1.0
                    Return ONLY a valid JSON array, no other text, no markdown, no code blocks.
                """,
                "default": """
                    Watch this video and find all the interesting, exciting, or clipworthy moments.
                    Use your judgment based on what kind of content this is.
                    For each moment return a JSON object with:
                    - start: timestamp in seconds, 3 seconds before the moment begins (integer)
                    - end: timestamp in seconds 3 seconds after the moment ends (integer)
                    - type: type of moment in 1-2 words
                    - description: one sentence describing what happens
                    - confidence: float between 0.0 and 1.0
                    Return ONLY a valid JSON array, no other text, no markdown, no code blocks.
                """
            }

            prompt = prompts.get(content_type, prompts["default"])
            print(f"📋 Using prompt for content_type={content_type}")

            print(f"⬆️ Uploading video to Gemini...")
            # ❌ fix 2: gemini_client.upload(file=) → gemini_client.files.upload(path=)
            video_file = gemini_client.files.upload(file=output_path)
            print(f"✅ Video uploaded to Gemini: name={video_file.name} state={video_file.state}")

            while video_file.state.name == "PROCESSING":
                print(f"⏳ Gemini still processing file: state={video_file.state.name}")
                video_file = gemini_client.files.get(name=video_file.name)

            if video_file.state.name == "FAILED":
                raise RuntimeError("Gemini video file processing failed")

            print(f"✅ Gemini file ready: state={video_file.state.name}")
            print(f"🤖 Sending to Gemini for moment detection...")

            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",  # ❌ fix 3: gemini-2.5-flash not available yet → gemini-2.0-flash
                contents=[video_file, prompt],
            )
            print(f"✅ Gemini response received: length={len(response.text)}")
            print(f"📄 Raw response preview: {response.text[:200]}")

            try:
                moments = json.loads(response.text)
            except json.JSONDecodeError:
                print(f"⚠️ JSON parse failed, attempting to clean response...")
                cleaned = response.text.strip().strip("```json").strip("```").strip()
                moments = json.loads(cleaned)

            print(f"✅ Moments parsed: {len(moments)} moments found")

            print(f"💾 Saving to MongoDB...")
            db.videos.update_one(
                {"_id": video_id},
                {"$set": {
                    "status": "analyzed",
                    "moments": moments,
                    "transcript": transcript,
                    "duration": duration
                }}
            )
            print(f"✅ MongoDB updated: status=analyzed moments={len(moments)} transcript={len(transcript)}")

        print(f"🎉 detect_moments completed successfully: video_id={video_id}")
        return {"moments": moments, "transcript": transcript}

    except Exception as e:
        print(f"❌ detect_moments failed: {str(e)}")
        db.videos.update_one(
            {"_id": video_id},
            {"$set": {"status": "error", "error": str(e)}}
        )
        return {"error": str(e)}

    finally:
        client.close()
        print(f"🔒 MongoDB connection closed: video_id={video_id}")