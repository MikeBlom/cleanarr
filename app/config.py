from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), env_file_encoding="utf-8", extra="ignore")

    SECRET_KEY: str = "change_me_to_long_random_string"
    BASE_URL: str = "http://localhost:8765"
    DEBUG: bool = False
    DATABASE_URL: str = "sqlite:////data/cleanarr.db"

    # Plex
    PLEX_CLIENT_ID: str = "cleanarr-default-client-id"
    PLEX_CLIENT_NAME: str = "CleanArr"
    PLEX_ADMIN_PLEX_IDS: str = ""  # comma-separated plex user IDs
    PLEX_SERVER_URL: str = "http://localhost:32400"
    PLEX_ADMIN_TOKEN: str = ""

    # Path mapping (Plex path → container path)
    PLEX_PATH_PREFIX_FROM: str = ""
    PLEX_PATH_PREFIX_TO: str = ""

    # cleanmedia
    CLEANMEDIA_BIN: str = "cleanmedia"
    ALLOWED_MEDIA_DIRS: str = "/mnt/media"

    # Sessions
    SESSION_COOKIE_NAME: str = "cleanarr_session"
    SESSION_MAX_AGE_DAYS: int = 30

    # Worker
    WORKER_POLL_INTERVAL_SEC: int = 2

    @property
    def admin_plex_ids(self) -> list[str]:
        return [x.strip() for x in self.PLEX_ADMIN_PLEX_IDS.split(",") if x.strip()]

    @property
    def allowed_media_dirs(self) -> list[str]:
        return [x.strip() for x in self.ALLOWED_MEDIA_DIRS.split(",") if x.strip()]


settings = Settings()
