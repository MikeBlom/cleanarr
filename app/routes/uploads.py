from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth.sessions import set_flash
from ..config import settings
from ..deps import get_db, require_user
from ..models import ConversionJob, ConversionRequest, JobStatus, RequestStatus, RequestType, User
from ..templates import templates

router = APIRouter()

ALLOWED_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm"}


def _active_upload(db: Session, user_id: int) -> ConversionRequest | None:
    """Return the user's active upload request (queued, running, or completed awaiting download)."""
    return (
        db.query(ConversionRequest)
        .filter(
            ConversionRequest.user_id == user_id,
            ConversionRequest.source == "upload",
            ConversionRequest.status.in_([
                RequestStatus.pending, RequestStatus.queued,
                RequestStatus.partially_complete, RequestStatus.complete,
            ]),
        )
        .first()
    )


@router.get("/upload", response_class=HTMLResponse)
async def upload_page(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    active = _active_upload(db, user.id)
    if active:
        # Redirect to the active request — user must download or delete it first
        redirect = RedirectResponse(f"/requests/{active.id}", status_code=302)
        set_flash(redirect, "You already have an upload being processed. Download or delete it before uploading another.", "info")
        return redirect

    from .. import app_settings as _as
    s = _as.all_settings(db)
    return templates.TemplateResponse("upload.html", {
        "request": request,
        "user": user,
        "max_upload_mb": settings.MAX_UPLOAD_SIZE_MB,
        "profanity_defaults": s,
        "nudity_defaults": s,
        "violence_defaults": s,
    })


@router.post("/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    # Block if user already has an active upload
    active = _active_upload(db, user.id)
    if active:
        redirect = RedirectResponse(f"/requests/{active.id}", status_code=303)
        set_flash(redirect, "You already have an upload being processed. Download or delete it first.", "error")
        return redirect

    # Validate extension
    filename = file.filename or "video.mkv"
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        from .. import app_settings as _as
        s = _as.all_settings(db)
        return templates.TemplateResponse("upload.html", {
            "request": request, "user": user,
            "max_upload_mb": settings.MAX_UPLOAD_SIZE_MB,
            "profanity_defaults": s, "nudity_defaults": s, "violence_defaults": s,
            "errors": [f"File type '{ext}' is not supported. Accepted: {', '.join(sorted(ALLOWED_EXTENSIONS))}"],
        })

    # Create upload directory with open permissions so the host worker can write sidecars
    upload_id = str(uuid.uuid4())
    write_dir = Path(settings.UPLOAD_DIR) / str(user.id) / upload_id
    write_dir.mkdir(parents=True, exist_ok=True)
    import os
    os.chmod(write_dir, 0o777)

    dest = write_dir / f"{Path(filename).stem}{ext}"
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    written = 0

    try:
        with open(dest, "wb") as f:
            while True:
                chunk = await file.read(1024 * 1024)  # 1MB chunks
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    f.close()
                    shutil.rmtree(write_dir)
                    from .. import app_settings as _as
                    s = _as.all_settings(db)
                    return templates.TemplateResponse("upload.html", {
                        "request": request, "user": user,
                        "max_upload_mb": settings.MAX_UPLOAD_SIZE_MB,
                        "profanity_defaults": s, "nudity_defaults": s, "violence_defaults": s,
                        "errors": [f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_MB // 1024}GB."],
                    })
                f.write(chunk)
    except Exception:
        shutil.rmtree(write_dir, ignore_errors=True)
        raise

    os.chmod(dest, 0o666)

    # Parse form fields for filters and overrides
    import json as _json
    form = await request.form()
    filter_profanity = form.get("filter_profanity") == "true"
    filter_nudity = form.get("filter_nudity") == "true"
    filter_violence = form.get("filter_violence") == "true"
    use_bleep = form.get("use_bleep") == "true"
    use_whisper = form.get("use_whisper") == "true"

    # Profanity overrides
    extra_words_raw = str(form.get("profanity_extra_words", "")).strip()
    extra_words_json = _json.dumps([w.strip() for w in extra_words_raw.splitlines() if w.strip()]) if extra_words_raw else None
    extra_phrases_raw = str(form.get("profanity_extra_phrases", "")).strip()
    extra_phrases_json = _json.dumps([p.strip() for p in extra_phrases_raw.splitlines() if p.strip()]) if extra_phrases_raw else None
    prof_padding = form.get("profanity_padding_ms")
    whisper_model = form.get("whisper_model_override")

    # Nudity overrides
    nud_conf = form.get("nudity_confidence")
    nud_fps = form.get("nudity_sample_fps")
    nud_pad = form.get("nudity_padding_ms")
    nud_gap = form.get("nudity_scene_merge_gap_ms")
    nud_cats = form.getlist("nudity_category")
    nud_dets = form.getlist("nudity_detector")
    nud_ens = form.get("nudity_ensemble_strategy")
    nud_ext = form.get("nudity_extraction_mode")
    nud_temp = form.get("nudity_temporal_enabled") == "true"
    nud_win = form.get("nudity_temporal_window")
    nud_min = form.get("nudity_temporal_min_flagged")

    # Violence overrides
    viol_conf = form.get("violence_confidence")
    viol_fps = form.get("violence_sample_fps")
    viol_pad = form.get("violence_padding_ms")
    viol_gap = form.get("violence_scene_merge_gap_ms")
    viol_cats = form.getlist("violence_category")
    viol_dets = form.getlist("violence_detector")
    viol_ens = form.get("violence_ensemble_strategy")
    viol_ext = form.get("violence_extraction_mode")
    viol_temp = form.get("violence_temporal_enabled") == "true"
    viol_win = form.get("violence_temporal_window")
    viol_min = form.get("violence_temporal_min_flagged")

    # Create request and job
    req = ConversionRequest(
        user_id=user.id,
        plex_key="upload",
        title=filename,
        source="upload",
        original_filename=filename,
        request_type=RequestType.movie,
        filter_profanity=filter_profanity,
        filter_nudity=filter_nudity,
        filter_violence=filter_violence,
        use_whisper=use_whisper,
        use_bleep=use_bleep,
        profanity_extra_words_json=extra_words_json,
        profanity_extra_phrases_json=extra_phrases_json,
        profanity_padding_ms=int(prof_padding) if prof_padding else None,
        whisper_model=whisper_model if whisper_model else None,
        nudity_confidence=float(nud_conf) if nud_conf else None,
        nudity_sample_fps=float(nud_fps) if nud_fps else None,
        nudity_padding_ms=int(nud_pad) if nud_pad else None,
        nudity_scene_merge_gap_ms=int(nud_gap) if nud_gap else None,
        nudity_categories_json=_json.dumps(list(nud_cats)) if nud_cats else None,
        nudity_detectors_json=_json.dumps(list(nud_dets)) if nud_dets else None,
        nudity_ensemble_strategy=nud_ens if nud_ens else None,
        nudity_extraction_mode=nud_ext if nud_ext else None,
        nudity_temporal_enabled=nud_temp if nud_temp else None,
        nudity_temporal_window=int(nud_win) if nud_win else None,
        nudity_temporal_min_flagged=int(nud_min) if nud_min else None,
        violence_confidence=float(viol_conf) if viol_conf else None,
        violence_sample_fps=float(viol_fps) if viol_fps else None,
        violence_padding_ms=int(viol_pad) if viol_pad else None,
        violence_scene_merge_gap_ms=int(viol_gap) if viol_gap else None,
        violence_categories_json=_json.dumps(list(viol_cats)) if viol_cats else None,
        violence_detectors_json=_json.dumps(list(viol_dets)) if viol_dets else None,
        violence_ensemble_strategy=viol_ens if viol_ens else None,
        violence_extraction_mode=viol_ext if viol_ext else None,
        violence_temporal_enabled=viol_temp if viol_temp else None,
        violence_temporal_window=int(viol_win) if viol_win else None,
        violence_temporal_min_flagged=int(viol_min) if viol_min else None,
        status=RequestStatus.queued,
    )
    db.add(req)
    db.flush()

    # Store host-mapped path in DB so the systemd worker can access it
    host_dir = settings.UPLOAD_DIR_HOST or settings.UPLOAD_DIR
    host_file = str(dest).replace(settings.UPLOAD_DIR, host_dir, 1) if host_dir != settings.UPLOAD_DIR else str(dest)

    job = ConversionJob(
        request_id=req.id,
        plex_key="upload",
        title=filename,
        input_file=host_file,
        status=JobStatus.queued,
    )
    db.add(job)
    db.commit()

    redirect = RedirectResponse(f"/requests/{req.id}", status_code=303)
    set_flash(redirect, f"Upload complete! Processing {filename}.", "success")
    return redirect


@router.get("/requests/{req_id}/download/{job_id}")
async def download_clean_file(
    req_id: int,
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    req = db.query(ConversionRequest).filter(ConversionRequest.id == req_id).first()
    if not req:
        raise HTTPException(status_code=404)
    if req.user_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403)
    if req.source != "upload":
        raise HTTPException(status_code=400, detail="Downloads are only available for uploaded files.")

    job = db.query(ConversionJob).filter(
        ConversionJob.id == job_id,
        ConversionJob.request_id == req_id,
    ).first()
    if not job or not job.output_file:
        raise HTTPException(status_code=404, detail="Clean file not available.")

    # Map host path back to container path for file access
    host_dir = settings.UPLOAD_DIR_HOST or settings.UPLOAD_DIR
    output_str = job.output_file
    if host_dir != settings.UPLOAD_DIR:
        output_str = output_str.replace(host_dir, settings.UPLOAD_DIR, 1)
    output_path = Path(output_str)
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Clean file not found on disk.")

    # Build download filename from original
    orig = req.original_filename or "video.mkv"
    stem = Path(orig).stem
    ext = output_path.suffix
    download_name = f"{stem} (Clean){ext}"

    # Mark request as failed (used as "downloaded" state) so the upload slot is freed
    # and schedule cleanup after the file is streamed
    input_str = job.input_file
    if host_dir != settings.UPLOAD_DIR:
        input_str = input_str.replace(host_dir, settings.UPLOAD_DIR, 1)
    upload_dir = Path(input_str).parent
    req.status = RequestStatus.failed
    db.commit()

    from starlette.background import BackgroundTask

    def _cleanup():
        shutil.rmtree(upload_dir, ignore_errors=True)
        from ..database import SessionLocal
        cleanup_db = SessionLocal()
        try:
            r = cleanup_db.query(ConversionRequest).filter(ConversionRequest.id == req_id).first()
            if r:
                cleanup_db.delete(r)
                cleanup_db.commit()
        finally:
            cleanup_db.close()

    return FileResponse(
        path=str(output_path),
        filename=download_name,
        media_type="application/octet-stream",
        background=BackgroundTask(_cleanup),
    )
