from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

import httpx
from sqlalchemy.orm import Session

from .models import ImdbParentalGuide

log = logging.getLogger(__name__)

CACHE_TTL_DAYS = 30

_DISPLAY_LABELS = {
    "nudity": "Sex & Nudity",
    "violence": "Violence & Gore",
    "profanity": "Profanity",
    "alcohol": "Alcohol, Drugs & Smoking",
    "frightening": "Frightening & Intense Scenes",
}

_GRAPHQL_URL = "https://graphql.imdb.com/"

_PARENTAL_GUIDE_QUERY = """
query ParentalGuide($id: ID!) {
  title(id: $id) {
    parentsGuide {
      guideItems(first: 100) {
        edges {
          node {
            category { id text }
            isSpoiler
            text { plainText }
          }
        }
      }
      categories {
        ... on ParentsGuideCategorySummary {
          category { id text }
          severity { text }
        }
      }
    }
  }
}
"""


def extract_imdb_id(item: dict) -> str | None:
    """Extract IMDB tt ID from a Plex item's Guid array."""
    for guid in item.get("Guid", []):
        gid = guid.get("id", "")
        m = re.search(r"(tt\d+)", gid)
        if m:
            return m.group(1)
    return None


def extract_imdb_id_for_item(item: dict, plex_client) -> str | None:
    """Extract IMDB ID, preferring the item's own ID.

    Falls back to the parent show only for seasons (which don't have
    their own IMDB parental guide) or if the item itself has no IMDB GUID.
    """
    item_type = item.get("type", "")

    # Seasons don't have their own parental guide on IMDB — use the show's
    if item_type == "season":
        show_key = item.get("parentRatingKey")
        if show_key:
            try:
                show = plex_client.get_item(show_key)
                return extract_imdb_id(show)
            except Exception:
                pass

    # For episodes and movies, prefer their own IMDB ID
    own_id = extract_imdb_id(item)
    if own_id:
        return own_id

    # Fallback: walk up to show for episodes without their own IMDB GUID
    if item_type == "episode":
        show_key = item.get("grandparentRatingKey")
        if show_key:
            try:
                show = plex_client.get_item(show_key)
                return extract_imdb_id(show)
            except Exception:
                pass

    return None


def get_parental_guide(imdb_id: str, db: Session) -> dict | None:
    """Get parsed parental guide data, using SQLite cache with 30-day TTL."""
    cached = db.get(ImdbParentalGuide, imdb_id)
    if cached and cached.fetched_at > datetime.utcnow() - timedelta(days=CACHE_TTL_DAYS):
        try:
            guide = json.loads(cached.data_json)
            # Fix labels from older cached entries that stored severity as label
            for key, info in guide.items():
                if key in _DISPLAY_LABELS and info.get("label") in (None, info.get("severity"), "None"):
                    info["label"] = _DISPLAY_LABELS[key]
            return guide
        except Exception:
            pass

    parsed = _fetch_parental_guide(imdb_id)
    if not parsed:
        return None

    data_json = json.dumps(parsed)
    if cached:
        cached.data_json = data_json
        cached.fetched_at = datetime.utcnow()
    else:
        db.add(ImdbParentalGuide(
            imdb_id=imdb_id,
            data_json=data_json,
            fetched_at=datetime.utcnow(),
        ))
    db.commit()

    return parsed


def _fetch_parental_guide(imdb_id: str) -> dict | None:
    """Fetch parental guide from IMDB's GraphQL API."""
    try:
        resp = httpx.post(
            _GRAPHQL_URL,
            json={"query": _PARENTAL_GUIDE_QUERY, "variables": {"id": imdb_id}},
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        log.exception("Failed to fetch parental guide for %s", imdb_id)
        return None

    title = (data.get("data") or {}).get("title")
    if not title:
        return None
    pg = title.get("parentsGuide")
    if not pg:
        return None

    # Build severity map from categories
    severity_map: dict[str, str] = {}
    for cat_summary in pg.get("categories", []):
        cat = cat_summary.get("category", {})
        sev = cat_summary.get("severity", {})
        if cat.get("id") and sev.get("text"):
            severity_map[cat["id"]] = sev["text"]

    # Build descriptions grouped by category
    cat_items: dict[str, list[str]] = {}
    cat_labels: dict[str, str] = {}
    for edge in (pg.get("guideItems") or {}).get("edges", []):
        node = edge.get("node", {})
        if node.get("isSpoiler"):
            continue
        cat = node.get("category", {})
        cat_id = cat.get("id", "")
        text = (node.get("text") or {}).get("plainText", "")
        if cat_id and text:
            cat_items.setdefault(cat_id, []).append(text)
            cat_labels[cat_id] = cat.get("text", cat_id)

    # Merge into result
    all_cat_ids = set(severity_map.keys()) | set(cat_items.keys())
    # Ordered display
    order = ["NUDITY", "VIOLENCE", "PROFANITY", "ALCOHOL", "FRIGHTENING"]
    result = {}
    for cat_id in order:
        if cat_id not in all_cat_ids:
            continue
        result[cat_id.lower()] = {
            "label": cat_labels.get(cat_id, _DISPLAY_LABELS.get(cat_id.lower(), cat_id)),
            "severity": severity_map.get(cat_id, "Unknown"),
            "descriptions": cat_items.get(cat_id, []),
        }

    return result if result else None
