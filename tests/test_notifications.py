from __future__ import annotations

import json
from unittest.mock import patch

from app import app_settings
from app.models import (
    ConversionJob,
    ConversionRequest,
    JobStatus,
    Notification,
    RequestStatus,
    RequestType,
    User,
)
from app.notifications import (
    _build_message,
    notify_request_status_change,
)


def _make_request_with_jobs(db_session, user, job_statuses):
    req = ConversionRequest(
        user_id=user.id,
        title="Test Request",
        request_type=RequestType.movie,
        status=RequestStatus.queued,
    )
    db_session.add(req)
    db_session.flush()
    for i, st in enumerate(job_statuses):
        job = ConversionJob(
            request_id=req.id,
            plex_key=f"key{i}",
            title=f"Job {i}",
            input_file=f"/mnt/media/file{i}.mkv",
            status=st,
        )
        db_session.add(job)
    db_session.flush()
    return req


def test_notify_on_complete(db_session, regular_user):
    regular_user.notify_inapp = True
    db_session.flush()
    req = _make_request_with_jobs(db_session, regular_user, [JobStatus.completed])
    notify_request_status_change(db_session, req, RequestStatus.complete)
    notifs = db_session.query(Notification).filter_by(user_id=regular_user.id).all()
    assert len(notifs) == 1
    assert "completed" in notifs[0].title


def test_notify_on_failed(db_session, regular_user):
    regular_user.notify_inapp = True
    db_session.flush()
    req = _make_request_with_jobs(db_session, regular_user, [JobStatus.failed])
    notify_request_status_change(db_session, req, RequestStatus.failed)
    notifs = db_session.query(Notification).filter_by(user_id=regular_user.id).all()
    assert len(notifs) == 1
    assert "failed" in notifs[0].title


def test_no_notify_on_queued(db_session, regular_user):
    regular_user.notify_inapp = True
    db_session.flush()
    req = _make_request_with_jobs(db_session, regular_user, [JobStatus.queued])
    notify_request_status_change(db_session, req, RequestStatus.queued)
    notifs = db_session.query(Notification).filter_by(user_id=regular_user.id).all()
    assert len(notifs) == 0


def test_no_notify_when_disabled(db_session, regular_user):
    regular_user.notify_inapp = True
    db_session.flush()
    app_settings.put(db_session, "notification_on_complete", "false")
    req = _make_request_with_jobs(db_session, regular_user, [JobStatus.completed])
    notify_request_status_change(db_session, req, RequestStatus.complete)
    notifs = db_session.query(Notification).filter_by(user_id=regular_user.id).all()
    assert len(notifs) == 0


def test_no_notify_when_user_opted_out(db_session, regular_user):
    regular_user.notify_inapp = False
    db_session.flush()
    req = _make_request_with_jobs(db_session, regular_user, [JobStatus.completed])
    notify_request_status_change(db_session, req, RequestStatus.complete)
    notifs = db_session.query(Notification).filter_by(user_id=regular_user.id).all()
    assert len(notifs) == 0


@patch("app.notifications.send_notification_email", return_value=True)
def test_email_sent_when_opted_in(mock_send, db_session, regular_user):
    regular_user.notify_email = True
    regular_user.notify_inapp = False
    db_session.flush()
    req = _make_request_with_jobs(db_session, regular_user, [JobStatus.completed])
    notify_request_status_change(db_session, req, RequestStatus.complete)
    mock_send.assert_called_once()
    assert regular_user.email in mock_send.call_args[0]


@patch("app.notifications.send_notification_email", return_value=True)
def test_email_not_sent_when_no_email(mock_send, db_session):
    user = User(
        username="no_email_user",
        email=None,
        is_approved=True,
        notify_email=True,
        notify_inapp=False,
    )
    db_session.add(user)
    db_session.flush()
    req = _make_request_with_jobs(db_session, user, [JobStatus.completed])
    notify_request_status_change(db_session, req, RequestStatus.complete)
    mock_send.assert_not_called()


@patch("app.notifications.urlopen")
def test_webhook_discord_format(mock_urlopen, db_session, regular_user):
    regular_user.notify_webhook = True
    regular_user.webhook_url = "https://discord.com/api/webhooks/test"
    regular_user.notify_inapp = False
    db_session.flush()
    req = _make_request_with_jobs(db_session, regular_user, [JobStatus.completed])
    notify_request_status_change(db_session, req, RequestStatus.complete)
    mock_urlopen.assert_called()
    call_args = mock_urlopen.call_args[0][0]
    payload = json.loads(call_args.data)
    assert "content" in payload


@patch("app.notifications.urlopen")
def test_webhook_generic_format(mock_urlopen, db_session, regular_user):
    regular_user.notify_webhook = True
    regular_user.webhook_url = "https://example.com/hook"
    regular_user.notify_inapp = False
    db_session.flush()
    app_settings.put(db_session, "notification_webhook_format", "generic")
    req = _make_request_with_jobs(db_session, regular_user, [JobStatus.completed])
    notify_request_status_change(db_session, req, RequestStatus.complete)
    mock_urlopen.assert_called()
    call_args = mock_urlopen.call_args[0][0]
    payload = json.loads(call_args.data)
    assert "title" in payload
    assert "message" in payload


@patch("app.notifications.urlopen")
def test_global_webhook_fires_regardless_of_user_pref(
    mock_urlopen, db_session, regular_user
):
    regular_user.notify_webhook = False
    regular_user.notify_inapp = False
    db_session.flush()
    app_settings.put(db_session, "notification_webhook_url", "https://global.hook/test")
    req = _make_request_with_jobs(db_session, regular_user, [JobStatus.completed])
    notify_request_status_change(db_session, req, RequestStatus.complete)
    mock_urlopen.assert_called_once()


def test_build_message_complete():
    req = ConversionRequest(title="My Movie", request_type=RequestType.movie)
    req.jobs = [
        ConversionJob(
            plex_key="1",
            title="J",
            input_file="/f.mkv",
            status=JobStatus.completed,
        )
    ]
    title, msg = _build_message(req, RequestStatus.complete)
    assert "completed" in title
    assert "1/1 succeeded" in msg


def test_build_message_partial():
    req = ConversionRequest(title="My Show", request_type=RequestType.season)
    req.jobs = [
        ConversionJob(
            plex_key="1",
            title="J1",
            input_file="/f1.mkv",
            status=JobStatus.completed,
        ),
        ConversionJob(
            plex_key="2",
            title="J2",
            input_file="/f2.mkv",
            status=JobStatus.failed,
        ),
    ]
    title, msg = _build_message(req, RequestStatus.partially_complete)
    assert "partially" in title
    assert "1 failed" in msg
