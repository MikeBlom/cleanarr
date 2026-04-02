"""Optional email sending for invite notifications."""

from __future__ import annotations

import smtplib
from email.mime.text import MIMEText

from .config import settings


def is_email_configured() -> bool:
    return bool(settings.SMTP_HOST and settings.SMTP_FROM)


def send_invite_email(to: str, invite_url: str) -> bool:
    """Send an invite email. Returns True on success, False on failure or not configured."""
    if not is_email_configured():
        return False

    body = (
        f"You've been invited to CleanArr!\n\n"
        f"Click the link below to set up your account:\n\n"
        f"{invite_url}\n\n"
        f"This link expires in 7 days."
    )
    msg = MIMEText(body)
    msg["Subject"] = "You're invited to CleanArr"
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            server.starttls()
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception:
        return False
