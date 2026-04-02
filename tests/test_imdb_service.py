from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from app.imdb_service import (
    extract_imdb_id,
    extract_imdb_id_for_item,
    get_parental_guide,
)
from app.models import ImdbParentalGuide


def test_extract_imdb_id_from_guid():
    item = {"Guid": [{"id": "imdb://tt1234567"}, {"id": "tmdb://999"}]}
    assert extract_imdb_id(item) == "tt1234567"


def test_extract_imdb_id_no_match():
    item = {"Guid": [{"id": "tmdb://999"}]}
    assert extract_imdb_id(item) is None


def test_extract_imdb_id_no_guid():
    assert extract_imdb_id({}) is None


def test_extract_imdb_id_for_item_movie():
    item = {"type": "movie", "Guid": [{"id": "imdb://tt9999999"}]}
    result = extract_imdb_id_for_item(item, None)
    assert result == "tt9999999"


def test_extract_imdb_id_for_item_season():
    mock_client = MagicMock()
    mock_client.get_item.return_value = {"Guid": [{"id": "imdb://tt1111111"}]}
    item = {"type": "season", "parentRatingKey": "50"}
    result = extract_imdb_id_for_item(item, mock_client)
    assert result == "tt1111111"


def test_extract_imdb_id_for_item_episode_fallback():
    mock_client = MagicMock()
    mock_client.get_item.return_value = {"Guid": [{"id": "imdb://tt2222222"}]}
    item = {"type": "episode", "Guid": [], "grandparentRatingKey": "60"}
    result = extract_imdb_id_for_item(item, mock_client)
    assert result == "tt2222222"


def test_get_parental_guide_cache_hit(db_session):
    cached = ImdbParentalGuide(
        imdb_id="tt0000001",
        data_json=json.dumps(
            {
                "nudity": {
                    "label": "Sex & Nudity",
                    "severity": "None",
                    "descriptions": [],
                }
            }
        ),
        fetched_at=datetime.utcnow(),
    )
    db_session.add(cached)
    db_session.flush()

    result = get_parental_guide("tt0000001", db_session)
    assert result is not None
    assert result["nudity"]["severity"] == "None"


@patch("app.imdb_service._fetch_parental_guide")
def test_get_parental_guide_cache_expired(mock_fetch, db_session):
    cached = ImdbParentalGuide(
        imdb_id="tt0000002",
        data_json=json.dumps(
            {"nudity": {"label": "Sex & Nudity", "severity": "Old", "descriptions": []}}
        ),
        fetched_at=datetime.utcnow() - timedelta(days=60),
    )
    db_session.add(cached)
    db_session.flush()

    mock_fetch.return_value = {
        "nudity": {"label": "Sex & Nudity", "severity": "Updated", "descriptions": []}
    }
    result = get_parental_guide("tt0000002", db_session)
    assert result["nudity"]["severity"] == "Updated"
    mock_fetch.assert_called_once_with("tt0000002")


@patch("app.imdb_service._fetch_parental_guide")
def test_get_parental_guide_fresh_fetch(mock_fetch, db_session):
    mock_fetch.return_value = {
        "nudity": {
            "label": "Sex & Nudity",
            "severity": "Mild",
            "descriptions": ["Brief scene"],
        }
    }
    result = get_parental_guide("tt0000003", db_session)
    assert result is not None
    assert result["nudity"]["severity"] == "Mild"
    # Verify it was cached
    cached = db_session.get(ImdbParentalGuide, "tt0000003")
    assert cached is not None
