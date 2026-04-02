from __future__ import annotations

from app.models import (
    ConversionJob,
    ConversionRequest,
    JobStatus,
    RequestStatus,
    RequestType,
)


def _create_job(db_session, user, status=JobStatus.queued, priority=0):
    req = ConversionRequest(
        user_id=user.id,
        title="Test",
        request_type=RequestType.movie,
        status=RequestStatus.queued,
    )
    db_session.add(req)
    db_session.flush()
    job = ConversionJob(
        request_id=req.id,
        plex_key="1",
        title="Job",
        input_file="/mnt/media/test.mkv",
        status=status,
        priority=priority,
    )
    db_session.add(job)
    db_session.flush()
    return req, job


# ── Detail ──────────────────────────────────────────────────────────────────


def test_job_detail_owner_can_view(user_client, db_session, regular_user):
    _, job = _create_job(db_session, regular_user)
    c, _ = user_client
    resp = c.get(f"/jobs/{job.id}")
    assert resp.status_code == 200


def test_job_detail_other_user_forbidden(user_client, db_session, admin_user):
    _, job = _create_job(db_session, admin_user)
    c, _ = user_client
    resp = c.get(f"/jobs/{job.id}")
    assert resp.status_code == 403


def test_job_detail_admin_can_view_any(admin_client, db_session, regular_user):
    _, job = _create_job(db_session, regular_user)
    c, _ = admin_client
    resp = c.get(f"/jobs/{job.id}")
    assert resp.status_code == 200


# ── Retry ───────────────────────────────────────────────────────────────────


def test_retry_failed_job(user_client, db_session, regular_user):
    _, job = _create_job(db_session, regular_user, status=JobStatus.failed)
    c, _ = user_client
    resp = c.post(f"/jobs/{job.id}/retry", follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(job)
    assert job.status == JobStatus.queued


def test_retry_completed_job_returns_400(user_client, db_session, regular_user):
    _, job = _create_job(db_session, regular_user, status=JobStatus.completed)
    c, _ = user_client
    resp = c.post(f"/jobs/{job.id}/retry", follow_redirects=False)
    assert resp.status_code == 400


# ── Progress / Log ──────────────────────────────────────────────────────────


def test_job_progress_returns_html(user_client, db_session, regular_user):
    _, job = _create_job(db_session, regular_user)
    c, _ = user_client
    resp = c.get(f"/jobs/{job.id}/progress")
    assert resp.status_code == 200


def test_job_log_returns_html(user_client, db_session, regular_user):
    _, job = _create_job(db_session, regular_user)
    c, _ = user_client
    resp = c.get(f"/jobs/{job.id}/log")
    assert resp.status_code == 200
    assert b"<pre" in resp.content


# ── Reorder ─────────────────────────────────────────────────────────────────


def test_move_job_up(admin_client, db_session, admin_user):
    _, job1 = _create_job(db_session, admin_user, priority=0)
    req2 = ConversionRequest(
        user_id=admin_user.id,
        title="Test2",
        request_type=RequestType.movie,
        status=RequestStatus.queued,
    )
    db_session.add(req2)
    db_session.flush()
    job2 = ConversionJob(
        request_id=req2.id,
        plex_key="2",
        title="Job2",
        input_file="/mnt/media/test2.mkv",
        status=JobStatus.queued,
        priority=10,
    )
    db_session.add(job2)
    db_session.flush()

    c, _ = admin_client
    resp = c.post(f"/jobs/{job2.id}/move-up", follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(job1)
    db_session.refresh(job2)
    # job2 should now have lower priority than job1
    assert job2.priority < job1.priority


def test_move_job_at_top_stays(admin_client, db_session, admin_user):
    _, job = _create_job(db_session, admin_user, priority=0)
    c, _ = admin_client
    resp = c.post(f"/jobs/{job.id}/move-up", follow_redirects=False)
    assert resp.status_code == 303
    db_session.refresh(job)
    assert job.priority == 0  # unchanged
