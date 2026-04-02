from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.email import is_email_configured, send_invite_email


@patch("app.email.settings")
def test_is_email_configured_true(mock_settings):
    mock_settings.SMTP_HOST = "smtp.example.com"
    mock_settings.SMTP_FROM = "noreply@example.com"
    assert is_email_configured() is True


@patch("app.email.settings")
def test_is_email_configured_false(mock_settings):
    mock_settings.SMTP_HOST = ""
    mock_settings.SMTP_FROM = ""
    assert is_email_configured() is False


@patch("app.email.settings")
def test_send_invite_email_not_configured(mock_settings):
    mock_settings.SMTP_HOST = ""
    mock_settings.SMTP_FROM = ""
    assert send_invite_email("guest@test.com", "http://example.com/invite/abc") is False


@patch("app.email.smtplib.SMTP")
@patch("app.email.settings")
def test_send_invite_email_success(mock_settings, mock_smtp_class):
    mock_settings.SMTP_HOST = "smtp.example.com"
    mock_settings.SMTP_PORT = 587
    mock_settings.SMTP_FROM = "noreply@example.com"
    mock_settings.SMTP_USER = "user"
    mock_settings.SMTP_PASSWORD = "pass"

    mock_server = MagicMock()
    mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
    mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

    result = send_invite_email("guest@test.com", "http://example.com/invite/abc")
    assert result is True


@patch("app.email.smtplib.SMTP")
@patch("app.email.settings")
def test_send_invite_email_smtp_error(mock_settings, mock_smtp_class):
    mock_settings.SMTP_HOST = "smtp.example.com"
    mock_settings.SMTP_PORT = 587
    mock_settings.SMTP_FROM = "noreply@example.com"
    mock_settings.SMTP_USER = ""

    mock_smtp_class.side_effect = Exception("Connection refused")
    result = send_invite_email("guest@test.com", "http://example.com/invite/abc")
    assert result is False
