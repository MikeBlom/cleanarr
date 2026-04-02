from __future__ import annotations

from unittest.mock import patch

from app.models import (
    ConversionJob,
    ConversionRequest,
    JobStatus,
    RequestStatus,
    RequestType,
)
from app.plex.client import PlexClient


def _make_plex_item(key="123", title="Test Movie", file_path="/mnt/media/movie.mkv"):
    return {
        "key": f"/library/metadata/{key}",
        "title": title,
        "type": "movie",
        "Media": [{"Part": [{"file": file_path}]}],
    }


# ── Submit ──────────────────────────────────────────────────────────────────


@patch.object(PlexClient, "resolve_file_path", return_value="/mnt/media/movie.mkv")
@patch.object(PlexClient, "get_item", return_value=_make_plex_item())
def test_submit_request_movie(mock_get, mock_resolve, user_client, db_session):
    c, csrf = user_client
    resp = c.post(
        "/request",
        data={
            "plex_key": "/library/metadata/123",
            "title": "Test Movie",
            "request_type": "movie",
            "filter_profanity": "on",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    req = db_session.query(ConversionRequest).first()
    assert req is not None
    assert req.filter_profanity is True
    assert len(req.jobs) == 1
    assert req.jobs[0].status == JobStatus.queued


@patch.object(
    PlexClient,
    "resolve_file_path",
    side_effect=lambda item, db=None: item["Media"][0]["Part"][0]["file"],
)
@patch.object(
    PlexClient,
    "get_leaves",
    return_value=[
        _make_plex_item("201", "Ep 1", "/mnt/media/ep1.mkv"),
        _make_plex_item("202", "Ep 2", "/mnt/media/ep2.mkv"),
    ],
)
@patch.object(
    PlexClient,
    "get_item",
    return_value={
        "key": "/library/metadata/200",
        "title": "Season 1",
        "type": "season",
    },
)
def test_submit_request_season_resolves_episodes(
    mock_get, mock_leaves, mock_resolve, user_client, db_session
):
    c, csrf = user_client
    resp = c.post(
        "/request",
        data={
            "plex_key": "/library/metadata/200",
            "title": "Season 1",
            "request_type": "season",
            "filter_profanity": "on",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    req = db_session.query(ConversionRequest).first()
    assert len(req.jobs) == 2


def test_submit_request_no_filter_returns_400(user_client):
    c, csrf = user_client
    resp = c.post(
        "/request",
        data={
            "plex_key": "/library/metadata/123",
            "title": "Test",
            "request_type": "movie",
            # No filter selected
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400


# ── List ────────────────────────────────────────────────────────────────────


def test_list_requests_user_sees_own(user_client, db_session, regular_user, admin_user):
    req1 = ConversionRequest(
        user_id=regular_user.id,
        title="User's",
        request_type=RequestType.movie,
        status=RequestStatus.queued,
    )
    req2 = ConversionRequest(
        user_id=admin_user.id,
        title="Admin's",
        request_type=RequestType.movie,
        status=RequestStatus.queued,
    )
    db_session.add_all([req1, req2])
    db_session.flush()

    c, _ = user_client
    resp = c.get("/requests")
    assert resp.status_code == 200
    assert b"User&#39;s" in resp.content or b"User's" in resp.content
    assert b"Admin&#39;s" not in resp.content and b"Admin's" not in resp.content


def test_list_requests_admin_sees_all(
    admin_client, db_session, regular_user, admin_user
):
    req1 = ConversionRequest(
        user_id=regular_user.id,
        title="UserReq",
        request_type=RequestType.movie,
        status=RequestStatus.queued,
    )
    req2 = ConversionRequest(
        user_id=admin_user.id,
        title="AdminReq",
        request_type=RequestType.movie,
        status=RequestStatus.queued,
    )
    db_session.add_all([req1, req2])
    db_session.flush()

    c, _ = admin_client
    resp = c.get("/requests")
    assert resp.status_code == 200
    assert b"UserReq" in resp.content
    assert b"AdminReq" in resp.content


# ── Detail ──────────────────────────────────────────────────────────────────


def test_request_detail_owner_can_view(user_client, db_session, regular_user):
    req = ConversionRequest(
        user_id=regular_user.id,
        title="Mine",
        request_type=RequestType.movie,
        status=RequestStatus.queued,
    )
    db_session.add(req)
    db_session.flush()

    c, _ = user_client
    resp = c.get(f"/requests/{req.id}")
    assert resp.status_code == 200


def test_request_detail_other_user_forbidden(user_client, db_session, admin_user):
    req = ConversionRequest(
        user_id=admin_user.id,
        title="Not mine",
        request_type=RequestType.movie,
        status=RequestStatus.queued,
    )
    db_session.add(req)
    db_session.flush()

    c, _ = user_client
    resp = c.get(f"/requests/{req.id}")
    assert resp.status_code == 403


def test_request_detail_admin_can_view_any(admin_client, db_session, regular_user):
    req = ConversionRequest(
        user_id=regular_user.id,
        title="Other",
        request_type=RequestType.movie,
        status=RequestStatus.queued,
    )
    db_session.add(req)
    db_session.flush()

    c, _ = admin_client
    resp = c.get(f"/requests/{req.id}")
    assert resp.status_code == 200


# ── Delete ──────────────────────────────────────────────────────────────────


def test_delete_request(user_client, db_session, regular_user):
    req = ConversionRequest(
        user_id=regular_user.id,
        title="Delete Me",
        request_type=RequestType.movie,
        status=RequestStatus.queued,
    )
    db_session.add(req)
    db_session.flush()
    job = ConversionJob(
        request_id=req.id,
        plex_key="1",
        title="J",
        input_file="/mnt/media/x.mkv",
        status=JobStatus.completed,
    )
    db_session.add(job)
    db_session.flush()
    req_id = req.id

    c, _ = user_client
    resp = c.post(f"/requests/{req_id}/delete", data={}, follow_redirects=False)
    assert resp.status_code == 303
    assert db_session.query(ConversionRequest).filter_by(id=req_id).first() is None


def test_delete_request_running_job_blocked(user_client, db_session, regular_user):
    req = ConversionRequest(
        user_id=regular_user.id,
        title="Running",
        request_type=RequestType.movie,
        status=RequestStatus.queued,
    )
    db_session.add(req)
    db_session.flush()
    job = ConversionJob(
        request_id=req.id,
        plex_key="1",
        title="J",
        input_file="/mnt/media/x.mkv",
        status=JobStatus.running,
    )
    db_session.add(job)
    db_session.flush()

    c, _ = user_client
    resp = c.post(f"/requests/{req.id}/delete", data={}, follow_redirects=False)
    assert resp.status_code == 400


def test_delete_request_wrong_user_forbidden(user_client, db_session, admin_user):
    req = ConversionRequest(
        user_id=admin_user.id,
        title="Not mine",
        request_type=RequestType.movie,
        status=RequestStatus.queued,
    )
    db_session.add(req)
    db_session.flush()

    c, _ = user_client
    resp = c.post(f"/requests/{req.id}/delete", data={}, follow_redirects=False)
    assert resp.status_code == 403


# ── Edit ────────────────────────────────────────────────────────────────────


def test_edit_request_updates_filters(user_client, db_session, regular_user):
    req = ConversionRequest(
        user_id=regular_user.id,
        title="Edit Me",
        request_type=RequestType.movie,
        filter_profanity=True,
        filter_nudity=False,
        status=RequestStatus.queued,
    )
    db_session.add(req)
    db_session.flush()

    c, _ = user_client
    resp = c.post(
        f"/requests/{req.id}/edit",
        data={
            "filter_profanity": "on",
            "filter_nudity": "on",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    db_session.refresh(req)
    assert req.filter_nudity is True


def test_edit_request_no_filter_returns_400(user_client, db_session, regular_user):
    req = ConversionRequest(
        user_id=regular_user.id,
        title="Edit Me",
        request_type=RequestType.movie,
        filter_profanity=True,
        status=RequestStatus.queued,
    )
    db_session.add(req)
    db_session.flush()

    c, _ = user_client
    resp = c.post(f"/requests/{req.id}/edit", data={}, follow_redirects=False)
    assert resp.status_code == 400
