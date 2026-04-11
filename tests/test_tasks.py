from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from app.models import (
    ConversionJob,
    ConversionRequest,
    JobStatus,
    RequestStatus,
    RequestType,
    SystemTaskRun,
)


# ── Registry tests ─────────────────────────────────────────────────────────


def test_registry_has_sync_plex_paths():
    from app.tasks import TASK_REGISTRY

    assert "sync_plex_paths" in TASK_REGISTRY
    defn = TASK_REGISTRY["sync_plex_paths"]
    assert defn.display_name == "Sync Plex Paths"
    assert defn.icon == "fa-rotate"
    assert callable(defn.func)


def test_register_task_decorator():
    from app.tasks.registry import TASK_REGISTRY, register_task

    @register_task(
        name="_test_task",
        display_name="Test Task",
        description="A test",
        icon="fa-vial",
    )
    def my_task(db, set_progress):
        return "ok"

    assert "_test_task" in TASK_REGISTRY
    assert TASK_REGISTRY["_test_task"].func is my_task

    # Cleanup
    del TASK_REGISTRY["_test_task"]


# ── Runner tests ───────────────────────────────────────────────────────────


def test_trigger_task_creates_run(db_session):
    """trigger_task creates a SystemTaskRun record with status=running."""
    from app.tasks.registry import TASK_REGISTRY, TaskDefinition
    from app.tasks.runner import _running_tasks, trigger_task

    barrier = threading.Event()

    def _blocking_task(db, set_progress):
        barrier.wait(timeout=5)
        return "done"

    TASK_REGISTRY["_test_create"] = TaskDefinition(
        name="_test_create",
        display_name="Create Test",
        description="test",
        icon="fa-vial",
        func=_blocking_task,
    )

    try:
        with patch("app.tasks.runner.SessionLocal", return_value=db_session):
            run = trigger_task("_test_create", "testuser")
            assert run is not None
            assert run.task_name == "_test_create"
            assert run.status == "running"
            assert run.triggered_by == "testuser"
            assert run.started_at is not None
    finally:
        barrier.set()
        time.sleep(0.5)
        del TASK_REGISTRY["_test_create"]
        _running_tasks.discard("_test_create")


def test_trigger_task_prevents_duplicate(db_session):
    from app.tasks.registry import TASK_REGISTRY, TaskDefinition
    from app.tasks.runner import _running_tasks, trigger_task

    barrier = threading.Event()

    def _slow_task(db, set_progress):
        barrier.wait(timeout=5)
        return "done"

    TASK_REGISTRY["_test_slow"] = TaskDefinition(
        name="_test_slow",
        display_name="Slow Test",
        description="test",
        icon="fa-vial",
        func=_slow_task,
    )

    try:
        with patch("app.tasks.runner.SessionLocal", return_value=db_session):
            run1 = trigger_task("_test_slow", "user1")
            assert run1 is not None

            run2 = trigger_task("_test_slow", "user2")
            assert run2 is None  # blocked — already running
    finally:
        barrier.set()
        time.sleep(0.5)
        del TASK_REGISTRY["_test_slow"]
        _running_tasks.discard("_test_slow")


def test_trigger_unknown_task_raises():
    from app.tasks.runner import trigger_task

    with pytest.raises(ValueError, match="Unknown task"):
        trigger_task("nonexistent_task", "user")


def test_is_task_running():
    from app.tasks.runner import _running_lock, _running_tasks, is_task_running

    assert is_task_running("anything") is False

    with _running_lock:
        _running_tasks.add("_test_check")
    assert is_task_running("_test_check") is True

    with _running_lock:
        _running_tasks.discard("_test_check")


def test_task_execution_sets_completed(db_session):
    """Simulate the runner's _execute logic: task succeeds -> status=completed."""
    run = SystemTaskRun(
        task_name="test",
        display_name="Test",
        status="running",
        started_at=datetime.utcnow(),
    )
    db_session.add(run)
    db_session.flush()

    # Simulate what runner._execute does
    def set_progress(current, total):
        run.progress_current = current
        run.progress_total = total
        db_session.flush()

    set_progress(1, 3)
    assert run.progress_current == 1

    run.status = "completed"
    run.result_message = "done"
    run.finished_at = datetime.utcnow()
    run.progress_current = None
    run.progress_total = None
    db_session.flush()

    fetched = db_session.query(SystemTaskRun).filter_by(id=run.id).first()
    assert fetched.status == "completed"
    assert fetched.result_message == "done"
    assert fetched.progress_current is None


def test_task_execution_sets_failed(db_session):
    """Simulate the runner's _execute logic: task raises -> status=failed."""
    run = SystemTaskRun(
        task_name="test",
        display_name="Test",
        status="running",
        started_at=datetime.utcnow(),
    )
    db_session.add(run)
    db_session.flush()

    run.status = "failed"
    run.error_message = "something broke"
    run.finished_at = datetime.utcnow()
    db_session.flush()

    fetched = db_session.query(SystemTaskRun).filter_by(id=run.id).first()
    assert fetched.status == "failed"
    assert "something broke" in fetched.error_message


# ── Sync Plex Paths task tests ─────────────────────────────────────────────


def _make_job(db_session, plex_key, title, input_file, status=JobStatus.completed):
    req = ConversionRequest(
        title=title,
        request_type=RequestType.movie,
        plex_key=plex_key,
        status=RequestStatus.complete,
    )
    db_session.add(req)
    db_session.flush()
    job = ConversionJob(
        request_id=req.id,
        plex_key=plex_key,
        title=title,
        input_file=input_file,
        status=status,
    )
    db_session.add(job)
    db_session.flush()
    return req, job


def test_sync_no_jobs(db_session):
    from app.tasks.sync_plex_paths import sync_plex_paths

    progress_calls = []
    result = sync_plex_paths(db_session, lambda c, t: progress_calls.append((c, t)))
    assert "No conversion jobs" in result


def test_sync_updates_path(db_session):
    from app.tasks.sync_plex_paths import sync_plex_paths

    req, job = _make_job(db_session, "100", "Test Movie", "/old/path/movie.mkv")

    mock_client = MagicMock()
    mock_client.get_item.return_value = {
        "ratingKey": "100",
        "title": "Test Movie",
        "Media": [{"Part": [{"file": "/mnt/media/new/path/movie.mkv"}]}],
    }
    mock_client.resolve_file_path.return_value = "/mnt/media/new/path/movie.mkv"

    progress_calls = []
    with patch("app.tasks.sync_plex_paths.PlexClient", return_value=mock_client):
        result = sync_plex_paths(
            db_session, lambda c, t: progress_calls.append((c, t))
        )

    db_session.refresh(job)
    assert job.input_file == "/mnt/media/new/path/movie.mkv"
    assert "1 path(s) updated" in result
    assert len(progress_calls) >= 1


def test_sync_path_unchanged(db_session):
    from app.tasks.sync_plex_paths import sync_plex_paths

    req, job = _make_job(db_session, "100", "Test Movie", "/mnt/media/movie.mkv")

    mock_client = MagicMock()
    mock_client.get_item.return_value = {"ratingKey": "100", "title": "Test Movie"}
    mock_client.resolve_file_path.return_value = "/mnt/media/movie.mkv"

    with patch("app.tasks.sync_plex_paths.PlexClient", return_value=mock_client):
        result = sync_plex_paths(db_session, lambda c, t: None)

    assert "All paths are current" in result


def test_sync_relinks_stale_key_via_search(db_session):
    """When plex_key returns 404, search by title to find the new key."""
    from app.plex.client import PlexError
    from app.tasks.sync_plex_paths import sync_plex_paths

    req, job = _make_job(db_session, "OLD_KEY", "Christmas Vacation", "/old/cv.mkv")

    mock_client = MagicMock()
    mock_client.get_item.side_effect = PlexError("404 Not Found")
    mock_client.global_search.return_value = [
        {
            "type": "movie",
            "Metadata": [
                {"ratingKey": "NEW_KEY", "title": "Christmas Vacation", "year": 1989}
            ],
        }
    ]
    mock_client.resolve_file_path.return_value = "/mnt/media/new/cv.mkv"

    with patch("app.tasks.sync_plex_paths.PlexClient", return_value=mock_client):
        result = sync_plex_paths(db_session, lambda c, t: None)

    db_session.refresh(job)
    db_session.refresh(req)
    assert job.plex_key == "NEW_KEY"
    assert job.input_file == "/mnt/media/new/cv.mkv"
    assert req.plex_key == "NEW_KEY"
    assert "re-linked" in result


def test_sync_search_no_match(db_session):
    """When plex_key fails and search finds nothing, count as error."""
    from app.plex.client import PlexError
    from app.tasks.sync_plex_paths import sync_plex_paths

    req, job = _make_job(db_session, "GONE_KEY", "Deleted Movie", "/old/deleted.mkv")

    mock_client = MagicMock()
    mock_client.get_item.side_effect = PlexError("404")
    mock_client.global_search.return_value = []

    with patch("app.tasks.sync_plex_paths.PlexClient", return_value=mock_client):
        result = sync_plex_paths(db_session, lambda c, t: None)

    db_session.refresh(job)
    assert job.plex_key == "GONE_KEY"  # unchanged
    assert "could not be resolved" in result


def test_sync_search_case_insensitive_match(db_session):
    """Title matching should be case-insensitive."""
    from app.plex.client import PlexError
    from app.tasks.sync_plex_paths import sync_plex_paths

    req, job = _make_job(db_session, "OLD", "the matrix", "/old/matrix.mkv")

    mock_client = MagicMock()
    mock_client.get_item.side_effect = PlexError("404")
    mock_client.global_search.return_value = [
        {
            "type": "movie",
            "Metadata": [{"ratingKey": "NEW", "title": "The Matrix", "year": 1999}],
        }
    ]
    mock_client.resolve_file_path.return_value = "/mnt/media/matrix.mkv"

    with patch("app.tasks.sync_plex_paths.PlexClient", return_value=mock_client):
        sync_plex_paths(db_session, lambda c, t: None)

    db_session.refresh(job)
    assert job.plex_key == "NEW"


def test_sync_progress_callback(db_session):
    from app.tasks.sync_plex_paths import sync_plex_paths

    _make_job(db_session, "1", "Movie A", "/a.mkv")
    _make_job(db_session, "2", "Movie B", "/b.mkv")

    mock_client = MagicMock()
    mock_client.get_item.return_value = {"ratingKey": "1", "title": "Movie"}
    mock_client.resolve_file_path.return_value = "/a.mkv"

    calls = []
    with patch("app.tasks.sync_plex_paths.PlexClient", return_value=mock_client):
        sync_plex_paths(db_session, lambda c, t: calls.append((c, t)))

    # Should get: (0, N), ..., (N, N)
    assert calls[0] == (0, 2)
    assert calls[-1][0] == calls[-1][1]  # last call: current == total


def test_sync_multiple_jobs_mixed(db_session):
    """Mix of successful, path-changed, key-relinked, and failed jobs."""
    from app.plex.client import PlexError
    from app.tasks.sync_plex_paths import sync_plex_paths

    # Job 1: path unchanged
    _make_job(db_session, "A", "Unchanged", "/mnt/media/a.mkv")
    # Job 2: path changed
    _make_job(db_session, "B", "Moved", "/old/b.mkv")
    # Job 3: key stale, searchable
    _make_job(db_session, "C_OLD", "Relinked", "/old/c.mkv")

    mock_client = MagicMock()

    def get_item_side_effect(key):
        if key == "A":
            return {"ratingKey": "A", "title": "Unchanged"}
        if key == "B":
            return {"ratingKey": "B", "title": "Moved"}
        raise PlexError("404")

    mock_client.get_item.side_effect = get_item_side_effect

    def resolve_side_effect(item, db=None):
        key = item.get("ratingKey", "")
        if key == "A":
            return "/mnt/media/a.mkv"
        if key == "B":
            return "/mnt/media/new/b.mkv"
        if key == "C_NEW":
            return "/mnt/media/new/c.mkv"
        raise PlexError("not allowed")

    mock_client.resolve_file_path.side_effect = resolve_side_effect
    mock_client.global_search.return_value = [
        {"type": "movie", "Metadata": [{"ratingKey": "C_NEW", "title": "Relinked"}]}
    ]

    with patch("app.tasks.sync_plex_paths.PlexClient", return_value=mock_client):
        result = sync_plex_paths(db_session, lambda c, t: None)

    assert "2 path(s) updated" in result
    assert "1 Plex key(s) re-linked" in result


# ── Admin route tests ──────────────────────────────────────────────────────


def test_tasks_page_loads(admin_client):
    c, _ = admin_client
    resp = c.get("/admin/tasks")
    assert resp.status_code == 200
    assert b"Sync Plex Paths" in resp.content


def test_tasks_page_rejects_non_admin(user_client):
    c, _ = user_client
    resp = c.get("/admin/tasks", follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_tasks_status_endpoint(admin_client):
    c, _ = admin_client
    resp = c.get("/admin/tasks/status")
    assert resp.status_code == 200
    assert b"Sync Plex Paths" in resp.content


def test_run_unknown_task(admin_client):
    c, _ = admin_client
    resp = c.post("/admin/tasks/nonexistent/run", follow_redirects=False)
    # App has a global 404 handler that redirects to /
    assert resp.status_code in (302, 404)


def test_run_task_redirects(admin_client, db_session):
    """Running a valid task should redirect to the tasks page."""
    from app.tasks.registry import TASK_REGISTRY, TaskDefinition
    from app.tasks.runner import _running_tasks

    def _noop(db, set_progress):
        return "noop"

    TASK_REGISTRY["_test_noop"] = TaskDefinition(
        name="_test_noop",
        display_name="Noop",
        description="test",
        icon="fa-vial",
        func=_noop,
    )

    try:
        c, _ = admin_client
        resp = c.post("/admin/tasks/_test_noop/run", follow_redirects=False)
        assert resp.status_code == 303
        assert "/admin/tasks" in resp.headers.get("location", "")
    finally:
        time.sleep(0.5)
        del TASK_REGISTRY["_test_noop"]
        _running_tasks.discard("_test_noop")


def test_run_already_running_task(admin_client, db_session):
    """Running an already-running task should still redirect (with flash)."""
    from app.tasks.registry import TASK_REGISTRY, TaskDefinition
    from app.tasks.runner import _running_tasks

    barrier = threading.Event()

    def _slow(db, set_progress):
        barrier.wait(timeout=5)
        return "done"

    TASK_REGISTRY["_test_dup"] = TaskDefinition(
        name="_test_dup",
        display_name="Dup Test",
        description="test",
        icon="fa-vial",
        func=_slow,
    )

    try:
        c, _ = admin_client
        # Start it first
        c.post("/admin/tasks/_test_dup/run", follow_redirects=False)
        time.sleep(0.2)

        # Try again — should redirect with "already running" flash
        resp = c.post("/admin/tasks/_test_dup/run", follow_redirects=False)
        assert resp.status_code == 303
    finally:
        barrier.set()
        time.sleep(0.5)
        del TASK_REGISTRY["_test_dup"]
        _running_tasks.discard("_test_dup")


def test_activity_feed_endpoint(admin_client):
    c, _ = admin_client
    resp = c.get("/admin/activity-feed")
    assert resp.status_code == 200


def test_activity_feed_shows_running(admin_client, db_session):
    run = SystemTaskRun(
        task_name="sync_plex_paths",
        display_name="Sync Plex Paths",
        status="running",
        started_at=datetime.utcnow(),
        progress_current=5,
        progress_total=20,
    )
    db_session.add(run)
    db_session.flush()

    c, _ = admin_client
    resp = c.get("/admin/activity-feed")
    assert resp.status_code == 200
    assert b"Sync Plex Paths" in resp.content
    assert b"5" in resp.content


def test_activity_feed_shows_recent_completed(admin_client, db_session):
    run = SystemTaskRun(
        task_name="sync_plex_paths",
        display_name="Sync Plex Paths",
        status="completed",
        started_at=datetime.utcnow() - timedelta(seconds=5),
        finished_at=datetime.utcnow(),
        result_message="Updated 3 paths.",
    )
    db_session.add(run)
    db_session.flush()

    c, _ = admin_client
    resp = c.get("/admin/activity-feed")
    assert resp.status_code == 200
    assert b"Sync Plex Paths" in resp.content


def test_activity_feed_hides_old_completed(admin_client, db_session):
    """Completed tasks older than 30s should not show in the feed."""
    run = SystemTaskRun(
        task_name="sync_plex_paths",
        display_name="Sync Plex Paths",
        status="completed",
        started_at=datetime.utcnow() - timedelta(minutes=5),
        finished_at=datetime.utcnow() - timedelta(minutes=4),
        result_message="Old result.",
    )
    db_session.add(run)
    db_session.flush()

    c, _ = admin_client
    resp = c.get("/admin/activity-feed")
    assert resp.status_code == 200
    # Should be empty since the task is old
    assert b"Sync Plex Paths" not in resp.content


def test_activity_feed_rejects_non_admin(user_client):
    c, _ = user_client
    resp = c.get("/admin/activity-feed", follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_tasks_events_sse_endpoint(admin_client):
    c, _ = admin_client
    resp = c.get("/admin/tasks/events")
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("text/event-stream")


# ── Model tests ────────────────────────────────────────────────────────────


def test_system_task_run_model(db_session):
    run = SystemTaskRun(
        task_name="test",
        display_name="Test",
        status="running",
        started_at=datetime.utcnow(),
        triggered_by="admin",
        progress_current=5,
        progress_total=10,
    )
    db_session.add(run)
    db_session.flush()

    fetched = db_session.query(SystemTaskRun).filter_by(id=run.id).first()
    assert fetched.task_name == "test"
    assert fetched.progress_current == 5
    assert fetched.progress_total == 10
    assert fetched.status == "running"


def test_system_task_run_nullable_fields(db_session):
    run = SystemTaskRun(
        task_name="minimal",
        display_name="Minimal",
        status="completed",
        started_at=datetime.utcnow(),
    )
    db_session.add(run)
    db_session.flush()

    fetched = db_session.query(SystemTaskRun).filter_by(id=run.id).first()
    assert fetched.finished_at is None
    assert fetched.result_message is None
    assert fetched.error_message is None
    assert fetched.triggered_by is None
    assert fetched.progress_current is None
    assert fetched.progress_total is None
