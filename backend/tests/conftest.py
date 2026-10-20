"""Shared fixtures.

The suite never touches a real service. Before the app is imported, the environment is
pinned to placeholders (this also overrides a developer's backend/.env, so a test run
can never reach a real database or Redis). The database is an in-memory SQLite engine,
and storage, queues and the AI providers are replaced per test.
"""
import os

os.environ.update(
    {
        "SECRET_KEY": "test",
        "ENV": "test",
        "CLERK_SECRET_KEY": "test",
        "CLERK_WEBHOOK_SIGNING_SECRET": "whsec_" + "dGVzdC1zaWduaW5nLXNlY3JldC1mb3ItdGVzdHM=",
        "CLERK_FRONTEND_API": "clerk.test.invalid",
        "CLERK_DEV_FRONTEND_API": "clerk.dev.test.invalid",
        "R2_ENDPOINT_URL": "https://r2.test.invalid",
        "R2_ACCESS_KEY": "test",
        "R2_SECRET_ACCESS_KEY": "test",
        "R2_BUCKET_NAME": "test-bucket",
        "NEON_DB_CONNECT": "sqlite://",
        "REDIS_URL": "redis://localhost:6379/15",
        "GROQ_API_KEY": "test",
        "GEMINI_API_KEY": "test",
        "DEEPSEEK_API_KEY": "test",
    }
)

import uuid
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db.session as session_module
from app.db.models import Base, User, Video, VideoStatus


@pytest.fixture()
def db_engine(monkeypatch):
    """A fresh in-memory database, wired in as the app's engine and session factory."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(session_module, "_engine", engine)
    monkeypatch.setattr(session_module, "SessionLocal", factory)
    yield engine
    engine.dispose()


@pytest.fixture()
def db(db_engine):
    session = session_module.SessionLocal()
    yield session
    session.close()


@pytest.fixture()
def make_user(db):
    def _make(clerk_id=None, email="user@example.com"):
        user = User(clerk_id=clerk_id or f"user_{uuid.uuid4().hex[:8]}", email=email)
        db.add(user)
        db.commit()
        return user

    return _make


@pytest.fixture()
def user(make_user):
    return make_user("user_main")


@pytest.fixture()
def other_user(make_user):
    return make_user("user_other", email="other@example.com")


@pytest.fixture()
def make_video(db):
    def _make(owner, **overrides):
        vid = overrides.pop("id", uuid.uuid4())
        fields = dict(
            id=vid,
            user_id=owner.id,
            filename="talk.mp4",
            size_bytes=1000,
            status=VideoStatus.ready,
            r2_key=f"sources/{vid}/original.mp4",
            duration_sec=600,
            pipeline={},
            artifacts={},
        )
        fields.update(overrides)
        video = Video(**fields)
        db.add(video)
        db.commit()
        return video

    return _make


@pytest.fixture()
def rate_counter(monkeypatch):
    """Replaces the Redis rate-limit script with an in-process counter."""
    import app.dependencies.rate_limit as rl

    counts: dict = {}

    def fake(keys, args):
        counts[keys[0]] = counts.get(keys[0], 0) + 1
        return counts[keys[0]], int(args[0])

    monkeypatch.setattr(rl, "_CHECK_SCRIPT", fake)
    return counts


@pytest.fixture()
def r2(monkeypatch):
    """Mocks every storage helper the video routes call. Returns the mocks by name."""
    import app.api.video as video_api
    import app.api.clips as clips_api

    mocks = {}
    defaults = {
        "generate_upload_url": "https://r2.test/put",
        "create_multipart_upload": "upload-123",
        "generate_part_upload_urls": None,
        "list_uploaded_parts": [],
        "complete_multipart_upload": None,
        "abort_multipart_upload": None,
        "head_object_size": 1000,
        "delete_file": None,
        "delete_prefix": 0,
    }
    for name, value in defaults.items():
        mock = MagicMock(return_value=value)
        monkeypatch.setattr(video_api, name, mock)
        mocks[name] = mock
    mocks["generate_part_upload_urls"].side_effect = lambda key, uid, nums: {
        n: f"https://r2.test/part/{n}" for n in nums
    }
    download = MagicMock(side_effect=lambda key: f"https://r2.test/dl/{key}")
    monkeypatch.setattr(clips_api, "generate_download_url", download)
    mocks["generate_download_url"] = download
    return mocks


@pytest.fixture()
def queues(monkeypatch):
    import app.api.video as video_api
    import app.api.clips as clips_api

    io, cpu = MagicMock(), MagicMock()
    io.name, cpu.name = "io", "cpu"
    io.enqueue.return_value.id = "job-io"
    cpu.enqueue.return_value.id = "job-cpu"
    monkeypatch.setattr(video_api, "io_queue", io)
    monkeypatch.setattr(clips_api, "cpu_queue", cpu)
    return SimpleQueues(io, cpu)


class SimpleQueues:
    def __init__(self, io, cpu):
        self.io, self.cpu = io, cpu


@pytest.fixture()
def embed(monkeypatch):
    """Embedding calls fail by default (the routes must cope); tests can set a value."""
    import app.api.video as video_api

    mock = MagicMock(side_effect=RuntimeError("embeddings offline"))
    monkeypatch.setattr(video_api, "embed_text", mock)
    return mock


@pytest.fixture()
def client(db_engine, rate_counter, r2, queues, embed):
    """HTTP client with auth bypassed. Call client.login(user) to act as someone."""
    from app.dependencies.auth import get_current_user
    from app.main import app

    state = {"clerk_id": "user_main"}

    async def fake_auth():
        return state["clerk_id"]

    app.dependency_overrides[get_current_user] = fake_auth
    test_client = TestClient(app, raise_server_exceptions=False)
    test_client.login = lambda u: state.update(clerk_id=u.clerk_id)
    yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def anyio_backend():
    return "asyncio"


# ---------------------------------------------------------------- real media

import shutil
import subprocess

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
requires_ffmpeg = pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg and ffprobe are not installed")


@pytest.fixture(scope="session")
def sample_video(tmp_path_factory):
    """A real 6 second 320x240 video with a tone that goes silent from 2.0s to 3.5s."""
    if not HAS_FFMPEG:
        pytest.skip("ffmpeg and ffprobe are not installed")
    path = tmp_path_factory.mktemp("media") / "sample.mp4"
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", "testsrc=size=320x240:rate=25:duration=6",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=16000:duration=6",
            "-af", "volume=enable='between(t,2,3.5)':volume=0",
            "-c:v", "libx264", "-g", "25", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
            str(path),
        ],
        capture_output=True, check=True,
    )
    return path
