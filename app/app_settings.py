"""Read/write application settings stored in the DB (app_settings table).

These replace many .env variables so the app is configurable from the admin UI.
On first run, defaults are seeded.  The worker reads these at job time so
changes take effect without a restart.
"""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from .models import AppSetting

# ── Defaults ────────────────────────────────────────────────────────────────
# Key → (default_value, description)
_DEFAULTS: dict[str, tuple[str, str]] = {
    # Plex
    "plex_server_url": ("http://localhost:32400", "Plex Media Server URL"),
    "plex_admin_token": ("", "Plex admin token (X-Plex-Token)"),
    "plex_client_id": ("cleanarr-default-client-id", "Plex OAuth client ID"),
    "plex_admin_plex_ids": ("", "Comma-separated Plex user IDs that are auto-admin"),
    # Path mapping
    "plex_path_prefix_from": ("", "Plex file-path prefix to strip"),
    "plex_path_prefix_to": ("", "Replacement prefix for container paths"),
    "allowed_media_dirs": ("/mnt/media", "Comma-separated allowed media directories"),
    # cleanmedia binary
    "cleanmedia_bin": ("cleanmedia", "Path to the cleanmedia binary"),
    # Profanity
    "profanity_words": (json.dumps([
        "fuck", "fucking", "fucker", "motherfucker", "motherfucking",
        "shit", "shitting", "shitty", "bullshit",
        "ass", "asshole", "bitch", "bitching", "bastard",
        "damn", "dammit", "goddamn",
        "cunt", "cock", "dick", "prick", "pussy",
        "whore", "slut",
        "nigger", "nigga", "faggot", "fag",
        "retard", "retarded",
        "crap", "jackass", "dipshit", "dumbass", "hellhole",
        "piss", "pissed",
    ]), "JSON list of profanity words"),
    "profanity_phrases": (json.dumps([
        "son of a bitch", "piece of shit", "what the fuck",
        "what the hell", "holy shit", "go to hell",
        "kiss my ass", "shut the fuck up", "shut up",
        "screw you", "up yours",
    ]), "JSON list of profanity phrases"),
    "profanity_padding_ms": ("200", "Audio mute padding in ms"),
    "whisper_model": ("base", "Whisper model size (tiny/base/small/medium/large)"),
    # Nudity
    "nudity_confidence": ("0.7", "Nudity detection confidence threshold (0.0–1.0)"),
    "nudity_categories": (json.dumps([
        "FEMALE_BREAST_EXPOSED",
        "FEMALE_GENITALIA_EXPOSED",
        "MALE_GENITALIA_EXPOSED",
        "ANUS_EXPOSED",
        "BUTTOCKS_EXPOSED",
    ]), "JSON list of enabled nudity categories"),
    "nudity_sample_fps": ("2", "Frames per second to sample for nudity"),
    "nudity_padding_ms": ("500", "Video blackout padding in ms"),
    "nudity_scene_merge_gap_ms": ("5000", "Bridge nudity detections within this gap (ms) into one continuous blackout"),
    # Multi-model nudity pipeline
    "nudity_detectors": ('["nudenet"]', "JSON list of detector backends to use (nudenet, vit_nsfw)"),
    "nudity_ensemble_strategy": ("weighted_average", "Ensemble voting strategy (weighted_average, unanimous, any)"),
    "nudity_temporal_enabled": ("false", "Enable temporal consistency filter to suppress isolated false positives"),
    "nudity_temporal_window": ("5", "Sliding window size for temporal filter (number of frames)"),
    "nudity_temporal_min_flagged": ("3", "Minimum flagged frames in window to keep a detection"),
    "nudity_extraction_mode": ("fixed_fps", "Frame extraction mode (fixed_fps, keyframe, auto)"),
    "nudity_device": ("auto", "Device for ML models (auto, cpu, cuda)"),
    # Violence/gore
    "violence_confidence": ("0.5", "Violence detection confidence threshold (0.0–1.0)"),
    "violence_categories": (json.dumps([
        "GORE_BLOODSHED",
        "VIOLENCE_FIGHTING",
    ]), "JSON list of enabled violence categories"),
    "violence_sample_fps": ("2", "Frames per second to sample for violence"),
    "violence_padding_ms": ("500", "Video blackout padding in ms for violence"),
    "violence_scene_merge_gap_ms": ("5000", "Bridge violence detections within this gap (ms)"),
    "violence_detectors": ('["siglip_violence"]', "JSON list of violence detector backends (siglip_violence, vit_violence)"),
    "violence_ensemble_strategy": ("weighted_average", "Violence ensemble voting strategy"),
    "violence_temporal_enabled": ("false", "Enable temporal consistency filter for violence detection"),
    "violence_temporal_window": ("5", "Sliding window size for violence temporal filter"),
    "violence_temporal_min_flagged": ("3", "Minimum flagged frames in window for violence"),
    "violence_extraction_mode": ("fixed_fps", "Frame extraction mode for violence (fixed_fps, keyframe, auto)"),
    "violence_device": ("auto", "Device for violence ML models (auto, cpu, cuda)"),
    # AI Content Advisor (Ollama)
    "ollama_url": ("http://localhost:11434", "Ollama API URL for AI content evaluation"),
    "ollama_model": ("llama3.2:1b", "Ollama model to use for content evaluation"),
    "ai_advisor_enabled": ("true", "Enable AI evaluation of IMDB data to auto-set filter defaults"),
}


def get(db: Session, key: str) -> str:
    """Return the value for *key*, falling back to the compiled default."""
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row is not None:
        return row.value
    default, _ = _DEFAULTS.get(key, ("", ""))
    return default


def get_json(db: Session, key: str) -> Any:
    """Return a parsed JSON value for *key*."""
    return json.loads(get(db, key))


def put(db: Session, key: str, value: str) -> None:
    """Upsert a setting."""
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))
    db.flush()


def seed_defaults(db: Session) -> None:
    """Insert any missing keys with their default values."""
    existing = {r.key for r in db.query(AppSetting.key).all()}
    for key, (default, _desc) in _DEFAULTS.items():
        if key not in existing:
            db.add(AppSetting(key=key, value=default))
    db.commit()


def all_settings(db: Session) -> dict[str, str]:
    """Return all settings as a dict, filling in defaults for missing keys."""
    stored = {r.key: r.value for r in db.query(AppSetting).all()}
    for key, (default, _desc) in _DEFAULTS.items():
        stored.setdefault(key, default)
    return stored


def descriptions() -> dict[str, str]:
    """Return key → description map."""
    return {k: desc for k, (_, desc) in _DEFAULTS.items()}
