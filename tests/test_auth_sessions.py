from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import Response

from app.auth.sessions import create_session, destroy_session, get_session
from app.models import User, UserSession


def test_create_session_stores_in_db(db_session):
    user = User(username="sess_user", is_approved=True)
    db_session.add(user)
    db_session.flush()

    response = Response()
    sess = create_session(db_session, user, response)

    assert sess.id is not None
    assert sess.user_id == user.id
    assert len(sess.token) > 10
    assert len(sess.csrf_token) > 10
    fetched = db_session.query(UserSession).filter_by(id=sess.id).first()
    assert fetched is not None


def test_destroy_session_removes_from_db(db_session):
    user = User(username="sess_user2", is_approved=True)
    db_session.add(user)
    db_session.flush()

    response = Response()
    sess = create_session(db_session, user, response)
    token = sess.token

    response2 = Response()
    destroy_session(db_session, token, response2)

    assert db_session.query(UserSession).filter_by(token=token).first() is None


def test_get_session_valid(db_session):
    user = User(username="sess_user3", is_approved=True)
    db_session.add(user)
    db_session.flush()

    session = UserSession(
        token="valid_token_123",
        user_id=user.id,
        csrf_token="csrf_123",
        expires_at=datetime.utcnow() + timedelta(days=1),
    )
    db_session.add(session)
    db_session.flush()

    result = get_session(db_session, "valid_token_123")
    assert result is not None
    assert result.user_id == user.id


def test_get_session_expired(db_session):
    user = User(username="sess_user4", is_approved=True)
    db_session.add(user)
    db_session.flush()

    session = UserSession(
        token="expired_token_123",
        user_id=user.id,
        csrf_token="csrf_456",
        expires_at=datetime.utcnow() - timedelta(days=1),
    )
    db_session.add(session)
    db_session.flush()

    result = get_session(db_session, "expired_token_123")
    assert result is None


def test_get_session_invalid_token(db_session):
    result = get_session(db_session, "nonexistent_token")
    assert result is None
