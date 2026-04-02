from __future__ import annotations


from app import app_settings
from app.models import (
    ConversionJob,
    ConversionRequest,
    Invitation,
    JobStatus,
    RequestStatus,
    RequestType,
    User,
)


# ── User management ────────────────────────────────────────────────────────


def test_admin_users_page(admin_client, db_session):
    c, _ = admin_client
    resp = c.get("/admin/users")
    assert resp.status_code == 200


def test_approve_user(admin_client, db_session, unapproved_user):
    c, _ = admin_client
    resp = c.post(f"/admin/users/{unapproved_user.id}/approve", follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(unapproved_user)
    assert unapproved_user.is_approved is True


def test_revoke_user(admin_client, db_session, regular_user):
    c, _ = admin_client
    resp = c.post(f"/admin/users/{regular_user.id}/revoke", follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(regular_user)
    assert regular_user.is_approved is False


def test_toggle_admin(admin_client, db_session, regular_user):
    c, _ = admin_client
    resp = c.post(
        f"/admin/users/{regular_user.id}/toggle-admin", follow_redirects=False
    )
    assert resp.status_code == 303
    db_session.refresh(regular_user)
    assert regular_user.is_admin is True


def test_toggle_admin_self_blocked(admin_client, admin_user):
    c, _ = admin_client
    resp = c.post(f"/admin/users/{admin_user.id}/toggle-admin", follow_redirects=False)
    assert resp.status_code == 400


def test_delete_user(admin_client, db_session, regular_user):
    uid = regular_user.id
    c, _ = admin_client
    resp = c.post(f"/admin/users/{uid}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert db_session.query(User).filter_by(id=uid).first() is None


def test_delete_self_blocked(admin_client, admin_user, db_session):
    c, _ = admin_client
    resp = c.post(f"/admin/users/{admin_user.id}/delete", follow_redirects=False)
    assert resp.status_code == 303
    # User should still exist
    assert db_session.query(User).filter_by(id=admin_user.id).first() is not None


def test_create_user_local(admin_client, db_session):
    c, _ = admin_client
    resp = c.post(
        "/admin/users/create",
        data={
            "username": "newlocal",
            "password": "password123",
            "password_confirm": "password123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    u = db_session.query(User).filter_by(username="newlocal").first()
    assert u is not None
    assert u.is_approved is True


def test_create_user_duplicate_username(admin_client, db_session, admin_user):
    c, _ = admin_client
    resp = c.post(
        "/admin/users/create",
        data={
            "username": "admin",
            "password": "password123",
            "password_confirm": "password123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert b"already exists" in resp.content


def test_reset_password(admin_client, db_session, regular_user):
    c, _ = admin_client
    # regular_user is local auth
    resp = c.post(
        f"/admin/users/{regular_user.id}/reset-password",
        data={
            "new_password": "newpassword123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303


# ── Masquerade ──────────────────────────────────────────────────────────────


def test_masquerade_sets_cookie(admin_client, regular_user):
    c, _ = admin_client
    resp = c.post(f"/admin/users/{regular_user.id}/masquerade", follow_redirects=False)
    assert resp.status_code == 303
    assert "cleanarr_masquerade" in resp.cookies


def test_masquerade_self_blocked(admin_client, admin_user):
    c, _ = admin_client
    resp = c.post(f"/admin/users/{admin_user.id}/masquerade", follow_redirects=False)
    assert resp.status_code == 303
    assert "cleanarr_masquerade" not in resp.cookies


def test_stop_masquerade(admin_client):
    c, _ = admin_client
    resp = c.post("/admin/masquerade/stop", follow_redirects=False)
    assert resp.status_code == 303


# ── Invitations ─────────────────────────────────────────────────────────────


def test_invite_user_creates_invitation(admin_client, db_session):
    c, _ = admin_client
    resp = c.post(
        "/admin/users/invite",
        data={
            "email": "invited@example.com",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    inv = db_session.query(Invitation).filter_by(email="invited@example.com").first()
    assert inv is not None


# ── Bulk actions ────────────────────────────────────────────────────────────


def test_bulk_approve(admin_client, db_session, unapproved_user):
    c, _ = admin_client
    resp = c.post(
        "/admin/users/bulk",
        data={
            "action": "approve",
            "user_ids": str(unapproved_user.id),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db_session.refresh(unapproved_user)
    assert unapproved_user.is_approved is True


def test_bulk_delete(admin_client, db_session, regular_user):
    uid = regular_user.id
    c, _ = admin_client
    resp = c.post(
        "/admin/users/bulk",
        data={
            "action": "delete",
            "user_ids": str(uid),
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert db_session.query(User).filter_by(id=uid).first() is None


# ── Settings ────────────────────────────────────────────────────────────────


def test_settings_plex_save(admin_client, db_session):
    c, _ = admin_client
    resp = c.post(
        "/admin/settings/plex",
        data={
            "plex_server_url": "http://custom:32400",
            "plex_admin_token": "new-token",
            "plex_client_id": "custom-id",
            "plex_admin_plex_ids": "12345",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert app_settings.get(db_session, "plex_server_url") == "http://custom:32400"


def test_settings_profanity_save(admin_client, db_session):
    c, _ = admin_client
    resp = c.post(
        "/admin/settings/profanity",
        data={
            "profanity_words": "fuck\nshit\nnewword",
            "profanity_phrases": "oh no",
            "profanity_padding_ms": "300",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert app_settings.get(db_session, "profanity_padding_ms") == "300"


def test_settings_invalid_section(admin_client):
    c, _ = admin_client
    resp = c.get("/admin/settings/invalid", follow_redirects=False)
    assert resp.status_code == 302
    assert "plex" in resp.headers["location"]


# ── Queue management ───────────────────────────────────────────────────────


def _make_admin_job(db_session, admin_user, status=JobStatus.queued):
    req = ConversionRequest(
        user_id=admin_user.id,
        title="AdminReq",
        request_type=RequestType.movie,
        status=RequestStatus.queued,
    )
    db_session.add(req)
    db_session.flush()
    job = ConversionJob(
        request_id=req.id,
        plex_key="1",
        title="AJob",
        input_file="/mnt/media/admin.mkv",
        status=status,
    )
    db_session.add(job)
    db_session.flush()
    return req, job


def test_cancel_job(admin_client, db_session, admin_user):
    _, job = _make_admin_job(db_session, admin_user)
    c, _ = admin_client
    resp = c.post(f"/admin/jobs/{job.id}/cancel", follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(job)
    assert job.status == JobStatus.skipped


def test_admin_retry_job(admin_client, db_session, admin_user):
    _, job = _make_admin_job(db_session, admin_user, status=JobStatus.failed)
    c, _ = admin_client
    resp = c.post(f"/admin/jobs/{job.id}/retry", follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(job)
    assert job.status == JobStatus.queued


def test_admin_delete_job(admin_client, db_session, admin_user):
    _, job = _make_admin_job(db_session, admin_user, status=JobStatus.completed)
    jid = job.id
    c, _ = admin_client
    resp = c.post(f"/admin/jobs/{jid}/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert db_session.query(ConversionJob).filter_by(id=jid).first() is None


def test_admin_delete_running_job_blocked(admin_client, db_session, admin_user):
    _, job = _make_admin_job(db_session, admin_user, status=JobStatus.running)
    c, _ = admin_client
    resp = c.post(f"/admin/jobs/{job.id}/delete", follow_redirects=False)
    assert resp.status_code == 303  # Redirects with flash error
    assert db_session.query(ConversionJob).filter_by(id=job.id).first() is not None


# ── Non-admin access ───────────────────────────────────────────────────────


def test_admin_routes_reject_non_admin(user_client):
    c, _ = user_client
    routes = [
        ("GET", "/admin/users"),
        ("POST", "/admin/users/1/approve"),
        ("POST", "/admin/users/1/delete"),
        ("GET", "/admin/settings/plex"),
        ("POST", "/admin/settings/plex"),
    ]
    for method, path in routes:
        if method == "GET":
            resp = c.get(path, follow_redirects=False)
        else:
            resp = c.post(path, data={}, follow_redirects=False)
        assert resp.status_code in (302, 403), (
            f"{method} {path} returned {resp.status_code}"
        )
