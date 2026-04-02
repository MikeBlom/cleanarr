from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from ..auth.sessions import set_flash
from ..deps import get_db, require_user
from ..email import is_email_configured
from ..models import Notification, User
from ..templates import templates

router = APIRouter(prefix="/notifications")


@router.get("/count", response_class=HTMLResponse)
async def notification_count(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    count = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.is_read.is_(False))
        .count()
    )
    return templates.TemplateResponse(
        "notifications/_count.html", {"request": request, "count": count}
    )


@router.get("", response_class=HTMLResponse)
async def notification_list(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    notifications = (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )
    return templates.TemplateResponse(
        "notifications/list.html",
        {"request": request, "user": user, "notifications": notifications},
    )


@router.post("/{notif_id}/read")
async def mark_read(
    notif_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    notif = db.query(Notification).filter(Notification.id == notif_id).first()
    if not notif or notif.user_id != user.id:
        raise HTTPException(status_code=404)
    notif.is_read = True
    db.commit()
    return RedirectResponse("/notifications", status_code=303)


@router.post("/read-all")
async def mark_all_read(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
):
    db.query(Notification).filter(
        Notification.user_id == user.id, Notification.is_read.is_(False)
    ).update({"is_read": True})
    db.commit()
    return RedirectResponse("/notifications", status_code=303)


@router.get("/preferences", response_class=HTMLResponse)
async def notification_preferences(
    request: Request,
    user: User = Depends(require_user),
):
    return templates.TemplateResponse(
        "notifications/preferences.html",
        {
            "request": request,
            "user": user,
            "email_configured": is_email_configured(),
            "saved": request.query_params.get("saved"),
        },
    )


@router.post("/preferences")
async def save_notification_preferences(
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
    notify_email: bool = Form(False),
    notify_webhook: bool = Form(False),
    notify_inapp: bool = Form(False),
    webhook_url: str = Form(""),
):
    user.notify_email = notify_email
    user.notify_webhook = notify_webhook
    user.notify_inapp = notify_inapp
    user.webhook_url = webhook_url.strip() or None
    db.commit()
    redirect = RedirectResponse("/notifications/preferences?saved=1", status_code=303)
    set_flash(redirect, "Notification preferences saved.", "success")
    return redirect
