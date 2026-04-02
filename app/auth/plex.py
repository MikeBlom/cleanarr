from __future__ import annotations

import time

import httpx

from ..config import settings

PLEX_API_BASE = "https://plex.tv/api/v2"


def _headers() -> dict[str, str]:
    return {
        "Accept": "application/json",
        "X-Plex-Client-Identifier": settings.PLEX_CLIENT_ID,
        "X-Plex-Product": settings.PLEX_CLIENT_NAME,
    }


def create_pin() -> tuple[int, str]:
    """Create a Plex PIN. Returns (pin_id, pin_code)."""
    resp = httpx.post(
        f"{PLEX_API_BASE}/pins", headers=_headers(), data={"strong": "true"}
    )
    resp.raise_for_status()
    data = resp.json()
    return data["id"], data["code"]


def plex_auth_url(pin_code: str, callback_url: str) -> str:
    import urllib.parse

    params = urllib.parse.urlencode(
        {
            "clientID": settings.PLEX_CLIENT_ID,
            "code": pin_code,
            "context[device][product]": settings.PLEX_CLIENT_NAME,
            "forwardUrl": callback_url,
        }
    )
    return f"https://app.plex.tv/auth#?{params}"


def poll_pin(pin_id: int, max_attempts: int = 30) -> str | None:
    """Poll until auth token appears or timeout. Returns auth token or None."""
    for _ in range(max_attempts):
        resp = httpx.get(f"{PLEX_API_BASE}/pins/{pin_id}", headers=_headers())
        resp.raise_for_status()
        data = resp.json()
        if data.get("authToken"):
            return data["authToken"]
        time.sleep(1)
    return None


def fetch_user_info(auth_token: str) -> dict:
    """Fetch Plex user info using the auth token."""
    headers = {**_headers(), "X-Plex-Token": auth_token}
    resp = httpx.get(f"{PLEX_API_BASE}/user", headers=headers)
    resp.raise_for_status()
    return resp.json()


def fetch_server_users(server_url: str, admin_token: str) -> list[dict]:
    """Fetch users who have access to the Plex server.

    Tries the plex.tv friends API first (returns emails), falls back to
    the local server /accounts endpoint if that fails.

    Returns a list of dicts with keys: id, username, email.
    """
    users = _fetch_plex_tv_friends(admin_token)
    if users is not None:
        return users
    return _fetch_server_accounts(server_url, admin_token)


def _fetch_plex_tv_friends(admin_token: str) -> list[dict] | None:
    """Fetch friends from plex.tv API (includes emails)."""
    try:
        headers = {**_headers(), "X-Plex-Token": admin_token}
        resp = httpx.get(f"{PLEX_API_BASE}/friends", headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        users = []
        for friend in data:
            plex_id = str(friend.get("id", ""))
            if plex_id and plex_id not in ("0", "1"):
                users.append(
                    {
                        "id": plex_id,
                        "username": friend.get("username") or friend.get("title", ""),
                        "email": friend.get("email", ""),
                    }
                )
        return users
    except Exception:
        return None


def _fetch_server_accounts(server_url: str, admin_token: str) -> list[dict]:
    """Fallback: fetch accounts from local Plex server (no emails)."""
    url = f"{server_url.rstrip('/')}/accounts"
    headers = {
        "Accept": "application/json",
        "X-Plex-Token": admin_token,
    }
    resp = httpx.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    users = []
    for account in data.get("MediaContainer", {}).get("Account", []):
        plex_id = str(account.get("id", ""))
        name = account.get("name", "")
        if plex_id and plex_id not in ("0", "1"):
            users.append(
                {
                    "id": plex_id,
                    "username": name,
                    "email": account.get("email", ""),
                }
            )
    return users
