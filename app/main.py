from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db
from .routes import admin, auth, browse, jobs, notifications, requests, uploads
from .templates import templates


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.WORKER_ENABLED:
        from .worker import start_worker

        start_worker()
    yield


app = FastAPI(title="CleanArr", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    from .auth.sessions import set_flash

    redirect = RedirectResponse("/", status_code=302)
    set_flash(redirect, "The page you were looking for was not found.", "info")
    return redirect


app.mount(
    "/static",
    StaticFiles(directory=str(Path(__file__).parent / "static")),
    name="static",
)

app.include_router(auth.router)
app.include_router(browse.router)
app.include_router(browse.thumb_router)
app.include_router(requests.router)
app.include_router(jobs.router)
app.include_router(uploads.router)
app.include_router(notifications.router)
app.include_router(admin.router)


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return RedirectResponse("/static/favicon.ico", status_code=301)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    import json as _json
    from sqlalchemy.orm import joinedload
    from .deps import get_current_user
    from .database import SessionLocal
    from .models import (
        ConversionRequest,
        JobStatus,
        RequestStatus,
        User,
    )

    db = SessionLocal()
    try:
        has_users = db.query(User.id).first() is not None
        if not has_users:
            return RedirectResponse("/setup", status_code=302)
        user = get_current_user(request, db)
        if user is None:
            return RedirectResponse("/login", status_code=302)
        if not user.is_approved:
            return RedirectResponse("/pending", status_code=302)

        completed_requests = (
            db.query(ConversionRequest)
            .options(joinedload(ConversionRequest.jobs))
            .filter(
                ConversionRequest.status.in_(
                    [RequestStatus.complete, RequestStatus.partially_complete]
                )
            )
            .order_by(ConversionRequest.updated_at.desc())
            .all()
        )

        cleaned_movies = []
        for req in completed_requests:
            counts = {"profanity": 0, "nudity": 0, "violence": 0}
            for job in req.jobs:
                if job.status != JobStatus.completed or not job.content_report:
                    continue
                try:
                    report = _json.loads(job.content_report)
                except Exception:
                    continue
                for entry in report:
                    entry_type = entry.get("type", "")
                    if entry_type in counts:
                        counts[entry_type] += 1
            cleaned_movies.append(
                {
                    "request_id": req.id,
                    "title": req.title,
                    "profanity_count": counts["profanity"],
                    "nudity_count": counts["nudity"],
                    "violence_count": counts["violence"],
                }
            )

        return templates.TemplateResponse(
            "dashboard.html",
            {"request": request, "user": user, "cleaned_movies": cleaned_movies},
        )
    finally:
        db.close()
