from __future__ import annotations

from app.models import (
    ConversionJob,
    ConversionRequest,
    JobStatus,
    RequestStatus,
    RequestType,
)


def test_upload_page_no_active(user_client):
    c, _ = user_client
    resp = c.get("/upload")
    assert resp.status_code == 200


def test_upload_page_active_redirects(user_client, db_session, regular_user):
    req = ConversionRequest(
        user_id=regular_user.id,
        title="Active Upload",
        request_type=RequestType.movie,
        source="upload",
        status=RequestStatus.queued,
    )
    db_session.add(req)
    db_session.flush()

    c, _ = user_client
    resp = c.get("/upload", follow_redirects=False)
    assert resp.status_code == 302
    assert f"/requests/{req.id}" in resp.headers["location"]


def test_download_other_user_forbidden(user_client, db_session, admin_user):
    req = ConversionRequest(
        user_id=admin_user.id,
        title="Not mine",
        request_type=RequestType.movie,
        source="upload",
        status=RequestStatus.complete,
    )
    db_session.add(req)
    db_session.flush()
    job = ConversionJob(
        request_id=req.id,
        plex_key="upload",
        title="Job",
        input_file="/data/uploads/x.mkv",
        output_file="/data/uploads/x_clean.mkv",
        status=JobStatus.completed,
    )
    db_session.add(job)
    db_session.flush()

    c, _ = user_client
    resp = c.get(f"/requests/{req.id}/download/{job.id}")
    assert resp.status_code == 403


def test_download_non_upload_request_returns_400(user_client, db_session, regular_user):
    req = ConversionRequest(
        user_id=regular_user.id,
        title="Plex req",
        request_type=RequestType.movie,
        source="plex",
        status=RequestStatus.complete,
    )
    db_session.add(req)
    db_session.flush()
    job = ConversionJob(
        request_id=req.id,
        plex_key="1",
        title="Job",
        input_file="/mnt/media/movie.mkv",
        output_file="/mnt/media/movie_clean.mkv",
        status=JobStatus.completed,
    )
    db_session.add(job)
    db_session.flush()

    c, _ = user_client
    resp = c.get(f"/requests/{req.id}/download/{job.id}")
    assert resp.status_code == 400
