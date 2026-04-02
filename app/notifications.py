"""Notification dispatch — called from the worker after request status rollup."""

from __future__ import annotations

import json
import logging
from urllib.error import URLError
from urllib.request import Request as URLRequest, urlopen

from sqlalchemy.orm import Session

from . import app_settings
from .email import send_notification_email
from .models import ConversionRequest, Notification, RequestStatus, User

log = logging.getLogger(__name__)


def notify_request_status_change(
    db: Session,
    request: ConversionRequest,
    new_status: RequestStatus,
) -> None:
    """Dispatch notifications for a request status change.

    Called from _rollup_request() after the status is committed.
    Only fires for terminal statuses (complete, failed, partially_complete).
    """
    if new_status == RequestStatus.complete:
        if app_settings.get(db, "notification_on_complete") != "true":
            return
    elif new_status == RequestStatus.failed:
        if app_settings.get(db, "notification_on_failed") != "true":
            return
    elif new_status == RequestStatus.partially_complete:
        if app_settings.get(db, "notification_on_partial") != "true":
            return
    else:
        return

    user = request.user
    if not user:
        return

    title, message = _build_message(request, new_status)

    if user.notify_inapp:
        _send_inapp(db, user, request, title, message)

    if user.notify_email and user.email:
        send_notification_email(user.email, f"CleanArr: {title}", message)

    webhook_fmt = app_settings.get(db, "notification_webhook_format")

    if user.notify_webhook and user.webhook_url:
        _send_webhook(user.webhook_url, title, message, webhook_fmt)

    global_url = app_settings.get(db, "notification_webhook_url")
    if global_url:
        _send_webhook(global_url, title, message, webhook_fmt)


def _build_message(
    request: ConversionRequest,
    status: RequestStatus,
) -> tuple[str, str]:
    status_labels = {
        RequestStatus.complete: "completed",
        RequestStatus.failed: "failed",
        RequestStatus.partially_complete: "partially completed",
    }
    label = status_labels.get(status, str(status.value))
    title = f"Request {label}: {request.title}"

    job_count = len(request.jobs)
    completed = sum(
        1 for j in request.jobs if j.status.value in ("completed", "already_exists")
    )
    failed = sum(1 for j in request.jobs if j.status.value == "failed")

    message = f'Your request "{request.title}" has {label}.\n'
    message += f"Jobs: {completed}/{job_count} succeeded"
    if failed:
        message += f", {failed} failed"
    message += "."
    return title, message


def _send_inapp(
    db: Session,
    user: User,
    request: ConversionRequest,
    title: str,
    message: str,
) -> None:
    notif = Notification(
        user_id=user.id,
        request_id=request.id,
        title=title,
        message=message,
    )
    db.add(notif)
    db.commit()


def _send_webhook(url: str, title: str, message: str, fmt: str = "discord") -> None:
    if fmt == "discord":
        payload = json.dumps({"content": f"**{title}**\n{message}"})
    else:
        payload = json.dumps({"title": title, "message": message})

    req = URLRequest(url, data=payload.encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        with urlopen(req, timeout=10):
            pass
    except (URLError, Exception):
        log.exception("Failed to send webhook to %s", url)
