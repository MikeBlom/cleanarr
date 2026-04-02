from __future__ import annotations


from app import app_settings
from app.models import AppSetting


def test_seed_defaults_populates_all_keys(db_session):
    existing = {r.key for r in db_session.query(AppSetting.key).all()}
    for key in app_settings._DEFAULTS:
        assert key in existing, f"Missing default key: {key}"


def test_get_returns_stored_value(db_session):
    app_settings.put(db_session, "plex_server_url", "http://custom:32400")
    assert app_settings.get(db_session, "plex_server_url") == "http://custom:32400"


def test_get_returns_default_when_missing(db_session):
    db_session.query(AppSetting).filter_by(key="plex_server_url").delete()
    db_session.flush()
    assert app_settings.get(db_session, "plex_server_url") == "http://localhost:32400"


def test_put_creates_new_key(db_session):
    app_settings.put(db_session, "brand_new_key", "hello")
    assert app_settings.get(db_session, "brand_new_key") == "hello"


def test_put_updates_existing_key(db_session):
    app_settings.put(db_session, "profanity_padding_ms", "300")
    assert app_settings.get(db_session, "profanity_padding_ms") == "300"


def test_get_json_parses_json(db_session):
    words = app_settings.get_json(db_session, "profanity_words")
    assert isinstance(words, list)
    assert "fuck" in words


def test_all_settings_merges_defaults(db_session):
    result = app_settings.all_settings(db_session)
    assert "plex_server_url" in result
    assert "profanity_words" in result


def test_descriptions_returns_all_keys():
    descs = app_settings.descriptions()
    for key in app_settings._DEFAULTS:
        assert key in descs
        assert len(descs[key]) > 0
