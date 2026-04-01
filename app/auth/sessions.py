from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from fastapi import Response
from sqlalchemy.orm import Session

from ..config import settings
from ..models import User, UserSession


def create_session(db: Session, user: User, response: Response) -> UserSession:
    token = secrets.token_urlsafe(48)
    csrf_token = secrets.token_urlsafe(32)
    expires_at = datetime.utcnow() + timedelta(days=settings.SESSION_MAX_AGE_DAYS)

    session = UserSession(
        token=token,
        user_id=user.id,
        csrf_token=csrf_token,
        expires_at=expires_at,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.SESSION_MAX_AGE_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=settings.BASE_URL.startswith("https"),
    )
    return session


def destroy_session(db: Session, token: str, response: Response) -> None:
    session = db.query(UserSession).filter(UserSession.token == token).first()
    if session:
        db.delete(session)
        db.commit()
    response.delete_cookie(settings.SESSION_COOKIE_NAME)


def get_session(db: Session, token: str) -> UserSession | None:
    session = (
        db.query(UserSession)
        .filter(UserSession.token == token, UserSession.expires_at > datetime.utcnow())
        .first()
    )
    return session
