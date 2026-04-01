from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..deps import get_db, require_admin
from ..models import AppSetting, ConversionJob, ConversionRequest, JobStatus, RequestStatus, User
from ..templates import templates

router = APIRouter(prefix="/admin")


@router.get("", response_class=HTMLResponse)
async def admin_index(request: Request, user: User = Depends(require_admin)):
    return RedirectResponse("/admin/users", status_code=302)


@router.get("/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    users = db.query(User).order_by(User.created_at.desc()).all()
    return templates.TemplateResponse(
        "admin/users.html",
        {"request": request, "user": user, "users": users},
    )


@router.post("/users/{user_id}/approve")
async def approve_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404)
    target.is_approved = True
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/revoke")
async def revoke_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404)
    target.is_approved = False
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/toggle-admin")
async def toggle_admin(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404)
    if target.id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot change your own admin status.")
    target.is_admin = not target.is_admin
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.get("/queue", response_class=HTMLResponse)
async def admin_queue(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    jobs = (
        db.query(ConversionJob)
        .filter(ConversionJob.status.in_([JobStatus.queued, JobStatus.running, JobStatus.failed]))
        .order_by(ConversionJob.created_at.desc())
        .limit(200)
        .all()
    )
    return templates.TemplateResponse(
        "admin/queue.html",
        {"request": request, "user": user, "jobs": jobs},
    )


@router.post("/jobs/{job_id}/cancel")
async def cancel_job(
    job_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    job = db.query(ConversionJob).filter(ConversionJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404)
    if job.status in (JobStatus.queued, JobStatus.running):
        job.status = JobStatus.skipped
        job.error_message = "Cancelled by admin."
        job.finished_at = datetime.utcnow() if job.status == JobStatus.running else None
        db.commit()
        _rollup_request(db, job.request_id)
    return RedirectResponse("/admin/queue", status_code=303)


@router.post("/jobs/{job_id}/retry")
async def retry_job(
    job_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    job = db.query(ConversionJob).filter(ConversionJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404)
    if job.status in (JobStatus.failed, JobStatus.skipped):
        job.status = JobStatus.queued
        job.error_message = None
        job.log_output = None
        job.started_at = None
        job.finished_at = None
        db.commit()
        req = db.query(ConversionRequest).filter(ConversionRequest.id == job.request_id).first()
        if req:
            req.status = RequestStatus.queued
            db.commit()
    return RedirectResponse("/admin/queue", status_code=303)


@router.post("/jobs/{job_id}/move-up")
async def move_job_up(
    job_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    _reorder_job(db, job_id, direction=-1)
    return RedirectResponse("/admin/queue", status_code=303)


@router.post("/jobs/{job_id}/move-down")
async def move_job_down(
    job_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    _reorder_job(db, job_id, direction=1)
    return RedirectResponse("/admin/queue", status_code=303)


def _reorder_job(db: Session, job_id: int, direction: int) -> None:
    """Move a queued job up (direction=-1) or down (direction=1) in the queue."""
    jobs = (
        db.query(ConversionJob)
        .filter(ConversionJob.status == JobStatus.queued)
        .order_by(ConversionJob.priority.asc(), ConversionJob.created_at.asc())
        .all()
    )
    idx = next((i for i, j in enumerate(jobs) if j.id == job_id), None)
    if idx is None:
        return
    swap_idx = idx + direction
    if swap_idx < 0 or swap_idx >= len(jobs):
        return
    # Reassign all priorities as sequential integers, then swap
    for i, j in enumerate(jobs):
        j.priority = i * 10
    jobs[idx].priority, jobs[swap_idx].priority = jobs[swap_idx].priority, jobs[idx].priority
    db.commit()


@router.get("/settings", response_class=HTMLResponse)
async def admin_settings(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    from .. import app_settings
    s = app_settings.all_settings(db)
    # Parse JSON lists for display in textareas
    import json
    words = "\n".join(json.loads(s.get("profanity_words", "[]")))
    phrases = "\n".join(json.loads(s.get("profanity_phrases", "[]")))
    categories = json.loads(s.get("nudity_categories", "[]"))
    violence_categories = json.loads(s.get("violence_categories", "[]"))
    return templates.TemplateResponse(
        "admin/settings.html",
        {
            "request": request,
            "user": user,
            "s": s,
            "words": words,
            "phrases": phrases,
            "categories": categories,
            "violence_categories": violence_categories,
            "saved": request.query_params.get("saved"),
        },
    )


@router.post("/settings")
async def save_settings(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_admin),
):
    from .. import app_settings
    import json
    form = await request.form()

    # Simple string fields
    for key in (
        "plex_server_url", "plex_admin_token", "plex_client_id",
        "plex_admin_plex_ids", "plex_path_prefix_from", "plex_path_prefix_to",
        "allowed_media_dirs", "cleanmedia_bin", "whisper_model",
        "ollama_url", "ollama_model",
    ):
        val = form.get(key, "")
        app_settings.put(db, key, str(val).strip())

    # Numeric fields
    for key in ("profanity_padding_ms", "nudity_padding_ms", "nudity_scene_merge_gap_ms", "nudity_sample_fps"):
        val = form.get(key, "")
        app_settings.put(db, key, str(val).strip())

    app_settings.put(db, "nudity_confidence", str(form.get("nudity_confidence", "0.7")).strip())

    # Profanity words/phrases from newline-separated textareas
    raw_words = str(form.get("profanity_words", ""))
    words = [w.strip().lower() for w in raw_words.splitlines() if w.strip()]
    app_settings.put(db, "profanity_words", json.dumps(words))

    raw_phrases = str(form.get("profanity_phrases", ""))
    phrases = [p.strip().lower() for p in raw_phrases.splitlines() if p.strip()]
    app_settings.put(db, "profanity_phrases", json.dumps(phrases))

    # Nudity categories from checkboxes
    cats = form.getlist("nudity_categories")
    app_settings.put(db, "nudity_categories", json.dumps(list(cats)))

    # Multi-model pipeline settings
    dets = form.getlist("nudity_detectors")
    app_settings.put(db, "nudity_detectors", json.dumps(list(dets)) if dets else '["nudenet"]')

    for key in ("nudity_ensemble_strategy", "nudity_extraction_mode", "nudity_device"):
        val = form.get(key, "")
        app_settings.put(db, key, str(val).strip())

    app_settings.put(db, "nudity_temporal_enabled", "true" if form.get("nudity_temporal_enabled") else "false")

    for key in ("nudity_temporal_window", "nudity_temporal_min_flagged"):
        val = form.get(key, "")
        app_settings.put(db, key, str(val).strip())

    # Violence settings
    app_settings.put(db, "violence_confidence", str(form.get("violence_confidence", "0.5")).strip())

    for key in ("violence_padding_ms", "violence_scene_merge_gap_ms", "violence_sample_fps"):
        val = form.get(key, "")
        app_settings.put(db, key, str(val).strip())

    viol_cats = form.getlist("violence_categories")
    app_settings.put(db, "violence_categories", json.dumps(list(viol_cats)))

    viol_dets = form.getlist("violence_detectors")
    app_settings.put(db, "violence_detectors", json.dumps(list(viol_dets)) if viol_dets else '["siglip_violence"]')

    for key in ("violence_ensemble_strategy", "violence_extraction_mode", "violence_device"):
        val = form.get(key, "")
        app_settings.put(db, key, str(val).strip())

    app_settings.put(db, "violence_temporal_enabled", "true" if form.get("violence_temporal_enabled") else "false")

    for key in ("violence_temporal_window", "violence_temporal_min_flagged"):
        val = form.get(key, "")
        app_settings.put(db, key, str(val).strip())

    # AI advisor checkbox
    app_settings.put(db, "ai_advisor_enabled", "true" if form.get("ai_advisor_enabled") else "false")

    db.commit()
    return RedirectResponse("/admin/settings?saved=1", status_code=303)


def _rollup_request(db: Session, request_id: int) -> None:
    req = db.query(ConversionRequest).filter(ConversionRequest.id == request_id).first()
    if not req:
        return
    statuses = {j.status for j in req.jobs}
    if JobStatus.running in statuses or JobStatus.queued in statuses:
        req.status = RequestStatus.queued
    elif all(s in (JobStatus.completed, JobStatus.already_exists) for s in statuses):
        req.status = RequestStatus.complete
    elif JobStatus.completed in statuses or JobStatus.already_exists in statuses:
        req.status = RequestStatus.partially_complete
    elif all(s in (JobStatus.failed, JobStatus.skipped) for s in statuses):
        req.status = RequestStatus.failed
    db.commit()
