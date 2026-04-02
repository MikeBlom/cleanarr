from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth.password import hash_password, verify_password
from ..auth.plex import create_pin, fetch_server_users, fetch_user_info, plex_auth_url, poll_pin
from ..auth.sessions import create_session, destroy_session, set_flash
from ..config import settings
from ..database import SessionLocal
from ..deps import get_current_user, get_db
from ..models import Invitation, User
from ..templates import templates

router = APIRouter()


def _has_any_users(db: Session) -> bool:
    return db.query(User.id).first() is not None


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db), user=Depends(get_current_user)):
    if not _has_any_users(db):
        return RedirectResponse("/setup", status_code=302)
    if user and user.is_approved:
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "user": user})


@router.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, db: Session = Depends(get_db)):
    if _has_any_users(db):
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("setup.html", {"request": request, "user": None})


@router.post("/setup")
async def setup_create(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    if _has_any_users(db):
        return RedirectResponse("/login", status_code=302)

    errors = []
    if not username.strip():
        errors.append("Username is required.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if password != password_confirm:
        errors.append("Passwords do not match.")

    if errors:
        return templates.TemplateResponse("setup.html", {
            "request": request, "user": None,
            "errors": errors, "username": username,
        })

    user = User(
        username=username.strip(),
        auth_method="local",
        password_hash=hash_password(password),
        is_admin=True,
        is_approved=True,
    )
    db.add(user)
    db.commit()
    return RedirectResponse("/login", status_code=302)


@router.post("/auth/local")
async def local_login(
    request: Request,
    db: Session = Depends(get_db),
    username: str = Form(...),
    password: str = Form(...),
):
    user = db.query(User).filter(
        User.username == username,
        User.auth_method == "local",
    ).first()

    if not user or not user.password_hash or not verify_password(password, user.password_hash):
        return RedirectResponse("/login?error=invalid", status_code=302)

    user.last_login = datetime.utcnow()
    db.commit()
    db.refresh(user)

    redirect = RedirectResponse("/", status_code=302)
    create_session(db, user, redirect)
    return redirect


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
    invite_token: str | None = Cookie(default=None),
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

    # Check if this is an invite-based sign-up
    invited = False
    if invite_token:
        invitation = db.query(Invitation).filter(
            Invitation.token == invite_token,
            Invitation.accepted_at.is_(None),
            Invitation.expires_at > datetime.utcnow(),
        ).first()
        if invitation:
            invited = True
            invitation.accepted_at = datetime.utcnow()

    user = db.query(User).filter(User.plex_id == plex_id).first()
    is_admin = plex_id in settings.admin_plex_ids

    # For new users: verify they're a member of the Plex server (unless admin or invited)
    if user is None and not is_admin and not invited:
        from .. import app_settings as _as
        server_url = _as.get(db, "plex_server_url")
        admin_token = _as.get(db, "plex_admin_token")
        try:
            server_users = fetch_server_users(server_url, admin_token)
            server_plex_ids = {u["id"] for u in server_users}
        except Exception:
            server_plex_ids = set()
        if plex_id not in server_plex_ids:
            redirect = RedirectResponse("/login?error=not_invited", status_code=302)
            redirect.delete_cookie("plex_pin_id")
            return redirect

    if user is None:
        user = User(
            plex_id=plex_id,
            username=username,
            email=email,
            auth_method="plex",
            is_admin=is_admin,
            is_approved=is_admin or invited,
        )
        db.add(user)
    else:
        user.username = username
        user.email = email
        if is_admin:
            user.is_admin = True
            user.is_approved = True
        if invited and not user.is_approved:
            user.is_approved = True

    user.last_login = datetime.utcnow()
    db.commit()
    db.refresh(user)

    redirect = RedirectResponse("/", status_code=302)
    redirect.delete_cookie("plex_pin_id")
    if invite_token:
        redirect.delete_cookie("invite_token")
    create_session(db, user, redirect)
    if invited:
        set_flash(redirect, "Welcome to CleanArr!", "success")
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


@router.get("/invite/{token}", response_class=HTMLResponse)
async def invite_accept_page(request: Request, token: str, db: Session = Depends(get_db)):
    invitation = db.query(Invitation).filter(
        Invitation.token == token,
        Invitation.accepted_at.is_(None),
        Invitation.expires_at > datetime.utcnow(),
    ).first()
    if not invitation:
        return templates.TemplateResponse("invite_accept.html", {
            "request": request, "user": None, "invitation": None, "error": "This invite link is invalid or has expired.",
        })
    return templates.TemplateResponse("invite_accept.html", {
        "request": request, "user": None, "invitation": invitation,
    })


@router.post("/invite/{token}/local")
async def invite_accept_local(
    request: Request,
    token: str,
    db: Session = Depends(get_db),
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    invitation = db.query(Invitation).filter(
        Invitation.token == token,
        Invitation.accepted_at.is_(None),
        Invitation.expires_at > datetime.utcnow(),
    ).first()
    if not invitation:
        return RedirectResponse(f"/invite/{token}", status_code=302)

    errors = []
    if not username.strip():
        errors.append("Username is required.")
    if len(password) < 8:
        errors.append("Password must be at least 8 characters.")
    if password != password_confirm:
        errors.append("Passwords do not match.")
    existing = db.query(User).filter(User.username == username.strip(), User.auth_method == "local").first()
    if existing:
        errors.append("That username is already taken.")

    if errors:
        return templates.TemplateResponse("invite_accept.html", {
            "request": request, "user": None, "invitation": invitation,
            "errors": errors, "form_username": username,
        })

    user = User(
        username=username.strip(),
        email=invitation.email,
        auth_method="local",
        password_hash=hash_password(password),
        is_approved=True,
    )
    db.add(user)
    invitation.accepted_at = datetime.utcnow()
    db.commit()
    db.refresh(user)

    redirect = RedirectResponse("/", status_code=302)
    create_session(db, user, redirect)
    set_flash(redirect, "Welcome to CleanArr!", "success")
    return redirect


@router.post("/invite/{token}/plex")
async def invite_accept_plex(request: Request, token: str, db: Session = Depends(get_db)):
    invitation = db.query(Invitation).filter(
        Invitation.token == token,
        Invitation.accepted_at.is_(None),
        Invitation.expires_at > datetime.utcnow(),
    ).first()
    if not invitation:
        return RedirectResponse(f"/invite/{token}", status_code=302)

    pin_id, pin_code = create_pin()
    callback_url = f"{settings.BASE_URL}/auth/plex/callback"
    auth_url = plex_auth_url(pin_code, callback_url)

    redirect = RedirectResponse(auth_url, status_code=302)
    redirect.set_cookie("plex_pin_id", str(pin_id), max_age=600, httponly=True, samesite="lax")
    redirect.set_cookie("invite_token", token, max_age=600, httponly=True, samesite="lax")
    return redirect


@router.get("/pending", response_class=HTMLResponse)
async def pending_page(request: Request, user=Depends(get_current_user)):
    if user is None:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("pending.html", {"request": request, "user": user})
