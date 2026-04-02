from __future__ import annotations

from unittest.mock import patch

from app.plex.client import PlexClient, PlexError


@patch.object(
    PlexClient,
    "libraries",
    return_value=[
        {"title": "Movies", "key": "1", "type": "movie"},
        {"title": "TV Shows", "key": "2", "type": "show"},
    ],
)
def test_browse_index_lists_libraries(mock_libs, user_client):
    c, _ = user_client
    resp = c.get("/browse")
    assert resp.status_code == 200
    assert b"Movies" in resp.content


@patch.object(
    PlexClient,
    "library_items",
    return_value={
        "Metadata": [
            {"title": "Test Movie", "type": "movie", "key": "/library/metadata/1"}
        ],
        "totalSize": 1,
        "viewGroup": "movie",
    },
)
def test_browse_section_movie(mock_items, user_client):
    c, _ = user_client
    resp = c.get("/browse/section/1")
    assert resp.status_code == 200


@patch.object(
    PlexClient,
    "library_items",
    return_value={
        "Metadata": [
            {"title": "Test Show", "type": "show", "key": "/library/metadata/2"}
        ],
        "totalSize": 1,
        "viewGroup": "show",
    },
)
def test_browse_section_show(mock_items, user_client):
    c, _ = user_client
    resp = c.get("/browse/section/2")
    assert resp.status_code == 200


@patch.object(
    PlexClient,
    "global_search",
    return_value=[
        {"title": "Movies", "Metadata": [{"title": "Result"}]},
    ],
)
def test_browse_global_search(mock_search, user_client):
    c, _ = user_client
    resp = c.get("/browse/search?q=test")
    assert resp.status_code == 200


@patch.object(PlexClient, "libraries", side_effect=PlexError("Connection refused"))
def test_browse_plex_error(mock_libs, user_client):
    c, _ = user_client
    resp = c.get("/browse")
    # browse_index catches PlexError and renders with error, doesn't raise 502
    assert resp.status_code == 200


@patch.object(PlexClient, "library_items", side_effect=PlexError("Not found"))
def test_browse_section_plex_error_returns_502(mock_items, user_client):
    c, _ = user_client
    resp = c.get("/browse/section/999")
    assert resp.status_code == 502
