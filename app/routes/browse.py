from __future__ import annotations

import json

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy.orm import Session

from ..deps import get_db, require_user
from ..models import ConversionJob, ConversionRequest, JobStatus, RequestStatus, User
from ..plex.client import PlexClient, PlexError
from ..templates import templates

router = APIRouter(prefix="/browse")


def _cleaned_keys(db: Session) -> set[str]:
    job_keys = {r[0] for r in db.query(ConversionJob.plex_key).filter(ConversionJob.status == JobStatus.completed).all()}
    req_keys = {r[0] for r in db.query(ConversionRequest.plex_key).filter(
        ConversionRequest.status.in_([RequestStatus.complete, RequestStatus.partially_complete])
    ).all()}
    return job_keys | req_keys


def _parse_report(report_json: str | None) -> list[dict] | None:
    if not report_json:
        return None
    try:
        return json.loads(report_json)
    except Exception:
        return None


@router.get("", response_class=HTMLResponse)
async def browse_index(request: Request, db: Session = Depends(get_db), user: User = Depends(require_user)):
    client = PlexClient(db)
    try:
        libs = client.libraries()
    except PlexError as e:
        libs = []
        error = str(e)
    else:
        error = None
    return templates.TemplateResponse(
        "browse/index.html",
        {"request": request, "user": user, "libraries": libs, "error": error},
    )


@router.get("/section/{section_id}", response_class=HTMLResponse)
async def browse_section(
    request: Request,
    section_id: str,
    offset: int = 0,
    limit: int = 50,
    q: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    client = PlexClient(db)
    try:
        if q:
            items = client.search(section_id, q)
            total = len(items)
            if items:
                first_type = items[0].get("type", "movie")
                lib_type = "show" if first_type == "show" else "movie"
            else:
                container = client.library_items(section_id, offset=0, limit=1)
                lib_type = container.get("viewGroup", "movie")
        else:
            container = client.library_items(section_id, offset=offset, limit=limit)
            items = container.get("Metadata", [])
            total = container.get("totalSize", len(items))
            lib_type = container.get("viewGroup", "movie")
    except PlexError as e:
        raise HTTPException(status_code=502, detail=str(e))

    template = "browse/shows.html" if lib_type in ("show", "artist") else "browse/movies.html"
    return templates.TemplateResponse(
        template,
        {
            "request": request,
            "user": user,
            "items": items,
            "section_id": section_id,
            "offset": offset,
            "limit": limit,
            "total": total,
            "lib_type": lib_type,
            "q": q,
            "cleaned_keys": _cleaned_keys(db),
        },
    )


@router.get("/search", response_class=HTMLResponse)
async def global_search(request: Request, q: str = "", db: Session = Depends(get_db), user: User = Depends(require_user)):
    hubs: list[dict] = []
    error = None
    if q:
        client = PlexClient(db)
        try:
            raw = client.global_search(q)
            hubs = [h for h in raw if h.get("Metadata") and h.get("type") in ("movie", "show", "season", "episode")]
        except PlexError as e:
            error = str(e)
    return templates.TemplateResponse(
        "browse/search.html",
        {"request": request, "user": user, "q": q, "hubs": hubs, "error": error},
    )


@router.get("/item/{plex_key:path}/parental-guide", response_class=HTMLResponse)
def browse_item_parental_guide(
    request: Request,
    plex_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """HTMX fragment: fetch and render IMDB parental guide for an item.

    Sync def so FastAPI runs it in a thread pool (cinemagoer is blocking).
    """
    from ..imdb_service import extract_imdb_id_for_item, get_parental_guide

    client = PlexClient(db)
    try:
        item = client.get_item(plex_key)
    except PlexError:
        return HTMLResponse('<p class="muted">Could not load item data.</p>')

    imdb_id = extract_imdb_id_for_item(item, client)
    if not imdb_id:
        return HTMLResponse('<p class="muted">No IMDB data available for this title.</p>')

    guide = get_parental_guide(imdb_id, db)
    if not guide:
        return HTMLResponse('<p class="muted">No parental guide data available.</p>')

    return templates.TemplateResponse(
        "browse/_parental_guide.html",
        {"request": request, "guide": guide, "imdb_id": imdb_id},
    )


@router.get("/item/{plex_key:path}/request-form", response_class=HTMLResponse)
async def request_form(
    request: Request,
    plex_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """HTMX fragment: return the request form shell with disabled controls.

    The AI advice endpoint is triggered automatically from within this template
    and will OOB-swap the filter sections + enable the submit button.
    """
    client = PlexClient(db)
    try:
        item = client.get_item(plex_key)
    except PlexError as e:
        raise HTTPException(status_code=502, detail=str(e))

    audio_streams = client.get_audio_streams(item)

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
        "nudity_temporal_min_flagged": app_settings.get(db, "nudity_temporal_min_flagged"),
        "nudity_extraction_mode": app_settings.get(db, "nudity_extraction_mode"),
    }
    violence_defaults = {
        "violence_confidence": app_settings.get(db, "violence_confidence"),
        "violence_sample_fps": app_settings.get(db, "violence_sample_fps"),
        "violence_padding_ms": app_settings.get(db, "violence_padding_ms"),
        "violence_scene_merge_gap_ms": app_settings.get(db, "violence_scene_merge_gap_ms"),
        "violence_categories": app_settings.get(db, "violence_categories"),
        "violence_detectors": app_settings.get(db, "violence_detectors"),
        "violence_ensemble_strategy": app_settings.get(db, "violence_ensemble_strategy"),
        "violence_temporal_enabled": app_settings.get(db, "violence_temporal_enabled"),
        "violence_temporal_window": app_settings.get(db, "violence_temporal_window"),
        "violence_temporal_min_flagged": app_settings.get(db, "violence_temporal_min_flagged"),
        "violence_extraction_mode": app_settings.get(db, "violence_extraction_mode"),
    }

    return templates.TemplateResponse(
        "browse/_request_form.html",
        {
            "request": request,
            "plex_key": plex_key,
            "item": item,
            "audio_streams": audio_streams,
            "profanity_defaults": profanity_defaults,
            "nudity_defaults": nudity_defaults,
            "violence_defaults": violence_defaults,
        },
    )


@router.get("/item/{plex_key:path}/ai-filter-advice", response_class=HTMLResponse)
def ai_filter_advice(
    request: Request,
    plex_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """HTMX fragment: AI evaluates IMDB data, returns OOB swaps for filter sections.

    Sync def so FastAPI runs it in a threadpool (Ollama call is blocking).
    """
    from .. import app_settings as _as
    from ..content_advisor import evaluate_nudity, evaluate_profanity, evaluate_violence
    from ..imdb_service import extract_imdb_id_for_item, get_parental_guide

    client = PlexClient(db)
    try:
        item = client.get_item(plex_key)
    except PlexError:
        return HTMLResponse("")

    nudity_rec = None
    profanity_rec = None
    violence_rec = None
    ai_enabled = _as.get(db, "ai_advisor_enabled").lower() == "true"

    if ai_enabled:
        imdb_id = extract_imdb_id_for_item(item, client)
        if imdb_id:
            guide = get_parental_guide(imdb_id, db)
            if guide:
                ollama_url = _as.get(db, "ollama_url")
                ollama_model = _as.get(db, "ollama_model")
                nudity_rec = evaluate_nudity(guide, ollama_url, ollama_model)
                profanity_rec = evaluate_profanity(guide, ollama_url, ollama_model)
                violence_rec = evaluate_violence(guide, ollama_url, ollama_model)

    return templates.TemplateResponse(
        "browse/_ai_filter_advice.html",
        {
            "request": request,
            "nudity_rec": nudity_rec,
            "profanity_rec": profanity_rec,
            "violence_rec": violence_rec,
        },
    )


@router.get("/item/{plex_key:path}/job-progress", response_class=HTMLResponse)
async def browse_item_job_progress(
    request: Request,
    plex_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    """HTMX fragment: returns live job progress for an item."""
    key = str(plex_key).split("/")[-1]

    active_jobs = (
        db.query(ConversionJob)
        .filter(ConversionJob.plex_key == key, ConversionJob.status.in_([JobStatus.queued, JobStatus.running]))
        .all()
    )
    # For show/season views, also find active jobs via requests
    if not active_jobs:
        active_req_ids = [
            r[0] for r in db.query(ConversionRequest.id)
            .filter(
                ConversionRequest.plex_key == key,
                ConversionRequest.status.in_([RequestStatus.queued, RequestStatus.partially_complete]),
            )
            .all()
        ]
        if active_req_ids:
            active_jobs = (
                db.query(ConversionJob)
                .filter(ConversionJob.request_id.in_(active_req_ids), ConversionJob.status.in_([JobStatus.queued, JobStatus.running]))
                .all()
            )

    # Also include recently completed jobs (so progress shows final state before disappearing)
    if not active_jobs:
        recent_jobs = (
            db.query(ConversionJob)
            .filter(ConversionJob.plex_key == key, ConversionJob.status.in_([JobStatus.completed, JobStatus.failed]))
            .order_by(ConversionJob.finished_at.desc())
            .limit(1)
            .all()
        )
        # Only show if finished in the last 10 seconds (gives polling time to show final state)
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        for j in recent_jobs:
            if j.finished_at and (now - j.finished_at.replace(tzinfo=timezone.utc)) < timedelta(seconds=10):
                active_jobs = [j]

    jobs_progress = {}
    has_active = any(j.status in (JobStatus.queued, JobStatus.running) for j in active_jobs)
    for job in active_jobs:
        if job.progress_json:
            try:
                jobs_progress[job.id] = json.loads(job.progress_json)
            except Exception:
                pass

    return templates.TemplateResponse(
        "browse/_job_progress.html",
        {
            "request": request,
            "plex_key": plex_key,
            "active_jobs": active_jobs,
            "jobs_progress": jobs_progress,
            "has_active": has_active,
        },
    )


@router.get("/item/{plex_key:path}", response_class=HTMLResponse)
async def browse_item(
    request: Request,
    plex_key: str,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    client = PlexClient(db)
    try:
        item = client.get_item(plex_key)
        item_type = item.get("type", "movie")
        children: list[dict] = []
        if item_type in ("show", "season"):
            children = client.get_children(plex_key)
    except PlexError as e:
        raise HTTPException(status_code=502, detail=str(e))

    key = str(plex_key).split("/")[-1]

    # Most recent completed job for this item (for content report)
    last_job = (
        db.query(ConversionJob)
        .filter(ConversionJob.plex_key == key, ConversionJob.status == JobStatus.completed)
        .order_by(ConversionJob.finished_at.desc())
        .first()
    )
    has_clean = last_job is not None
    content_report = _parse_report(last_job.content_report) if last_job else None

    # Cleaned keys for children
    child_keys = {str(c.get("ratingKey")) for c in children}
    child_cleaned: set[str] = set()
    if child_keys:
        child_cleaned = {
            r[0] for r in db.query(ConversionJob.plex_key)
            .filter(ConversionJob.plex_key.in_(child_keys), ConversionJob.status == JobStatus.completed)
            .all()
        }
        child_cleaned |= {
            r[0] for r in db.query(ConversionRequest.plex_key)
            .filter(ConversionRequest.plex_key.in_(child_keys),
                    ConversionRequest.status.in_([RequestStatus.complete, RequestStatus.partially_complete]))
            .all()
        }

    # Audio streams (for movie/episode items that have media info)
    audio_streams = client.get_audio_streams(item)

    # Active jobs for progress display
    active_jobs = (
        db.query(ConversionJob)
        .filter(ConversionJob.plex_key == key, ConversionJob.status.in_([JobStatus.queued, JobStatus.running]))
        .all()
    )
    # For show/season views, also find active jobs via requests
    if not active_jobs and item_type in ("show", "season"):
        active_req_ids = [
            r[0] for r in db.query(ConversionRequest.id)
            .filter(
                ConversionRequest.plex_key == key,
                ConversionRequest.status.in_([RequestStatus.queued, RequestStatus.partially_complete]),
            )
            .all()
        ]
        if active_req_ids:
            active_jobs = (
                db.query(ConversionJob)
                .filter(ConversionJob.request_id.in_(active_req_ids), ConversionJob.status.in_([JobStatus.queued, JobStatus.running]))
                .all()
            )

    jobs_progress = {}
    has_active = False
    for job in active_jobs:
        if job.status in (JobStatus.queued, JobStatus.running):
            has_active = True
        if job.progress_json:
            try:
                jobs_progress[job.id] = json.loads(job.progress_json)
            except Exception:
                pass

    return templates.TemplateResponse(
        "browse/item.html",
        {
            "request": request,
            "user": user,
            "item": item,
            "children": children,
            "plex_key": plex_key,
            "has_clean": has_clean,
            "content_report": content_report,
            "child_cleaned": child_cleaned,
            "audio_streams": audio_streams,
            "active_jobs": active_jobs,
            "jobs_progress": jobs_progress,
            "has_active": has_active,
        },
    )


# Thumbnail proxy — mounted at app level (not under /browse prefix)
thumb_router = APIRouter()

import hashlib
from pathlib import Path as _Path

_THUMB_CACHE_DIR = _Path("/data/thumb_cache")


@thumb_router.get("/plex-thumb")
async def plex_thumb(url: str, db: Session = Depends(get_db)):
    """Proxy a Plex thumbnail, cached to disk permanently."""
    from .. import app_settings as _as
    if not url.startswith("/"):
        raise HTTPException(status_code=400)

    # Stable cache key from the URL (includes the timestamp Plex appends on art changes)
    cache_key = hashlib.sha1(url.encode()).hexdigest()
    cache_file = _THUMB_CACHE_DIR / f"{cache_key}.jpg"

    if cache_file.exists():
        return Response(
            content=cache_file.read_bytes(),
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=31536000"},
        )

    plex_url = f"{_as.get(db, 'plex_server_url').rstrip('/')}{url}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                plex_url,
                params={"X-Plex-Token": _as.get(db, "plex_admin_token")},
                timeout=10,
            )
            resp.raise_for_status()
    except httpx.HTTPError:
        raise HTTPException(status_code=502)

    _THUMB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file.write_bytes(resp.content)

    content_type = resp.headers.get("content-type", "image/jpeg")
    return Response(
        content=resp.content,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=31536000"},
    )
