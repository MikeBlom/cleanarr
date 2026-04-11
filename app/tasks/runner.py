from __future__ import annotations

import threading
from datetime import datetime

from ..database import SessionLocal
from ..models import SystemTaskRun
from .registry import TASK_REGISTRY

_running_lock = threading.Lock()
_running_tasks: set[str] = set()


def is_task_running(task_name: str) -> bool:
    return task_name in _running_tasks


def trigger_task(task_name: str, triggered_by: str) -> SystemTaskRun | None:
    """Launch a task in a background thread.

    Returns the SystemTaskRun row, or None if already running.
    """
    if task_name not in TASK_REGISTRY:
        raise ValueError(f"Unknown task: {task_name}")

    with _running_lock:
        if task_name in _running_tasks:
            return None
        _running_tasks.add(task_name)

    defn = TASK_REGISTRY[task_name]

    # Create the run record so UI can show "running" immediately
    db = SessionLocal()
    try:
        run = SystemTaskRun(
            task_name=task_name,
            display_name=defn.display_name,
            status="running",
            started_at=datetime.utcnow(),
            triggered_by=triggered_by,
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        run_id = run.id
    finally:
        db.close()

    def _execute() -> None:
        db = SessionLocal()
        try:
            run = db.query(SystemTaskRun).filter(SystemTaskRun.id == run_id).first()
            if not run:
                return

            def set_progress(current: int, total: int) -> None:
                run.progress_current = current
                run.progress_total = total
                db.commit()

            try:
                result = defn.func(db, set_progress)
                run.status = "completed"
                run.result_message = str(result) if result else "Done."
            except Exception as exc:
                run.status = "failed"
                run.error_message = str(exc)[:500]
            run.finished_at = datetime.utcnow()
            run.progress_current = None
            run.progress_total = None
            db.commit()
        finally:
            db.close()
            with _running_lock:
                _running_tasks.discard(task_name)

    thread = threading.Thread(
        target=_execute, name=f"task-{task_name}", daemon=True
    )
    thread.start()
    return run
