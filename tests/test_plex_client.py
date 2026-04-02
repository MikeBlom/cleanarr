from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.plex.client import PlexClient, PlexError


def _mock_response(json_data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    return resp


@patch("httpx.get")
def test_libraries_returns_directories(mock_get):
    mock_get.return_value = _mock_response(
        {
            "MediaContainer": {
                "Directory": [
                    {"title": "Movies", "key": "1", "type": "movie"},
                    {"title": "TV Shows", "key": "2", "type": "show"},
                ]
            }
        }
    )
    client = PlexClient()
    libs = client.libraries()
    assert len(libs) == 2
    assert libs[0]["title"] == "Movies"


@patch("httpx.get")
def test_get_item_returns_metadata(mock_get):
    mock_get.return_value = _mock_response(
        {"MediaContainer": {"Metadata": [{"title": "Test Movie", "type": "movie"}]}}
    )
    client = PlexClient()
    item = client.get_item("/library/metadata/123")
    assert item["title"] == "Test Movie"


@patch("httpx.get")
def test_get_item_not_found_raises(mock_get):
    mock_get.return_value = _mock_response({"MediaContainer": {"Metadata": []}})
    client = PlexClient()
    with pytest.raises(PlexError, match="No metadata found"):
        client.get_item("/library/metadata/999")


@patch("httpx.get")
def test_get_leaves_returns_episodes(mock_get):
    mock_get.return_value = _mock_response(
        {
            "MediaContainer": {
                "Metadata": [
                    {"title": "Episode 1", "type": "episode"},
                    {"title": "Episode 2", "type": "episode"},
                ]
            }
        }
    )
    client = PlexClient()
    leaves = client.get_leaves("/library/metadata/100")
    assert len(leaves) == 2


@patch("httpx.get")
def test_get_children_returns_seasons(mock_get):
    mock_get.return_value = _mock_response(
        {"MediaContainer": {"Metadata": [{"title": "Season 1"}, {"title": "Season 2"}]}}
    )
    client = PlexClient()
    children = client.get_children("/library/metadata/50")
    assert len(children) == 2


def test_resolve_file_path_applies_prefix_mapping(db_session):
    from app import app_settings

    app_settings.put(db_session, "plex_path_prefix_from", "/data")
    app_settings.put(db_session, "plex_path_prefix_to", "/mnt/media")
    app_settings.put(db_session, "allowed_media_dirs", "/mnt/media")

    client = PlexClient(db=db_session)
    item = {"Media": [{"Part": [{"file": "/data/movies/test.mkv"}]}]}
    path = client.resolve_file_path(item, db=db_session)
    assert path.startswith("/mnt/media")


def test_resolve_file_path_rejects_outside_allowed(db_session):
    from app import app_settings

    app_settings.put(db_session, "allowed_media_dirs", "/mnt/media")

    client = PlexClient(db=db_session)
    item = {"Media": [{"Part": [{"file": "/etc/passwd"}]}]}
    with pytest.raises(PlexError, match="not in allowed media dirs"):
        client.resolve_file_path(item, db=db_session)


def test_get_audio_streams_filters_type_2():
    client = PlexClient()
    item = {
        "Media": [
            {
                "Part": [
                    {
                        "Stream": [
                            {"streamType": 1, "codec": "h264"},  # video
                            {
                                "streamType": 2,
                                "codec": "aac",
                                "language": "English",
                            },  # audio
                            {"streamType": 3, "codec": "srt"},  # subtitle
                            {
                                "streamType": 2,
                                "codec": "dts",
                                "language": "Spanish",
                            },  # audio
                        ]
                    }
                ]
            }
        ]
    }
    streams = client.get_audio_streams(item)
    assert len(streams) == 2
    assert all(s["streamType"] == 2 for s in streams)


@patch("httpx.get")
def test_global_search_returns_hubs(mock_get):
    mock_get.return_value = _mock_response(
        {
            "MediaContainer": {
                "Hub": [
                    {"title": "Movies", "Metadata": [{"title": "Result 1"}]},
                ]
            }
        }
    )
    client = PlexClient()
    hubs = client.global_search("test query")
    assert len(hubs) == 1


@patch("httpx.get")
def test_refresh_section(mock_get):
    mock_get.return_value = _mock_response({})
    client = PlexClient()
    client.refresh_section("1")
    mock_get.assert_called_once()
