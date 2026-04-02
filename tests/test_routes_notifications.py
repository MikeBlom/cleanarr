from __future__ import annotations

from app.models import Notification


def test_count_returns_badge(user_client, db_session, regular_user):
    for i in range(3):
        db_session.add(
            Notification(
                user_id=regular_user.id,
                title=f"Test {i}",
                message="msg",
                is_read=False,
            )
        )
    db_session.flush()

    c, _ = user_client
    resp = c.get("/notifications/count")
    assert resp.status_code == 200
    assert b"3" in resp.content
    assert b"notif-badge" in resp.content


def test_count_empty_when_zero(user_client):
    c, _ = user_client
    resp = c.get("/notifications/count")
    assert resp.status_code == 200
    assert b"notif-badge" not in resp.content


def test_list_shows_notifications(user_client, db_session, regular_user):
    db_session.add(
        Notification(
            user_id=regular_user.id,
            title="Job Done",
            message="Your movie is ready",
        )
    )
    db_session.flush()

    c, _ = user_client
    resp = c.get("/notifications")
    assert resp.status_code == 200
    assert b"Job Done" in resp.content


def test_mark_read(user_client, db_session, regular_user):
    notif = Notification(
        user_id=regular_user.id,
        title="Test",
        message="msg",
        is_read=False,
    )
    db_session.add(notif)
    db_session.flush()

    c, _ = user_client
    resp = c.post(f"/notifications/{notif.id}/read", follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(notif)
    assert notif.is_read is True


def test_mark_all_read(user_client, db_session, regular_user):
    for i in range(3):
        db_session.add(
            Notification(
                user_id=regular_user.id,
                title=f"N{i}",
                message="m",
                is_read=False,
            )
        )
    db_session.flush()

    c, _ = user_client
    resp = c.post("/notifications/read-all", follow_redirects=False)
    assert resp.status_code == 303
    unread = (
        db_session.query(Notification)
        .filter_by(user_id=regular_user.id, is_read=False)
        .count()
    )
    assert unread == 0


def test_preferences_save(user_client, db_session, regular_user):
    c, _ = user_client
    resp = c.post(
        "/notifications/preferences",
        data={
            "notify_email": "true",
            "notify_inapp": "true",
            "webhook_url": "https://hooks.example.com/test",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db_session.refresh(regular_user)
    assert regular_user.notify_email is True
    assert regular_user.notify_webhook is False
    assert regular_user.webhook_url == "https://hooks.example.com/test"


def test_preferences_require_auth(client, admin_user):
    resp = client.get("/notifications/preferences", follow_redirects=False)
    assert resp.status_code == 302
    assert "/login" in resp.headers["location"]
