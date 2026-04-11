from __future__ import annotations

from typing import Callable

from sqlalchemy.orm import Session

from ..models import ConversionJob, ConversionRequest
from ..plex.client import PlexClient, PlexError
from .registry import register_task


def _find_by_search(client: PlexClient, title: str, old_key: str) -> dict | None:
    """Search Plex by title to find an item whose key changed."""
    try:
        hubs = client.global_search(title, limit=10)
    except PlexError:
        return None

    for hub in hubs:
        for item in hub.get("Metadata", []):
            # Exact title match (case-insensitive)
            if item.get("title", "").lower() == title.lower():
                return item
    return None


@register_task(
    name="sync_plex_paths",
    display_name="Sync Plex Paths",
    description="Re-resolves file paths and Plex keys for all conversion jobs.",
    icon="fa-rotate",
)
def sync_plex_paths(db: Session, set_progress: Callable[[int, int], None]) -> str:
    jobs = db.query(ConversionJob).all()
    if not jobs:
        return "No conversion jobs found."

    client = PlexClient(db)
    path_updated = 0
    key_updated = 0
    errors = 0
    total = len(jobs)

    # Cache request plex_key updates so we don't update the same request twice
    request_key_updates: dict[int, str] = {}

    set_progress(0, total)

    for i, job in enumerate(jobs, 1):
        item = None

        # Try the stored plex_key first
        try:
            item = client.get_item(job.plex_key)
        except PlexError:
            pass

        # Key failed — search by title to find the new key
        if item is None:
            item = _find_by_search(client, job.title, job.plex_key)
            if item:
                new_key = str(item.get("ratingKey", ""))
                if new_key and new_key != job.plex_key:
                    job.plex_key = new_key
                    key_updated += 1
                    # Also update the parent request's plex_key
                    if job.request_id not in request_key_updates:
                        request_key_updates[job.request_id] = new_key

        if item is None:
            errors += 1
            set_progress(i, total)
            continue

        # Resolve the current file path
        try:
            new_path = client.resolve_file_path(item, db=db)
            if new_path != job.input_file:
                job.input_file = new_path
                path_updated += 1
        except PlexError:
            errors += 1

        set_progress(i, total)

    # Update parent request plex_keys
    for req_id, new_key in request_key_updates.items():
        req = (
            db.query(ConversionRequest)
            .filter(ConversionRequest.id == req_id)
            .first()
        )
        if req:
            req.plex_key = new_key

    db.commit()

    parts = []
    if path_updated:
        parts.append(f"{path_updated} path(s) updated")
    if key_updated:
        parts.append(f"{key_updated} Plex key(s) re-linked")
    if not parts:
        parts.append("All paths are current")
    parts.append(f"({total} jobs checked)")
    if errors:
        parts.append(f"{errors} could not be resolved")
    return ". ".join(parts) + "."
