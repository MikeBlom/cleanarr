from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..deps import get_db, require_user
from ..models import ConversionJob, ConversionRequest, JobStatus, RequestStatus, User
from ..templates import templates

router = APIRouter(prefix="/jobs")


@router.get("/{job_id}", response_class=HTMLResponse)
async def job_detail(
    request: Request,
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    job = db.query(ConversionJob).filter(ConversionJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404)
    if not user.is_admin and (not job.request or job.request.user_id != user.id):
        raise HTTPException(status_code=403)
    content_report = None
    if job.content_report:
        try:
            content_report = json.loads(job.content_report)
        except Exception:
            pass
    has_sidecar = (
        Path(job.input_file).with_suffix(".cleanmedia.json").exists()
        if job.input_file
        else False
    )
    return templates.TemplateResponse(
        "jobs/detail.html",
        {
            "request": request,
            "user": user,
            "job": job,
            "content_report": content_report,
            "has_sidecar": has_sidecar,
        },
    )


@router.post("/{job_id}/retry")
async def retry_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    job = db.query(ConversionJob).filter(ConversionJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404)
    if not user.is_admin and (not job.request or job.request.user_id != user.id):
        raise HTTPException(status_code=403)
    if job.status not in (JobStatus.failed, JobStatus.skipped):
        raise HTTPException(
            status_code=400, detail="Only failed or skipped jobs can be retried."
        )
    # Reset job to queued — keep sidecar on disk for --resume
    job.status = JobStatus.queued
    job.error_message = None
    job.log_output = None
    job.started_at = None
    job.finished_at = None
    job.progress_json = None
    # Also ensure the parent request is queued
    req = (
        db.query(ConversionRequest)
        .filter(ConversionRequest.id == job.request_id)
        .first()
    )
    if req and req.status != RequestStatus.queued:
        req.status = RequestStatus.queued
    db.commit()
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.get("/{job_id}/progress", response_class=HTMLResponse)
async def job_progress(
    request: Request,
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    job = db.query(ConversionJob).filter(ConversionJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404)
    if not user.is_admin and (not job.request or job.request.user_id != user.id):
        raise HTTPException(status_code=403)
    progress = None
    if job.progress_json:
        try:
            progress = json.loads(job.progress_json)
        except Exception:
            pass
    return templates.TemplateResponse(
        "jobs/_progress.html",
        {"request": request, "job": job, "progress": progress},
    )


@router.get("/{job_id}/log", response_class=HTMLResponse)
async def job_log(
    request: Request,
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    job = db.query(ConversionJob).filter(ConversionJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404)
    if not user.is_admin and (not job.request or job.request.user_id != user.id):
        raise HTTPException(status_code=403)
    log = job.log_output or ""
    status = job.status.value if job.status else "unknown"
    return HTMLResponse(f'<pre id="log-content" data-status="{status}">{log}</pre>')


@router.post("/{job_id}/move-up")
async def move_job_up(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    job = db.query(ConversionJob).filter(ConversionJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404)
    if not user.is_admin and (not job.request or job.request.user_id != user.id):
        raise HTTPException(status_code=403)
    _reorder_user_job(db, job, user, direction=-1)
    return RedirectResponse(f"/requests/{job.request_id}", status_code=303)


@router.post("/{job_id}/move-down")
async def move_job_down(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    job = db.query(ConversionJob).filter(ConversionJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404)
    if not user.is_admin and (not job.request or job.request.user_id != user.id):
        raise HTTPException(status_code=403)
    _reorder_user_job(db, job, user, direction=1)
    return RedirectResponse(f"/requests/{job.request_id}", status_code=303)


def _reorder_user_job(
    db: Session, job: ConversionJob, user: User, direction: int
) -> None:
    """Reorder a queued job within the user's own jobs (or all jobs if admin)."""
    if job.status != JobStatus.queued:
        return
    if user.is_admin:
        # Admin can reorder across all queued jobs
        jobs = (
            db.query(ConversionJob)
            .filter(ConversionJob.status == JobStatus.queued)
            .order_by(ConversionJob.priority.asc(), ConversionJob.created_at.asc())
            .all()
        )
    else:
        # User can only reorder within their own requests' jobs
        user_request_ids = [
            r.id
            for r in db.query(ConversionRequest.id)
            .filter(ConversionRequest.user_id == user.id)
            .all()
        ]
        jobs = (
            db.query(ConversionJob)
            .filter(
                ConversionJob.status == JobStatus.queued,
                ConversionJob.request_id.in_(user_request_ids),
            )
            .order_by(ConversionJob.priority.asc(), ConversionJob.created_at.asc())
            .all()
        )
    idx = next((i for i, j in enumerate(jobs) if j.id == job.id), None)
    if idx is None:
        return
    swap_idx = idx + direction
    if swap_idx < 0 or swap_idx >= len(jobs):
        return
    for i, j in enumerate(jobs):
        j.priority = i * 10
    jobs[idx].priority, jobs[swap_idx].priority = (
        jobs[swap_idx].priority,
        jobs[idx].priority,
    )
    db.commit()
