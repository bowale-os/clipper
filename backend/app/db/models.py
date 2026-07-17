import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, ForeignKey, Numeric, String, Text, Uuid, Index, desc, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON, DateTime, Enum, Integer


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# JSONB on Postgres (Neon), plain JSON when running tests against SQLite.
JSONVariant = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class VideoStatus(str, enum.Enum):
    uploading = "uploading"
    uploaded = "uploaded"
    processing = "processing"
    ready = "ready"
    error = "error"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    clerk_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String)
    name: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Video(Base):
    __tablename__ = "videos"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)  # minted at /videos/init
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    filename: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    duration_sec: Mapped[float | None] = mapped_column(Numeric)
    status: Mapped[VideoStatus] = mapped_column(
        Enum(VideoStatus, name="video_status"), default=VideoStatus.uploading, nullable=False
    )
    r2_key: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, default="default", nullable=False)
    artifacts: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    pipeline: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )




class Transcript(Base):
    __tablename__ = "transcripts"

    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), primary_key=True
    )
    language: Mapped[str | None] = mapped_column(String)
    provider: Mapped[str] = mapped_column(String, nullable=False)  # groq | openai | deepgram | local
    model: Mapped[str] = mapped_column(String, nullable=False)
    segments: Mapped[list] = mapped_column(JSONVariant, nullable=False)  # [{start, end, text, speaker}]
    words_r2_key: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class RankingRun(Base):
    __tablename__ = "ranking_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    params: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String, nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, default="running", nullable=False)  # running|done|error
    est_cost_usd: Mapped[float | None] = mapped_column(Numeric)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Moment(Base):
    __tablename__ = "moments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("ranking_runs.id"), nullable=False)
    start_sec: Mapped[float] = mapped_column(Numeric, nullable=False)   # snapped, final
    end_sec: Mapped[float] = mapped_column(Numeric, nullable=False)
    raw_start_sec: Mapped[float | None] = mapped_column(Numeric)        # what the LLM proposed
    raw_end_sec: Mapped[float | None] = mapped_column(Numeric)
    scores: Mapped[dict] = mapped_column(JSONVariant, nullable=False)   # {hook, completeness, shareability, visual, final}
    type: Mapped[str | None] = mapped_column(String)
    title: Mapped[str | None] = mapped_column(String)
    reason: Mapped[str | None] = mapped_column(Text)
    transcript_excerpt: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, default="candidate", nullable=False)  # candidate|kept|dismissed
    source: Mapped[str] = mapped_column(String, default="auto", nullable=False)       # auto|refined|manual
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Clip(Base):
    __tablename__ = "clips"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    moment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("moments.id"))
    video_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    parent_clip_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("clips.id"))
    params: Mapped[dict] = mapped_column(JSONVariant, nullable=False)  # {start,end,format,captions,crop}
    r2_key: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="queued", nullable=False)  # queued|rendering|ready|error
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE")
    )
    clip_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("clips.id"))
    type: Mapped[str] = mapped_column(String, nullable=False)  # ingest|transcribe|detect|verify|render
    status: Mapped[str] = mapped_column(String, default="queued", nullable=False)  # queued|running|done|error
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    rq_job_id: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    metrics: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


class MomentEvent(Base):
    __tablename__ = "moment_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    moment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("moments.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)  # keep|dismiss|export|adjust_bounds|more_like_this
    payload: Mapped[dict] = mapped_column(JSONVariant, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)


Index("videos_user_idx", Video.user_id, Video.created_at.desc())

Index(
    "moments_video_run_idx",
    Moment.video_id,
    Moment.run_id,
    desc(text("(scores->>'final')")),
)

Index("clips_video_idx", Clip.video_id, Clip.created_at.desc())
Index("jobs_video_idx", Job.video_id, Job.created_at.desc())