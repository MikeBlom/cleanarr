from __future__ import annotations

import json as _json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..deps import get_db, require_user
from ..models import (
    ConversionJob,
    ConversionRequest,
    JobStatus,
    RequestStatus,
    RequestType,
    User,
)
from ..plex.client import PlexClient, PlexError
from ..templates import templates

router = APIRouter()


def _build_output_path(input_path: str) -> str:
    import re
    from pathlib import Path

    p = Path(input_path)
    clean_stem = re.sub(r"\s*\{edition-[^}]+\}", "", p.stem).rstrip()
    return str(p.parent / (clean_stem + " {edition-Clean}" + p.suffix))


def _resolve_leaf_items(client: PlexClient, plex_key: str, item: dict) -> list[dict]:
    """Return list of leaf items (movies or individual episodes) for a given key."""
    item_type = item.get("type", "movie")
    if item_type == "movie":
        return [item]
    elif item_type == "episode":
        return [item]
    elif item_type in ("show", "season"):
        return client.get_leaves(plex_key)
    return []


@router.post("/request")
async def submit_request(
    request: Request,
    plex_key: str = Form(...),
    title: str = Form(...),
    request_type: str = Form(...),
    filter_profanity: bool = Form(False),
    filter_nudity: bool = Form(False),
    filter_violence: bool = Form(False),
    use_whisper: bool = Form(False),
    use_bleep: bool = Form(False),
    audio_stream_index: int | None = Form(None),
    nudity_confidence: float | None = Form(None),
    nudity_sample_fps: float | None = Form(None),
    nudity_padding_ms: int | None = Form(None),
    nudity_scene_merge_gap_ms: int | None = Form(None),
    profanity_padding_ms: int | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if not filter_profanity and not filter_nudity and not filter_violence:
        raise HTTPException(status_code=400, detail="Select at least one filter.")

    client = PlexClient(db)
    try:
        item = client.get_item(plex_key)
        leaves = _resolve_leaf_items(client, plex_key, item)
    except PlexError as e:
        raise HTTPException(status_code=502, detail=str(e))

    try:
        rtype = RequestType(request_type)
    except ValueError:
        rtype = RequestType.movie

    form = await request.form()

    # Collect per-request profanity overrides (only if override toggle was on)
    profanity_override_on = "profanity_padding_ms" in form
    extra_words_json = None
    extra_phrases_json = None
    whisper_model_override = None
    prof_padding_override = None
    if profanity_override_on:
        raw_words = str(form.get("profanity_extra_words", "")).strip()
        if raw_words:
            extra_words_json = _json.dumps(
                [w.strip().lower() for w in raw_words.splitlines() if w.strip()]
            )
        raw_phrases = str(form.get("profanity_extra_phrases", "")).strip()
        if raw_phrases:
            extra_phrases_json = _json.dumps(
                [p.strip().lower() for p in raw_phrases.splitlines() if p.strip()]
            )
        whisper_model_override = (
            str(form.get("whisper_model_override", "")).strip() or None
        )
        prof_padding_override = profanity_padding_ms

    # Collect per-request nudity category overrides (only if override toggle was on)
    nudity_override_on = "nudity_confidence" in form
    nudity_categories_json = None
    nudity_detectors_json = None
    nudity_ensemble_strategy = None
    nudity_temporal_enabled = None
    nudity_temporal_window = None
    nudity_temporal_min_flagged = None
    nudity_extraction_mode = None
    if nudity_override_on:
        cats = form.getlist("nudity_category")
        if cats:
            nudity_categories_json = _json.dumps(list(cats))
        dets = form.getlist("nudity_detector")
        if dets:
            nudity_detectors_json = _json.dumps(list(dets))
        raw_strategy = str(form.get("nudity_ensemble_strategy", "")).strip()
        if raw_strategy:
            nudity_ensemble_strategy = raw_strategy
        if "nudity_temporal_enabled" in form:
            nudity_temporal_enabled = True
        else:
            nudity_temporal_enabled = False
        raw_tw = str(form.get("nudity_temporal_window", "")).strip()
        if raw_tw:
            nudity_temporal_window = int(raw_tw)
        raw_tmf = str(form.get("nudity_temporal_min_flagged", "")).strip()
        if raw_tmf:
            nudity_temporal_min_flagged = int(raw_tmf)
        raw_em = str(form.get("nudity_extraction_mode", "")).strip()
        if raw_em:
            nudity_extraction_mode = raw_em

    # Collect per-request violence overrides
    violence_override_on = "violence_confidence" in form
    violence_categories_json = None
    violence_detectors_json = None
    violence_ensemble_strategy = None
    violence_temporal_enabled = None
    violence_temporal_window = None
    violence_temporal_min_flagged = None
    violence_extraction_mode = None
    violence_confidence = None
    violence_sample_fps = None
    violence_padding_ms = None
    violence_scene_merge_gap_ms = None
    if violence_override_on:
        raw_vc = str(form.get("violence_confidence", "")).strip()
        if raw_vc:
            violence_confidence = float(raw_vc)
        raw_vfps = str(form.get("violence_sample_fps", "")).strip()
        if raw_vfps:
            violence_sample_fps = float(raw_vfps)
        raw_vpad = str(form.get("violence_padding_ms", "")).strip()
        if raw_vpad:
            violence_padding_ms = int(raw_vpad)
        raw_vmg = str(form.get("violence_scene_merge_gap_ms", "")).strip()
        if raw_vmg:
            violence_scene_merge_gap_ms = int(raw_vmg)
        cats = form.getlist("violence_category")
        if cats:
            violence_categories_json = _json.dumps(list(cats))
        dets = form.getlist("violence_detector")
        if dets:
            violence_detectors_json = _json.dumps(list(dets))
        raw_strategy = str(form.get("violence_ensemble_strategy", "")).strip()
        if raw_strategy:
            violence_ensemble_strategy = raw_strategy
        if "violence_temporal_enabled" in form:
            violence_temporal_enabled = True
        else:
            violence_temporal_enabled = False
        raw_tw = str(form.get("violence_temporal_window", "")).strip()
        if raw_tw:
            violence_temporal_window = int(raw_tw)
        raw_tmf = str(form.get("violence_temporal_min_flagged", "")).strip()
        if raw_tmf:
            violence_temporal_min_flagged = int(raw_tmf)
        raw_em = str(form.get("violence_extraction_mode", "")).strip()
        if raw_em:
            violence_extraction_mode = raw_em

    conv_request = ConversionRequest(
        user_id=user.id,
        plex_key=plex_key,
        title=title,
        request_type=rtype,
        filter_profanity=filter_profanity,
        filter_nudity=filter_nudity,
        use_whisper=use_whisper,
        use_bleep=use_bleep,
        audio_stream_index=audio_stream_index,
        profanity_extra_words_json=extra_words_json if profanity_override_on else None,
        profanity_extra_phrases_json=extra_phrases_json
        if profanity_override_on
        else None,
        profanity_padding_ms=prof_padding_override if profanity_override_on else None,
        whisper_model=whisper_model_override if profanity_override_on else None,
        nudity_confidence=nudity_confidence if nudity_override_on else None,
        nudity_sample_fps=nudity_sample_fps if nudity_override_on else None,
        nudity_padding_ms=nudity_padding_ms if nudity_override_on else None,
        nudity_scene_merge_gap_ms=nudity_scene_merge_gap_ms
        if nudity_override_on
        else None,
        nudity_categories_json=nudity_categories_json,
        nudity_detectors_json=nudity_detectors_json if nudity_override_on else None,
        nudity_ensemble_strategy=nudity_ensemble_strategy
        if nudity_override_on
        else None,
        nudity_temporal_enabled=nudity_temporal_enabled if nudity_override_on else None,
        nudity_temporal_window=nudity_temporal_window if nudity_override_on else None,
        nudity_temporal_min_flagged=nudity_temporal_min_flagged
        if nudity_override_on
        else None,
        nudity_extraction_mode=nudity_extraction_mode if nudity_override_on else None,
        filter_violence=filter_violence,
        violence_confidence=violence_confidence if violence_override_on else None,
        violence_sample_fps=violence_sample_fps if violence_override_on else None,
        violence_padding_ms=violence_padding_ms if violence_override_on else None,
        violence_scene_merge_gap_ms=violence_scene_merge_gap_ms
        if violence_override_on
        else None,
        violence_categories_json=violence_categories_json
        if violence_override_on
        else None,
        violence_detectors_json=violence_detectors_json
        if violence_override_on
        else None,
        violence_ensemble_strategy=violence_ensemble_strategy
        if violence_override_on
        else None,
        violence_temporal_enabled=violence_temporal_enabled
        if violence_override_on
        else None,
        violence_temporal_window=violence_temporal_window
        if violence_override_on
        else None,
        violence_temporal_min_flagged=violence_temporal_min_flagged
        if violence_override_on
        else None,
        violence_extraction_mode=violence_extraction_mode
        if violence_override_on
        else None,
        status=RequestStatus.queued,
    )
    db.add(conv_request)
    db.flush()  # get ID

    skipped = 0
    for leaf in leaves:
        leaf_key = leaf.get("key", "").split("/")[-1]
        try:
            file_path = client.resolve_file_path(leaf, db=db)
        except PlexError:
            skipped += 1
            continue

        # Duplicate check
        existing = (
            db.query(ConversionJob)
            .filter(
                ConversionJob.input_file == file_path,
                ConversionJob.status.in_([JobStatus.queued, JobStatus.running]),
            )
            .first()
        )
        if existing:
            job = ConversionJob(
                request_id=conv_request.id,
                plex_key=leaf_key,
                title=leaf.get("title", title),
                input_file=file_path,
                output_file=None,
                status=JobStatus.skipped,
                error_message="Already queued or running.",
            )
        else:
            job = ConversionJob(
                request_id=conv_request.id,
                plex_key=leaf_key,
                title=leaf.get("title", title),
                input_file=file_path,
                output_file=None,
                status=JobStatus.queued,
            )
        db.add(job)

    db.commit()
    return RedirectResponse(f"/requests/{conv_request.id}", status_code=303)


@router.get("/requests", response_class=HTMLResponse)
async def list_requests(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    if user.is_admin:
        reqs = (
            db.query(ConversionRequest)
            .order_by(ConversionRequest.created_at.desc())
            .limit(100)
            .all()
        )
    else:
        reqs = (
            db.query(ConversionRequest)
            .filter(ConversionRequest.user_id == user.id)
            .order_by(ConversionRequest.created_at.desc())
            .limit(100)
            .all()
        )
    return templates.TemplateResponse(
        "requests/list.html",
        {"request": request, "user": user, "requests": reqs},
    )


@router.get("/requests/{req_id}", response_class=HTMLResponse)
async def request_detail(
    request: Request,
    req_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    conv_req = (
        db.query(ConversionRequest).filter(ConversionRequest.id == req_id).first()
    )
    if not conv_req:
        raise HTTPException(status_code=404)
    if not user.is_admin and conv_req.user_id != user.id:
        raise HTTPException(status_code=403)

    from .. import app_settings

    profanity_defaults = {
        "profanity_padding_ms": app_settings.get(db, "profanity_padding_ms"),
        "whisper_model": app_settings.get(db, "whisper_model"),
    }
    nudity_defaults = {
        "nudity_confidence": app_settings.get(db, "nudity_confidence"),
        "nudity_sample_fps": app_settings.get(db, "nudity_sample_fps"),
        "nudity_padding_ms": app_settings.get(db, "nudity_padding_ms"),
        "nudity_scene_merge_gap_ms": app_settings.get(db, "nudity_scene_merge_gap_ms"),
        "nudity_categories": app_settings.get(db, "nudity_categories"),
        "nudity_detectors": app_settings.get(db, "nudity_detectors"),
        "nudity_ensemble_strategy": app_settings.get(db, "nudity_ensemble_strategy"),
        "nudity_temporal_enabled": app_settings.get(db, "nudity_temporal_enabled"),
        "nudity_temporal_window": app_settings.get(db, "nudity_temporal_window"),
        "nudity_temporal_min_flagged": app_settings.get(
            db, "nudity_temporal_min_flagged"
        ),
        "nudity_extraction_mode": app_settings.get(db, "nudity_extraction_mode"),
    }
    violence_defaults = {
        "violence_confidence": app_settings.get(db, "violence_confidence"),
        "violence_sample_fps": app_settings.get(db, "violence_sample_fps"),
        "violence_padding_ms": app_settings.get(db, "violence_padding_ms"),
        "violence_scene_merge_gap_ms": app_settings.get(
            db, "violence_scene_merge_gap_ms"
        ),
        "violence_categories": app_settings.get(db, "violence_categories"),
        "violence_detectors": app_settings.get(db, "violence_detectors"),
        "violence_ensemble_strategy": app_settings.get(
            db, "violence_ensemble_strategy"
        ),
        "violence_temporal_enabled": app_settings.get(db, "violence_temporal_enabled"),
        "violence_temporal_window": app_settings.get(db, "violence_temporal_window"),
        "violence_temporal_min_flagged": app_settings.get(
            db, "violence_temporal_min_flagged"
        ),
        "violence_extraction_mode": app_settings.get(db, "violence_extraction_mode"),
    }

    jobs_progress = {}
    has_active = False
    for job in conv_req.jobs:
        if job.status in (JobStatus.queued, JobStatus.running):
            has_active = True
        if job.progress_json:
            try:
                jobs_progress[job.id] = _json.loads(job.progress_json)
            except Exception:
                pass

    queued_ids = [j.id for j in conv_req.jobs if j.status == JobStatus.queued]
    queue_pos = _queue_positions(db, queued_ids)

    return templates.TemplateResponse(
        "requests/detail.html",
        {
            "request": request,
            "user": user,
            "conv_request": conv_req,
            "jobs": conv_req.jobs,
            "jobs_progress": jobs_progress,
            "has_active": has_active,
            "queue_positions": queue_pos,
            "profanity_defaults": profanity_defaults,
            "nudity_defaults": nudity_defaults,
            "violence_defaults": violence_defaults,
            "is_admin": user.is_admin,
        },
    )


@router.get("/requests/{req_id}/jobs-status", response_class=HTMLResponse)
async def request_jobs_status(
    request: Request,
    req_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    conv_req = (
        db.query(ConversionRequest).filter(ConversionRequest.id == req_id).first()
    )
    if not conv_req:
        raise HTTPException(status_code=404)
    if not user.is_admin and conv_req.user_id != user.id:
        raise HTTPException(status_code=403)

    jobs_progress = {}
    has_active = False
    for job in conv_req.jobs:
        if job.status in (JobStatus.queued, JobStatus.running):
            has_active = True
        if job.progress_json:
            try:
                jobs_progress[job.id] = _json.loads(job.progress_json)
            except Exception:
                pass

    queued_ids = [j.id for j in conv_req.jobs if j.status == JobStatus.queued]
    queue_pos = _queue_positions(db, queued_ids)

    return templates.TemplateResponse(
        "requests/_jobs_table.html",
        {
            "request": request,
            "conv_request": conv_req,
            "jobs": conv_req.jobs,
            "jobs_progress": jobs_progress,
            "has_active": has_active,
            "queue_positions": queue_pos,
            "is_admin": user.is_admin,
        },
    )


def _queue_positions(db: Session, job_ids: list[int]) -> dict[int, int]:
    """Return a dict of job_id → global queue position for queued jobs."""
    if not job_ids:
        return {}
    all_queued = (
        db.query(ConversionJob.id)
        .filter(ConversionJob.status == JobStatus.queued)
        .order_by(ConversionJob.priority.asc(), ConversionJob.created_at.asc())
        .all()
    )
    ordered = [row[0] for row in all_queued]
    return {jid: ordered.index(jid) + 1 for jid in job_ids if jid in ordered}


def _delete_job_files(job) -> None:
    """Delete the clean edition file and sidecar."""
    import re

    # Delete the output (clean edition) file
    if job.output_file:
        out = Path(job.output_file)
        if out.exists():
            out.unlink(missing_ok=True)

    # Delete the cleanmedia sidecar JSON
    if job.input_file:
        sidecar = Path(job.input_file).with_suffix(".cleanmedia.json")
        if sidecar.exists():
            sidecar.unlink(missing_ok=True)
        # Also check sidecar next to original (non-edition) path
        orig_stem = re.sub(
            r"\s*\{edition-[^}]+\}", "", Path(job.input_file).stem
        ).rstrip()
        orig_sidecar = Path(job.input_file).parent / (orig_stem + ".cleanmedia.json")
        if orig_sidecar.exists():
            orig_sidecar.unlink(missing_ok=True)


@router.post("/requests/{req_id}/delete")
async def delete_request(
    req_id: int,
    delete_files: bool = Form(False),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    conv_req = (
        db.query(ConversionRequest).filter(ConversionRequest.id == req_id).first()
    )
    if not conv_req:
        raise HTTPException(status_code=404)
    if not user.is_admin and conv_req.user_id != user.id:
        raise HTTPException(status_code=403)
    if any(j.status == JobStatus.running for j in conv_req.jobs):
        raise HTTPException(
            status_code=400, detail="Cannot delete a request with a running job."
        )

    if delete_files:
        for job in conv_req.jobs:
            _delete_job_files(job)

    # For uploads, remove the entire upload directory
    if (conv_req.source or "plex") == "upload":
        import shutil

        for job in conv_req.jobs:
            if job.input_file:
                upload_dir = Path(job.input_file).parent
                shutil.rmtree(upload_dir, ignore_errors=True)

    db.delete(conv_req)
    db.commit()
    return RedirectResponse("/requests", status_code=303)


@router.post("/requests/{req_id}/retry")
async def retry_request(
    req_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    conv_req = (
        db.query(ConversionRequest).filter(ConversionRequest.id == req_id).first()
    )
    if not conv_req:
        raise HTTPException(status_code=404)
    if not user.is_admin and conv_req.user_id != user.id:
        raise HTTPException(status_code=403)

    # For uploads, just re-queue failed/skipped jobs without Plex re-fetch
    if (conv_req.source or "plex") == "upload":
        for job in conv_req.jobs:
            if job.status in (JobStatus.failed, JobStatus.skipped):
                job.status = JobStatus.queued
                job.error_message = None
                job.log_output = None
                job.started_at = None
                job.finished_at = None
        conv_req.status = RequestStatus.queued
        db.commit()
        return RedirectResponse(f"/requests/{req_id}", status_code=303)

    client = PlexClient(db)
    try:
        item = client.get_item(conv_req.plex_key)
        leaves = _resolve_leaf_items(client, conv_req.plex_key, item)
    except PlexError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Remove failed/skipped jobs; keep completed/running/queued
    for job in list(conv_req.jobs):
        if job.status in (JobStatus.failed, JobStatus.skipped):
            db.delete(job)
    db.flush()

    # Reload remaining jobs to check which input files are covered
    db.refresh(conv_req)
    existing_files = {j.input_file for j in conv_req.jobs}

    for leaf in leaves:
        leaf_key = leaf.get("key", "").split("/")[-1]
        try:
            file_path = client.resolve_file_path(leaf, db=db)
        except PlexError:
            continue
        if file_path in existing_files:
            continue
        # Check not already queued/running in another request
        duplicate = (
            db.query(ConversionJob)
            .filter(
                ConversionJob.input_file == file_path,
                ConversionJob.status.in_([JobStatus.queued, JobStatus.running]),
            )
            .first()
        )
        job = ConversionJob(
            request_id=conv_req.id,
            plex_key=leaf_key,
            title=leaf.get("title", conv_req.title),
            input_file=file_path,
            output_file=None,
            status=JobStatus.skipped if duplicate else JobStatus.queued,
            error_message="Already queued or running." if duplicate else None,
        )
        db.add(job)

    conv_req.status = RequestStatus.queued
    db.commit()
    return RedirectResponse(f"/requests/{req_id}", status_code=303)


@router.post("/requests/{req_id}/edit")
async def edit_request(
    request: Request,
    req_id: int,
    filter_profanity: bool = Form(False),
    filter_nudity: bool = Form(False),
    filter_violence: bool = Form(False),
    use_whisper: bool = Form(False),
    use_bleep: bool = Form(False),
    nudity_confidence: float | None = Form(None),
    nudity_sample_fps: float | None = Form(None),
    nudity_padding_ms: int | None = Form(None),
    nudity_scene_merge_gap_ms: int | None = Form(None),
    profanity_padding_ms: int | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    conv_req = (
        db.query(ConversionRequest).filter(ConversionRequest.id == req_id).first()
    )
    if not conv_req:
        raise HTTPException(status_code=404)
    if not user.is_admin and conv_req.user_id != user.id:
        raise HTTPException(status_code=403)
    if not filter_profanity and not filter_nudity and not filter_violence:
        raise HTTPException(status_code=400, detail="Select at least one filter.")

    conv_req.filter_profanity = filter_profanity
    conv_req.filter_nudity = filter_nudity
    conv_req.use_whisper = use_whisper
    conv_req.use_bleep = use_bleep

    # Per-request profanity overrides
    form = await request.form()
    profanity_override_on = "profanity_padding_ms" in form
    if profanity_override_on:
        raw_words = str(form.get("profanity_extra_words", "")).strip()
        conv_req.profanity_extra_words_json = (
            _json.dumps(
                [w.strip().lower() for w in raw_words.splitlines() if w.strip()]
            )
            if raw_words
            else None
        )
        raw_phrases = str(form.get("profanity_extra_phrases", "")).strip()
        conv_req.profanity_extra_phrases_json = (
            _json.dumps(
                [p.strip().lower() for p in raw_phrases.splitlines() if p.strip()]
            )
            if raw_phrases
            else None
        )
        conv_req.profanity_padding_ms = profanity_padding_ms
        conv_req.whisper_model = (
            str(form.get("whisper_model_override", "")).strip() or None
        )
    else:
        conv_req.profanity_extra_words_json = None
        conv_req.profanity_extra_phrases_json = None
        conv_req.profanity_padding_ms = None
        conv_req.whisper_model = None

    # Per-request nudity overrides
    nudity_override_on = "nudity_confidence" in form
    if nudity_override_on:
        conv_req.nudity_confidence = nudity_confidence
        conv_req.nudity_sample_fps = nudity_sample_fps
        conv_req.nudity_padding_ms = nudity_padding_ms
        conv_req.nudity_scene_merge_gap_ms = nudity_scene_merge_gap_ms
        cats = form.getlist("nudity_category")
        conv_req.nudity_categories_json = _json.dumps(list(cats)) if cats else None
        dets = form.getlist("nudity_detector")
        conv_req.nudity_detectors_json = _json.dumps(list(dets)) if dets else None
        raw_strategy = str(form.get("nudity_ensemble_strategy", "")).strip()
        conv_req.nudity_ensemble_strategy = raw_strategy or None
        conv_req.nudity_temporal_enabled = "nudity_temporal_enabled" in form
        raw_tw = str(form.get("nudity_temporal_window", "")).strip()
        conv_req.nudity_temporal_window = int(raw_tw) if raw_tw else None
        raw_tmf = str(form.get("nudity_temporal_min_flagged", "")).strip()
        conv_req.nudity_temporal_min_flagged = int(raw_tmf) if raw_tmf else None
        raw_em = str(form.get("nudity_extraction_mode", "")).strip()
        conv_req.nudity_extraction_mode = raw_em or None
    else:
        conv_req.nudity_confidence = None
        conv_req.nudity_sample_fps = None
        conv_req.nudity_padding_ms = None
        conv_req.nudity_scene_merge_gap_ms = None
        conv_req.nudity_categories_json = None
        conv_req.nudity_detectors_json = None
        conv_req.nudity_ensemble_strategy = None
        conv_req.nudity_temporal_enabled = None
        conv_req.nudity_temporal_window = None
        conv_req.nudity_temporal_min_flagged = None
        conv_req.nudity_extraction_mode = None

    conv_req.filter_violence = filter_violence

    # Per-request violence overrides
    violence_override_on = "violence_confidence" in form
    if violence_override_on:
        raw_vc = str(form.get("violence_confidence", "")).strip()
        conv_req.violence_confidence = float(raw_vc) if raw_vc else None
        raw_vfps = str(form.get("violence_sample_fps", "")).strip()
        conv_req.violence_sample_fps = float(raw_vfps) if raw_vfps else None
        raw_vpad = str(form.get("violence_padding_ms", "")).strip()
        conv_req.violence_padding_ms = int(raw_vpad) if raw_vpad else None
        raw_vmg = str(form.get("violence_scene_merge_gap_ms", "")).strip()
        conv_req.violence_scene_merge_gap_ms = int(raw_vmg) if raw_vmg else None
        cats = form.getlist("violence_category")
        conv_req.violence_categories_json = _json.dumps(list(cats)) if cats else None
        dets = form.getlist("violence_detector")
        conv_req.violence_detectors_json = _json.dumps(list(dets)) if dets else None
        raw_strategy = str(form.get("violence_ensemble_strategy", "")).strip()
        conv_req.violence_ensemble_strategy = raw_strategy or None
        conv_req.violence_temporal_enabled = "violence_temporal_enabled" in form
        raw_tw = str(form.get("violence_temporal_window", "")).strip()
        conv_req.violence_temporal_window = int(raw_tw) if raw_tw else None
        raw_tmf = str(form.get("violence_temporal_min_flagged", "")).strip()
        conv_req.violence_temporal_min_flagged = int(raw_tmf) if raw_tmf else None
        raw_em = str(form.get("violence_extraction_mode", "")).strip()
        conv_req.violence_extraction_mode = raw_em or None
    else:
        conv_req.violence_confidence = None
        conv_req.violence_sample_fps = None
        conv_req.violence_padding_ms = None
        conv_req.violence_scene_merge_gap_ms = None
        conv_req.violence_categories_json = None
        conv_req.violence_detectors_json = None
        conv_req.violence_ensemble_strategy = None
        conv_req.violence_temporal_enabled = None
        conv_req.violence_temporal_window = None
        conv_req.violence_temporal_min_flagged = None
        conv_req.violence_extraction_mode = None

    # Re-queue any failed or skipped jobs so they re-run with new settings
    for job in conv_req.jobs:
        if job.status in (JobStatus.failed, JobStatus.skipped):
            job.status = JobStatus.queued
            job.error_message = None
            job.log_output = None
            job.started_at = None
            job.finished_at = None

    if any(j.status == JobStatus.queued for j in conv_req.jobs):
        conv_req.status = RequestStatus.queued

    db.commit()
    return RedirectResponse(f"/requests/{req_id}", status_code=303)
