from __future__ import annotations

import os

# Set test environment BEFORE any app imports
os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ["WORKER_ENABLED"] = "false"
os.environ.setdefault("PLEX_ADMIN_TOKEN", "test-token")
os.environ.setdefault("PLEX_SERVER_URL", "http://localhost:32400")
os.environ.setdefault("ALLOWED_MEDIA_DIRS", "/mnt/media")
os.environ.setdefault("BASE_URL", "http://localhost:8765")

import secrets
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from app import app_settings
from app.database import Base
from app.deps import get_db
from app.models import (
    User,
    UserSession,
)


@pytest.fixture(scope="session")
def db_engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def db_session(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    # Seed app_settings defaults
    app_settings.seed_defaults(session)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


def _make_session_local_factory(session):
    """Return a callable that mimics SessionLocal() but returns the test session."""

    class _FakeSessionLocal:
        def __init__(self):
            pass

        def __call__(self):
            return session

        def __enter__(self):
            return session

        def __exit__(self, *args):
            pass

    return _FakeSessionLocal()


@pytest.fixture
def client(db_session):
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    fake_sl = _make_session_local_factory(db_session)

    with (
        patch("app.database.init_db"),
        patch("app.database.SessionLocal", fake_sl),
    ):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    app.dependency_overrides.clear()


# ── User fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def admin_user(db_session):
    from app.auth.password import hash_password

    user = User(
        username="admin",
        email="admin@test.com",
        auth_method="local",
        password_hash=hash_password("adminpass123"),
        is_admin=True,
        is_approved=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def regular_user(db_session):
    from app.auth.password import hash_password

    user = User(
        username="user1",
        email="user1@test.com",
        auth_method="local",
        password_hash=hash_password("userpass123"),
        is_admin=False,
        is_approved=True,
    )
    db_session.add(user)
    db_session.flush()
    return user


@pytest.fixture
def unapproved_user(db_session):
    user = User(
        username="pending_user",
        email="pending@test.com",
        auth_method="plex",
        plex_id="99999",
        is_admin=False,
        is_approved=False,
    )
    db_session.add(user)
    db_session.flush()
    return user


# ── Authenticated client helpers ───────────────────────────────────────────


def _create_session_for_user(db_session: Session, user: User) -> UserSession:
    token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    session = UserSession(
        token=token,
        user_id=user.id,
        csrf_token=csrf_token,
        expires_at=datetime.utcnow() + timedelta(days=30),
    )
    db_session.add(session)
    db_session.flush()
    return session


@pytest.fixture
def auth_client(db_session, client):
    """Factory fixture: returns (TestClient, csrf_token) for a given user."""

    def _make(user: User):
        session = _create_session_for_user(db_session, user)
        from app.config import settings

        client.cookies.set(settings.SESSION_COOKIE_NAME, session.token)
        return client, session.csrf_token

    return _make


@pytest.fixture
def admin_client(auth_client, admin_user):
    return auth_client(admin_user)


@pytest.fixture
def user_client(auth_client, regular_user):
    return auth_client(regular_user)
