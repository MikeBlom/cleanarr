from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth.plex import create_pin, fetch_user_info, plex_auth_url, poll_pin
from ..auth.sessions import create_session, destroy_session
from ..config import settings
from ..database import SessionLocal
from ..deps import get_current_user, get_db
from ..models import User
from ..templates import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, user=Depends(get_current_user)):
    if user and user.is_approved:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "user": user})


@router.post("/auth/plex/start")
async def plex_start(request: Request, response: Response):
    pin_id, pin_code = create_pin()
    callback_url = f"{settings.BASE_URL}/auth/plex/callback"
    auth_url = plex_auth_url(pin_code, callback_url)

    redirect = RedirectResponse(auth_url, status_code=302)
    redirect.set_cookie("plex_pin_id", str(pin_id), max_age=600, httponly=True, samesite="lax")
    return redirect


@router.get("/auth/plex/callback")
async def plex_callback(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    plex_pin_id: str | None = Cookie(default=None),
):
    if not plex_pin_id:
        return RedirectResponse("/login?error=no_pin", status_code=302)

    try:
        pin_id = int(plex_pin_id)
    except ValueError:
        return RedirectResponse("/login?error=bad_pin", status_code=302)

    auth_token = poll_pin(pin_id)
    if not auth_token:
        return RedirectResponse("/login?error=timeout", status_code=302)

    try:
        info = fetch_user_info(auth_token)
    except Exception:
        return RedirectResponse("/login?error=user_fetch", status_code=302)

    plex_id = str(info.get("id", ""))
    username = info.get("username") or info.get("title") or "Unknown"
    email = info.get("email")

    user = db.query(User).filter(User.plex_id == plex_id).first()
    is_admin = plex_id in settings.admin_plex_ids

    if user is None:
        user = User(
            plex_id=plex_id,
            username=username,
            email=email,
            is_admin=is_admin,
            is_approved=is_admin,
        )
        db.add(user)
    else:
        user.username = username
        user.email = email
        if is_admin:
            user.is_admin = True
            user.is_approved = True

    user.last_login = datetime.utcnow()
    db.commit()
    db.refresh(user)

    redirect = RedirectResponse("/", status_code=302)
    redirect.delete_cookie("plex_pin_id")
    create_session(db, user, redirect)
    return redirect


@router.post("/logout")
async def logout(
    request: Request,
    db: Session = Depends(get_db),
):
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    redirect = RedirectResponse("/login", status_code=302)
    if token:
        destroy_session(db, token, redirect)
    return redirect


@router.get("/pending", response_class=HTMLResponse)
async def pending_page(request: Request, user=Depends(get_current_user)):
    if user is None:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("pending.html", {"request": request, "user": user})
