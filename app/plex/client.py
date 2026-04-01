from __future__ import annotations

from pathlib import Path

import httpx

from ..config import settings


class PlexError(Exception):
    pass


class PlexClient:
    def __init__(self, db=None) -> None:
        if db:
            from .. import app_settings
            self.base_url = app_settings.get(db, "plex_server_url").rstrip("/")
            self.token = app_settings.get(db, "plex_admin_token")
        else:
            self.base_url = settings.PLEX_SERVER_URL.rstrip("/")
            self.token = settings.PLEX_ADMIN_TOKEN

    def _get(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        p = {"X-Plex-Token": self.token, **(params or {})}
        try:
            resp = httpx.get(url, params=p, headers={"Accept": "application/json"}, timeout=15)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as exc:
            raise PlexError(str(exc)) from exc

    def libraries(self) -> list[dict]:
        data = self._get("/library/sections")
        return data.get("MediaContainer", {}).get("Directory", [])

    def library_items(self, section_id: str, offset: int = 0, limit: int = 50) -> dict:
        data = self._get(
            f"/library/sections/{section_id}/all",
            params={"X-Plex-Container-Start": offset, "X-Plex-Container-Size": limit},
        )
        return data.get("MediaContainer", {})

    def get_item(self, key: str) -> dict:
        """Return the metadata item for a given Plex key (e.g. /library/metadata/123)."""
        if not key.startswith("/"):
            key = f"/library/metadata/{key}"
        data = self._get(key)
        items = data.get("MediaContainer", {}).get("Metadata", [])
        if not items:
            raise PlexError(f"No metadata found for key: {key}")
        return items[0]

    def get_children(self, key: str) -> list[dict]:
        """Get children of a season/show (episodes/seasons)."""
        if not key.startswith("/"):
            key = f"/library/metadata/{key}"
        data = self._get(f"{key}/children")
        return data.get("MediaContainer", {}).get("Metadata", [])

    def get_leaves(self, key: str) -> list[dict]:
        """Get all leaf items (episodes) under a show or season."""
        if not key.startswith("/"):
            key = f"/library/metadata/{key}"
        data = self._get(f"{key}/allLeaves")
        return data.get("MediaContainer", {}).get("Metadata", [])

    def resolve_file_path(self, item: dict, db=None) -> str:
        """Extract and remap the file path from a leaf item."""
        try:
            raw_path = item["Media"][0]["Part"][0]["file"]
        except (KeyError, IndexError) as exc:
            raise PlexError("Could not extract file path from item") from exc

        path = raw_path
        if db:
            from .. import app_settings
            prefix_from = app_settings.get(db, "plex_path_prefix_from")
            prefix_to = app_settings.get(db, "plex_path_prefix_to")
            allowed_str = app_settings.get(db, "allowed_media_dirs")
            allowed_dirs = [x.strip() for x in allowed_str.split(",") if x.strip()]
        else:
            prefix_from = settings.PLEX_PATH_PREFIX_FROM
            prefix_to = settings.PLEX_PATH_PREFIX_TO
            allowed_dirs = settings.allowed_media_dirs

        if prefix_from and path.startswith(prefix_from):
            path = prefix_to + path[len(prefix_from):]

        resolved = Path(path).resolve()
        allowed = [Path(d).resolve() for d in allowed_dirs]
        if not any(str(resolved).startswith(str(a)) for a in allowed):
            raise PlexError(f"File path not in allowed media dirs: {resolved}")

        return str(resolved)

    def global_search(self, query: str, limit: int = 30) -> list[dict]:
        """Search across all libraries. Returns a list of Hub dicts, each with a Metadata list."""
        data = self._get("/hubs/search", params={"query": query, "limit": limit})
        return data.get("MediaContainer", {}).get("Hub", [])

    def search(self, section_id: str, query: str) -> list[dict]:
        data = self._get(
            f"/library/sections/{section_id}/all",
            params={"title": query},
        )
        return data.get("MediaContainer", {}).get("Metadata", [])

    def get_audio_streams(self, item: dict) -> list[dict]:
        """Return audio streams for a media item with Plex selection info.

        Each dict has: index (ffprobe stream index), codec, channels, language,
        languageCode, displayTitle, selected (True = Plex's current choice).
        """
        try:
            streams = item["Media"][0]["Part"][0]["Stream"]
        except (KeyError, IndexError):
            return []
        return [s for s in streams if s.get("streamType") == 2]

    def refresh_section(self, section_id: str | int) -> None:
        """Trigger a library section refresh so Plex picks up new/changed files."""
        url = f"{self.base_url}/library/sections/{section_id}/refresh"
        try:
            resp = httpx.get(url, params={"X-Plex-Token": self.token}, timeout=10)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise PlexError(f"Library refresh failed: {exc}") from exc

    def get_section_id_for_item(self, plex_key: str) -> str | None:
        """Return the library section ID for a given Plex item key."""
        try:
            item = self.get_item(plex_key)
            return str(item.get("librarySectionID", ""))
        except PlexError:
            return None

    def thumb_url(self, thumb: str) -> str:
        """Build a proxied thumb URL via this server."""
        return f"{self.base_url}{thumb}?X-Plex-Token={self.token}"
