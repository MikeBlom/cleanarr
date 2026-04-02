from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth.password import hash_password
from ..auth.sessions import set_flash
from ..deps import get_db, require_admin
from ..models import AppSetting, ConversionJob, ConversionRequest, Invitation, JobStatus, RequestStatus, User
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
    invitations = db.query(Invitation).order_by(Invitation.created_at.desc()).limit(50).all()
    return templates.TemplateResponse(
        "admin/users.html",
        {"request": request, "user": user, "users": users, "invitations": invitations, "now": datetime.utcnow()},
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


@router.post("/users/{user_id}/delete")
async def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404)
    if target.id == admin.id:
        redirect = RedirectResponse("/admin/users", status_code=303)
        set_flash(redirect, "You cannot delete your own account.", "error")
        return redirect
    name = target.username
    db.delete(target)
    db.commit()
    redirect = RedirectResponse("/admin/users", status_code=303)
    set_flash(redirect, f"Deleted user {name}.", "success")
    return redirect


@router.post("/users/bulk")
async def bulk_user_action(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    form = await request.form()
    action = form.get("action", "")
    user_ids = [int(x) for x in form.getlist("user_ids") if x.isdigit()]

    if not user_ids or action not in ("approve", "revoke", "delete", "invite"):
        redirect = RedirectResponse("/admin/users", status_code=303)
        set_flash(redirect, "No action taken.", "info")
        return redirect

    targets = db.query(User).filter(User.id.in_(user_ids)).all()
    count = 0

    if action == "invite":
        from ..config import settings as cfg
        from ..email import is_email_configured, send_invite_email
        invited = 0
        no_email = 0
        for target in targets:
            if target.id == admin.id:
                continue
            if not target.email:
                no_email += 1
                continue
            token = secrets.token_urlsafe(48)
            inv = Invitation(
                email=target.email,
                token=token,
                invited_by=admin.id,
                expires_at=datetime.utcnow() + timedelta(days=7),
            )
            db.add(inv)
            invite_url = f"{cfg.BASE_URL}/invite/{token}"
            if is_email_configured():
                send_invite_email(target.email, invite_url)
            invited += 1
        db.commit()
        redirect = RedirectResponse("/admin/users", status_code=303)
        msg = f"Invited {invited} user{'s' if invited != 1 else ''}."
        if no_email:
            msg += f" {no_email} skipped (no email on file)."
        set_flash(redirect, msg, "success" if invited else "warn")
        return redirect

    for target in targets:
        if target.id == admin.id:
            continue
        if action == "approve":
            target.is_approved = True
            count += 1
        elif action == "revoke":
            target.is_approved = False
            count += 1
        elif action == "delete":
            db.delete(target)
            count += 1
    db.commit()

    labels = {"approve": "approved", "revoke": "revoked", "delete": "deleted"}
    redirect = RedirectResponse("/admin/users", status_code=303)
    set_flash(redirect, f"{labels[action].capitalize()} {count} user{'s' if count != 1 else ''}.", "success")
    return redirect


@router.post("/users/{user_id}/masquerade")
async def masquerade_as_user(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404)
    if target.id == admin.id:
        redirect = RedirectResponse("/admin/users", status_code=303)
        set_flash(redirect, "You can't masquerade as yourself.", "error")
        return redirect
    redirect = RedirectResponse("/", status_code=303)
    redirect.set_cookie("cleanarr_masquerade", str(user_id), httponly=True, samesite="lax")
    set_flash(redirect, f"Now viewing as {target.username}.", "info")
    return redirect


@router.post("/masquerade/stop")
async def stop_masquerade(
    admin: User = Depends(require_admin),
):
    redirect = RedirectResponse("/admin/users", status_code=303)
    redirect.delete_cookie("cleanarr_masquerade")
    set_flash(redirect, "Masquerade ended.", "success")
    return redirect


@router.get("/users/create", response_class=HTMLResponse)
async def create_user_form(
    request: Request,
    user: User = Depends(require_admin),
):
    return templates.TemplateResponse(
        "admin/create_user.html",
        {"request": request, "user": user},
    )


@router.post("/users/create")
async def create_user(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    is_admin: bool = Form(False),
):
    errors = []
    if not username.strip():
        errors.append("Username is required.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if password != password_confirm:
        errors.append("Passwords do not match.")
    existing = db.query(User).filter(User.username == username.strip(), User.auth_method == "local").first()
    if existing:
        errors.append("A local user with that username already exists.")

    if errors:
        return templates.TemplateResponse("admin/create_user.html", {
            "request": request, "user": admin,
            "errors": errors, "form_username": username, "form_is_admin": is_admin,
        })

    new_user = User(
        username=username.strip(),
        auth_method="local",
        password_hash=hash_password(password),
        is_admin=is_admin,
        is_approved=True,
    )
    db.add(new_user)
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    new_password: str = Form(...),
):
    target = db.query(User).filter(User.id == user_id).first()
    if not target or target.auth_method != "local":
        raise HTTPException(status_code=404)
    if len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")
    target.password_hash = hash_password(new_password)
    db.commit()
    return RedirectResponse("/admin/users", status_code=303)


@router.post("/users/import-plex")
async def import_plex_users(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    from .. import app_settings as _as
    from ..auth.plex import fetch_server_users

    server_url = _as.get(db, "plex_server_url")
    admin_token = _as.get(db, "plex_admin_token")

    redirect = RedirectResponse("/admin/users", status_code=303)
    try:
        plex_users = fetch_server_users(server_url, admin_token)
    except Exception as e:
        set_flash(redirect, f"Failed to fetch Plex users: {e}", "error")
        return redirect

    existing_users = {u.plex_id: u for u in db.query(User).filter(User.plex_id.isnot(None)).all()}
    imported = 0
    updated = 0
    for pu in plex_users:
        email = pu.get("email") or None
        if pu["id"] not in existing_users:
            db.add(User(
                plex_id=pu["id"],
                username=pu["username"],
                email=email,
                auth_method="plex",
                is_approved=False,
            ))
            imported += 1
        elif email and not existing_users[pu["id"]].email:
            existing_users[pu["id"]].email = email
            updated += 1

    if imported or updated:
        db.commit()
        parts = []
        if imported:
            parts.append(f"Imported {imported} new user{'s' if imported != 1 else ''}")
        if updated:
            parts.append(f"updated emails for {updated} existing user{'s' if updated != 1 else ''}")
        set_flash(redirect, f"{', '.join(parts)} from Plex.", "success")
    else:
        set_flash(redirect, "No new users to import — all Plex users are already in CleanArr.", "info")
    return redirect


@router.get("/users/invite", response_class=HTMLResponse)
async def invite_form(
    request: Request,
    user: User = Depends(require_admin),
):
    return templates.TemplateResponse("admin/invite.html", {"request": request, "user": user})


@router.post("/users/invite")
async def invite_user(
    request: Request,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
    email: str = Form(...),
):
    from ..config import settings as cfg
    from ..email import is_email_configured, send_invite_email

    token = secrets.token_urlsafe(48)
    invitation = Invitation(
        email=email.strip(),
        token=token,
        invited_by=admin.id,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db.add(invitation)
    db.commit()

    invite_url = f"{cfg.BASE_URL}/invite/{token}"
    redirect = RedirectResponse("/admin/users", status_code=303)

    if is_email_configured():
        if send_invite_email(email.strip(), invite_url):
            set_flash(redirect, f"Invite sent to {email}.", "success")
        else:
            set_flash(redirect, f"Invite created but email failed to send. Link: {invite_url}", "warn")
    else:
        set_flash(redirect, f"Invite link (no SMTP configured): {invite_url}", "info")

    return redirect


@router.get("/queue")
async def admin_queue():
    return RedirectResponse("/requests", status_code=301)


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


@router.post("/jobs/{job_id}/delete")
async def delete_job(
    job_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    job = db.query(ConversionJob).filter(ConversionJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404)
    if job.status == JobStatus.running:
        redirect = RedirectResponse("/admin/queue", status_code=303)
        set_flash(redirect, "Cannot delete a running job. Cancel it first.", "error")
        return redirect
    request_id = job.request_id
    title = job.title
    db.delete(job)
    db.commit()
    _rollup_request(db, request_id)
    redirect = RedirectResponse("/admin/queue", status_code=303)
    set_flash(redirect, f"Deleted job: {title}", "success")
    return redirect


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
