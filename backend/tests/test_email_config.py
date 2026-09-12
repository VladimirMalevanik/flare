"""Environment policy for verification delivery."""

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, load_settings
from app.main import create_app
from app.services.smtp_email import LoggingEmailSender


def test_environment_defaults_verification_by_safety_boundary(monkeypatch):
    monkeypatch.delenv("EMAIL_VERIFICATION_REQUIRED", raising=False)
    monkeypatch.setenv("FLARE_ENV", "development")
    assert load_settings().email_verification_required is False
    monkeypatch.setenv("FLARE_ENV", "test")
    assert load_settings().email_verification_required is False
    monkeypatch.setenv("FLARE_ENV", "production")
    assert load_settings().email_verification_required is True


def test_production_requires_https_public_url_and_smtp():
    base = {
        "database_url": "postgresql://unused",
        "cors_origins": ["https://flare.test"],
    }
    with pytest.raises(RuntimeError, match="APP_PUBLIC_URL"):
        Settings(**base).validate()
    with pytest.raises(RuntimeError, match="HTTPS APP_PUBLIC_URL, SMTP_URL and EMAIL_FROM"):
        Settings(**base, app_public_url="http://localhost:3000").validate()
    Settings(
        **base,
        app_public_url="https://flare.test",
        smtp_url="smtps://smtp.flare.test:465",
        email_from="Flare <no-reply@flare.test>",
    ).validate()


@pytest.mark.parametrize("field", ["email_verification_ttl_seconds", "email_verification_resend_seconds"])
def test_verification_limits_must_be_positive(field):
    settings = Settings(
        database_url=None,
        environment="test",
        cors_origins=["http://testserver"],
        **{field: 0},
    )
    with pytest.raises(RuntimeError, match="must be positive"):
        settings.validate()


def test_explicit_local_verification_uses_only_localhost_logging_sender():
    remote = Settings(
        database_url=None,
        environment="development",
        cors_origins=["http://localhost:3000"],
        email_verification_required=True,
        app_public_url="https://remote.test",
    )
    with pytest.raises(RuntimeError, match="localhost"):
        remote.validate()

    local = Settings(
        database_url=None,
        environment="development",
        cors_origins=["http://localhost:3000"],
        email_verification_required=True,
        app_public_url="http://localhost:3000",
    )
    with TestClient(create_app(local)) as client:
        assert client.app.state.email_sender.__class__ is LoggingEmailSender
