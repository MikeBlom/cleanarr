from __future__ import annotations

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
    pool_pre_ping=True,
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, connection_record):
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from . import models  # noqa: F401 – ensure models are registered

    Base.metadata.create_all(bind=engine)
    _migrate()
    _seed_settings()


def _seed_settings() -> None:
    from . import app_settings

    db = SessionLocal()
    try:
        app_settings.seed_defaults(db)
    finally:
        db.close()


def _migrate() -> None:
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(conversion_jobs)"))
        cols = {row[1] for row in result}
        if "content_report" not in cols:
            conn.execute(
                text("ALTER TABLE conversion_jobs ADD COLUMN content_report TEXT")
            )
        if "progress_json" not in cols:
            conn.execute(
                text("ALTER TABLE conversion_jobs ADD COLUMN progress_json TEXT")
            )
        if "priority" not in cols:
            conn.execute(
                text(
                    "ALTER TABLE conversion_jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0"
                )
            )

        # conversion_requests migrations
        result2 = conn.execute(text("PRAGMA table_info(conversion_requests)"))
        req_cols = {row[1] for row in result2}
        if "audio_stream_index" not in req_cols:
            conn.execute(
                text(
                    "ALTER TABLE conversion_requests ADD COLUMN audio_stream_index INTEGER"
                )
            )
        for col in (
            "profanity_extra_words_json TEXT",
            "profanity_extra_phrases_json TEXT",
            "profanity_padding_ms INTEGER",
            "whisper_model VARCHAR(32)",
            "nudity_confidence REAL",
            "nudity_sample_fps REAL",
            "nudity_padding_ms INTEGER",
            "nudity_scene_merge_gap_ms INTEGER",
            "nudity_categories_json TEXT",
            "nudity_detectors_json TEXT",
            "nudity_ensemble_strategy VARCHAR(32)",
            "nudity_temporal_enabled BOOLEAN",
            "nudity_temporal_window INTEGER",
            "nudity_temporal_min_flagged INTEGER",
            "nudity_extraction_mode VARCHAR(32)",
            "filter_violence BOOLEAN DEFAULT 0",
            "violence_confidence REAL",
            "violence_sample_fps REAL",
            "violence_padding_ms INTEGER",
            "violence_scene_merge_gap_ms INTEGER",
            "violence_categories_json TEXT",
            "violence_detectors_json TEXT",
            "violence_ensemble_strategy VARCHAR(32)",
            "violence_temporal_enabled BOOLEAN",
            "violence_temporal_window INTEGER",
            "violence_temporal_min_flagged INTEGER",
            "violence_extraction_mode VARCHAR(32)",
        ):
            col_name = col.split()[0]
            if col_name not in req_cols:
                conn.execute(text(f"ALTER TABLE conversion_requests ADD COLUMN {col}"))

        # conversion_requests source/upload migrations
        if "source" not in req_cols:
            conn.execute(
                text(
                    "ALTER TABLE conversion_requests ADD COLUMN source VARCHAR(32) NOT NULL DEFAULT 'plex'"
                )
            )
        if "original_filename" not in req_cols:
            conn.execute(
                text(
                    "ALTER TABLE conversion_requests ADD COLUMN original_filename VARCHAR(512)"
                )
            )

        # users migrations
        result3 = conn.execute(text("PRAGMA table_info(users)"))
        user_cols = {row[1] for row in result3}
        if "auth_method" not in user_cols:
            conn.execute(
                text(
                    "ALTER TABLE users ADD COLUMN auth_method VARCHAR(32) NOT NULL DEFAULT 'plex'"
                )
            )
        if "password_hash" not in user_cols:
            conn.execute(
                text("ALTER TABLE users ADD COLUMN password_hash VARCHAR(255)")
            )

        conn.commit()
