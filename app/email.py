"""Optional email sending for invites and job notifications."""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

from .config import settings


def _get_smtp_config(db=None) -> dict:
    """Return SMTP config, preferring DB settings over env vars."""
    if db:
        from . import app_settings

        host = app_settings.get(db, "smtp_host")
        port = app_settings.get(db, "smtp_port")
        user = app_settings.get(db, "smtp_user")
        password = app_settings.get(db, "smtp_password")
        from_addr = app_settings.get(db, "smtp_from")
        # Use DB values if host is set, otherwise fall back to env vars
        if host:
            return {
                "host": host,
                "port": int(port) if port else 587,
                "user": user,
                "password": password,
                "from_addr": from_addr,
            }
    return {
        "host": settings.SMTP_HOST,
        "port": settings.SMTP_PORT,
        "user": settings.SMTP_USER,
        "password": settings.SMTP_PASSWORD,
        "from_addr": settings.SMTP_FROM,
    }


def is_email_configured(db=None) -> bool:
    cfg = _get_smtp_config(db)
    return bool(cfg["host"] and cfg["from_addr"])


def _send(to: str, subject: str, body: str, db=None) -> bool:
    cfg = _get_smtp_config(db)
    if not cfg["host"] or not cfg["from_addr"]:
        return False

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = cfg["from_addr"]
    msg["To"] = to

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as server:
            server.starttls()
            if cfg["user"]:
                server.login(cfg["user"], cfg["password"])
            server.send_message(msg)
        return True
    except Exception:
        return False


def send_invite_email(to: str, invite_url: str, db=None) -> bool:
    """Send an invite email. Returns True on success."""
    body = (
        f"You've been invited to CleanArr!\n\n"
        f"Click the link below to set up your account:\n\n"
        f"{invite_url}\n\n"
        f"This link expires in 7 days."
    )
    return _send(to, "You're invited to CleanArr", body, db=db)


def send_notification_email(to: str, subject: str, body: str, db=None) -> bool:
    """Send a notification email. Returns True on success."""
    return _send(to, subject, body, db=db)
