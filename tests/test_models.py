from __future__ import annotations

from datetime import datetime, timedelta

from app.models import (
    AppSetting,
    ConversionJob,
    ConversionRequest,
    ImdbParentalGuide,
    Invitation,
    JobStatus,
    RequestStatus,
    RequestType,
    User,
    UserSession,
)


def test_create_user_defaults(db_session):
    user = User(username="testuser", email="t@t.com")
    db_session.add(user)
    db_session.flush()
    assert user.id is not None
    assert user.is_admin is False
    assert user.is_approved is False
    assert user.auth_method == "plex"


def test_user_session_relationship(db_session):
    user = User(username="u1", email="u1@t.com", is_approved=True)
    db_session.add(user)
    db_session.flush()
    session = UserSession(
        token="tok123",
        user_id=user.id,
        csrf_token="csrf123",
        expires_at=datetime.utcnow() + timedelta(days=1),
    )
    db_session.add(session)
    db_session.flush()
    assert len(user.sessions) == 1
    assert user.sessions[0].token == "tok123"
    assert session.user.username == "u1"


def test_conversion_request_jobs_cascade(db_session):
    user = User(username="u2", is_approved=True)
    db_session.add(user)
    db_session.flush()
    req = ConversionRequest(
        user_id=user.id,
        title="Test Movie",
        request_type=RequestType.movie,
    )
    db_session.add(req)
    db_session.flush()
    job = ConversionJob(
        request_id=req.id,
        plex_key="/library/metadata/1",
        title="Test Movie",
        input_file="/mnt/media/movie.mkv",
    )
    db_session.add(job)
    db_session.flush()

    assert len(req.jobs) == 1
    db_session.delete(req)
    db_session.flush()
    assert db_session.query(ConversionJob).filter_by(id=job.id).first() is None


def test_request_status_enum():
    assert "queued" in [s.value for s in RequestStatus]
    assert "complete" in [s.value for s in RequestStatus]


def test_job_status_enum():
    assert "running" in [s.value for s in JobStatus]
    assert "already_exists" in [s.value for s in JobStatus]


def test_request_type_enum():
    assert set(RequestType) == {
        RequestType.movie,
        RequestType.episode,
        RequestType.season,
        RequestType.series,
    }


def test_invitation_model(db_session):
    user = User(username="inviter", is_approved=True, is_admin=True)
    db_session.add(user)
    db_session.flush()
    inv = Invitation(
        email="guest@test.com",
        token="inv_token_123",
        invited_by=user.id,
        expires_at=datetime.utcnow() + timedelta(days=7),
    )
    db_session.add(inv)
    db_session.flush()
    assert inv.id is not None
    assert inv.accepted_at is None


def test_app_setting_model(db_session):
    setting = AppSetting(key="test_key", value="test_value")
    db_session.add(setting)
    db_session.flush()
    fetched = db_session.query(AppSetting).filter_by(key="test_key").first()
    assert fetched.value == "test_value"


def test_imdb_parental_guide_model(db_session):
    guide = ImdbParentalGuide(
        imdb_id="tt1234567",
        data_json='{"nudity": "Mild"}',
    )
    db_session.add(guide)
    db_session.flush()
    assert guide.fetched_at is not None


def test_conversion_request_nullable_overrides(db_session):
    req = ConversionRequest(
        title="Override Test",
        request_type=RequestType.movie,
    )
    db_session.add(req)
    db_session.flush()
    assert req.nudity_confidence is None
    assert req.violence_detectors_json is None
    assert req.profanity_extra_words_json is None
