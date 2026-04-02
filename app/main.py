from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import init_db
from .routes import admin, auth, browse, jobs, requests
from .templates import templates
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.WORKER_ENABLED:
        from .worker import start_worker
        start_worker()
    yield


app = FastAPI(title="CleanArr", lifespan=lifespan, docs_url=None, redoc_url=None)

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
app.include_router(admin.router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    from .deps import get_current_user
    from .database import SessionLocal
    db = SessionLocal()
    try:
        user = get_current_user(request, db)
    finally:
        db.close()

    if user is None:
        return RedirectResponse("/login", status_code=302)
    if not user.is_approved:
        return RedirectResponse("/pending", status_code=302)
    return templates.TemplateResponse("dashboard.html", {"request": request, "user": user})
