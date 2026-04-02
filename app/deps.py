from __future__ import annotations

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .auth.sessions import get_session
from .config import settings
from .database import SessionLocal
from .models import User


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _get_session_user(request: Request, db: Session) -> User | None:
    """Return the actual session user, ignoring masquerade."""
    token = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not token:
        return None
    session = get_session(db, token)
    if not session:
        return None
    return session.user


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    real_user = _get_session_user(request, db)
    if not real_user:
        return None

    # Admin masquerade: if cookie set and user is admin, return target user
    masq_id = request.cookies.get("cleanarr_masquerade")
    if masq_id and real_user.is_admin:
        try:
            target = db.query(User).filter(User.id == int(masq_id)).first()
            if target:
                return target
        except (ValueError, TypeError):
            pass

    return real_user


def get_real_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User | None:
    """Always returns the actual session user, ignoring masquerade."""
    return _get_session_user(request, db)


def require_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    if not user.is_approved:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account pending approval.")
    return user


def require_admin(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    """Check admin status on the REAL user, not the masqueraded one."""
    user = _get_session_user(request, db)
    if user is None:
        raise HTTPException(status_code=status.HTTP_302_FOUND, headers={"Location": "/login"})
    if not user.is_approved:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account pending approval.")
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required.")
    return user
