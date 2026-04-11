from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class RequestType(str, enum.Enum):
    movie = "movie"
    episode = "episode"
    season = "season"
    series = "series"


class RequestStatus(str, enum.Enum):
    pending = "pending"
    queued = "queued"
    partially_complete = "partially_complete"
    complete = "complete"
    failed = "failed"


class JobStatus(str, enum.Enum):
    queued = "queued"
    running = "running"
    completed = "completed"
    failed = "failed"
    skipped = "skipped"
    already_exists = "already_exists"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plex_id: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    auth_method: Mapped[str] = mapped_column(String(32), default="plex", nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_email: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_webhook: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_inapp: Mapped[bool] = mapped_column(Boolean, default=True)
    webhook_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    sessions: Mapped[list[UserSession]] = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )
    requests: Mapped[list[ConversionRequest]] = relationship(
        "ConversionRequest", back_populates="user"
    )


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship("User", back_populates="sessions")


class ConversionRequest(Base):
    __tablename__ = "conversion_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    plex_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    source: Mapped[str] = mapped_column(String(32), default="plex", nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(512), nullable=True)
    request_type: Mapped[RequestType] = mapped_column(Enum(RequestType), nullable=False)
    filter_profanity: Mapped[bool] = mapped_column(Boolean, default=True)
    filter_nudity: Mapped[bool] = mapped_column(Boolean, default=False)
    use_whisper: Mapped[bool] = mapped_column(Boolean, default=False)
    use_bleep: Mapped[bool] = mapped_column(Boolean, default=True)
    audio_stream_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Per-request profanity overrides (NULL = use global settings)
    profanity_extra_words_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    profanity_extra_phrases_json: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )
    profanity_padding_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    whisper_model: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Per-request nudity overrides (NULL = use global settings)
    nudity_confidence: Mapped[float | None] = mapped_column(nullable=True)
    nudity_sample_fps: Mapped[float | None] = mapped_column(nullable=True)
    nudity_padding_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nudity_scene_merge_gap_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    nudity_categories_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Per-request multi-model pipeline overrides (NULL = use global settings)
    nudity_detectors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    nudity_ensemble_strategy: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    nudity_temporal_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    nudity_temporal_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nudity_temporal_min_flagged: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    nudity_extraction_mode: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    # Per-request violence/gore overrides (NULL = use global settings)
    filter_violence: Mapped[bool] = mapped_column(Boolean, default=False)
    violence_confidence: Mapped[float | None] = mapped_column(nullable=True)
    violence_sample_fps: Mapped[float | None] = mapped_column(nullable=True)
    violence_padding_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    violence_scene_merge_gap_ms: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    violence_categories_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    violence_detectors_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    violence_ensemble_strategy: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    violence_temporal_enabled: Mapped[bool | None] = mapped_column(
        Boolean, nullable=True
    )
    violence_temporal_window: Mapped[int | None] = mapped_column(Integer, nullable=True)
    violence_temporal_min_flagged: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    violence_extraction_mode: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    status: Mapped[RequestStatus] = mapped_column(
        Enum(RequestStatus), default=RequestStatus.pending
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    user: Mapped[User | None] = relationship("User", back_populates="requests")
    jobs: Mapped[list[ConversionJob]] = relationship(
        "ConversionJob", back_populates="request", cascade="all, delete-orphan"
    )


class ConversionJob(Base):
    __tablename__ = "conversion_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(
        ForeignKey("conversion_requests.id", ondelete="CASCADE")
    )
    plex_key: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    input_file: Mapped[str] = mapped_column(String(1024), nullable=False)
    output_file: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus), default=JobStatus.queued)
    priority: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    log_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_report: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    request: Mapped[ConversionRequest] = relationship(
        "ConversionRequest", back_populates="jobs"
    )

    __table_args__ = (Index("ix_jobs_status_created", "status", "created_at"),)


class Invitation(Base):
    __tablename__ = "invitations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(256), nullable=False)
    token: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    invited_by: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    request_id: Mapped[int | None] = mapped_column(
        ForeignKey("conversion_requests.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped[User] = relationship("User")

    __table_args__ = (Index("ix_notifications_user_read", "user_id", "is_read"),)


class ImdbParentalGuide(Base):
    __tablename__ = "imdb_parental_guides"

    imdb_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    data_json: Mapped[str] = mapped_column(Text, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )


class SystemTaskRun(Base):
    __tablename__ = "system_task_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="running"
    )  # running | completed | failed
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    result_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    progress_current: Mapped[int | None] = mapped_column(Integer, nullable=True)
    progress_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
