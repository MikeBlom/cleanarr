from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from app.config import settings
from app.models import Invitation, User


# ── Setup ───────────────────────────────────────────────────────────────────


def test_setup_page_when_no_users(client):
    resp = client.get("/setup", follow_redirects=False)
    assert resp.status_code == 200
    assert b"setup" in resp.content.lower() or b"Create" in resp.content


def test_setup_page_redirects_when_users_exist(client, admin_user):
    resp = client.get("/setup", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["location"]


def test_setup_create_admin_user(client, db_session):
    resp = client.post(
        "/setup",
        data={
            "username": "newadmin",
            "password": "password123",
            "password_confirm": "password123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    user = db_session.query(User).filter_by(username="newadmin").first()
    assert user is not None
    assert user.is_admin is True
    assert user.is_approved is True


def test_setup_create_password_mismatch(client):
    resp = client.post(
        "/setup",
        data={
            "username": "newadmin",
            "password": "password123",
            "password_confirm": "different",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert b"do not match" in resp.content


def test_setup_create_short_password(client):
    resp = client.post(
        "/setup",
        data={
            "username": "newadmin",
            "password": "short",
            "password_confirm": "short",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert b"at least 8" in resp.content


def test_setup_blocked_when_users_exist(client, admin_user):
    resp = client.post(
        "/setup",
        data={
            "username": "hacker",
            "password": "password123",
            "password_confirm": "password123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "/login" in resp.headers["location"]


# ── Login ───────────────────────────────────────────────────────────────────


def test_local_login_success(client, admin_user):
    resp = client.post(
        "/auth/local",
        data={
            "username": "admin",
            "password": "adminpass123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"
    assert settings.SESSION_COOKIE_NAME in resp.cookies


def test_local_login_wrong_password(client, admin_user):
    resp = client.post(
        "/auth/local",
        data={
            "username": "admin",
            "password": "wrongpassword",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=invalid" in resp.headers["location"]


def test_local_login_nonexistent_user(client, admin_user):
    resp = client.post(
        "/auth/local",
        data={
            "username": "nobody",
            "password": "whatever123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert "error=invalid" in resp.headers["location"]


def test_login_page_when_no_users_redirects_setup(client):
    resp = client.get("/login", follow_redirects=False)
    assert resp.status_code == 302
    assert "/setup" in resp.headers["location"]


def test_login_page_when_authenticated_redirects_home(admin_client):
    c, _ = admin_client
    resp = c.get("/login", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/"


# ── Logout ──────────────────────────────────────────────────────────────────


def test_logout_clears_session(admin_client, db_session):
    c, _ = admin_client
    resp = c.post("/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["location"]


# ── Plex OAuth ──────────────────────────────────────────────────────────────


@patch("app.routes.auth.create_pin", return_value=(12345, "PINCODE"))
@patch("app.routes.auth.plex_auth_url", return_value="https://plex.tv/auth")
def test_plex_start_redirects(mock_url, mock_pin, client, admin_user):
    resp = client.post("/auth/plex/start", follow_redirects=False)
    assert resp.status_code == 302
    assert "plex.tv" in resp.headers["location"]
    assert "plex_pin_id" in resp.cookies


@patch("app.routes.auth.poll_pin", return_value="fake-auth-token")
@patch(
    "app.routes.auth.fetch_user_info",
    return_value={
        "id": 11111,
        "username": "plexadmin",
        "email": "pa@test.com",
    },
)
def test_plex_callback_new_admin_user(mock_info, mock_poll, client, db_session):
    # Create an initial user so setup redirect doesn't trigger
    db_session.add(User(username="seed", is_approved=True))
    db_session.flush()

    with patch.object(settings, "PLEX_ADMIN_PLEX_IDS", "11111"):
        client.cookies.set("plex_pin_id", "12345")
        resp = client.get("/auth/plex/callback", follow_redirects=False)
    assert resp.status_code == 302
    user = db_session.query(User).filter_by(plex_id="11111").first()
    assert user is not None
    assert user.is_admin is True
    assert user.is_approved is True


@patch("app.routes.auth.poll_pin", return_value=None)
def test_plex_callback_timeout(mock_poll, client, admin_user):
    client.cookies.set("plex_pin_id", "12345")
    resp = client.get("/auth/plex/callback", follow_redirects=False)
    assert resp.status_code == 302
    assert "error=timeout" in resp.headers["location"]


# ── Invitations ─────────────────────────────────────────────────────────────


def test_invite_accept_local_creates_user(client, db_session, admin_user):
    inv = Invitation(
        email="invited@test.com",
        token="inv_test_token",
        invited_by=admin_user.id,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db_session.add(inv)
    db_session.flush()

    resp = client.post(
        "/invite/inv_test_token/local",
        data={
            "username": "inviteduser",
            "password": "password123",
            "password_confirm": "password123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    user = db_session.query(User).filter_by(username="inviteduser").first()
    assert user is not None
    assert user.is_approved is True


def test_invite_accept_expired_token(client, db_session, admin_user):
    inv = Invitation(
        email="expired@test.com",
        token="expired_token",
        invited_by=admin_user.id,
        expires_at=datetime.utcnow() - timedelta(days=1),
    )
    db_session.add(inv)
    db_session.flush()

    resp = client.get("/invite/expired_token", follow_redirects=False)
    assert resp.status_code == 200
    assert b"invalid" in resp.content.lower() or b"expired" in resp.content.lower()


def test_invite_accept_duplicate_username(client, db_session, admin_user):
    inv = Invitation(
        email="dup@test.com",
        token="dup_token",
        invited_by=admin_user.id,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db_session.add(inv)
    db_session.flush()

    resp = client.post(
        "/invite/dup_token/local",
        data={
            "username": "admin",  # already exists
            "password": "password123",
            "password_confirm": "password123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert b"already taken" in resp.content
