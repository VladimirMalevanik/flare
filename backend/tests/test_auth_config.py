"""Finite persistent-sign-in defaults and explicit deployment overrides."""
import pytest

from app.config import Settings, load_settings


def test_persistent_session_defaults_match_service_and_environment(monkeypatch):
    monkeypatch.delenv('SESSION_LIFETIME_SECONDS', raising=False)
    monkeypatch.delenv('SESSION_IDLE_SECONDS', raising=False)
    direct = Settings(environment='test', database_url=None, cors_origins=[])
    loaded = load_settings()
    from app.services.auth_service import AuthService
    service = AuthService(None)
    assert direct.session_lifetime_seconds == loaded.session_lifetime_seconds == service.lifetime == 2_592_000
    assert direct.session_idle_seconds == loaded.session_idle_seconds == service.idle_seconds == 2_592_000


def test_explicit_session_overrides_are_preserved(monkeypatch):
    monkeypatch.setenv('FLARE_ENV', 'test')
    monkeypatch.setenv('EMAIL_VERIFICATION_REQUIRED', 'false')
    monkeypatch.setenv('SESSION_LIFETIME_SECONDS', '7200')
    monkeypatch.setenv('SESSION_IDLE_SECONDS', '3600')
    configured = load_settings()
    configured.validate()
    assert configured.session_lifetime_seconds == 7200
    assert configured.session_idle_seconds == 3600


@pytest.mark.parametrize('lifetime,idle', [(0, 1), (3600, 0), (3600, -1), (3600, 3601)])
def test_invalid_session_limits_fail_closed(lifetime, idle):
    configured = Settings(environment='test', database_url=None, cors_origins=[],
                          session_lifetime_seconds=lifetime, session_idle_seconds=idle)
    with pytest.raises(RuntimeError, match='Session limits'):
        configured.validate()
