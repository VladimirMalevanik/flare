from uuid import uuid4
import logging

import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings
from app.config import settings
from app.main import app


def test_health_does_not_require_database():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert response.headers["permissions-policy"] == "camera=(), geolocation=(), microphone=(self)"


def test_raw_uvicorn_access_logger_is_disabled():
    assert logging.getLogger("uvicorn.access").disabled is True


def test_http_log_uses_route_template_and_omits_url_secrets(caplog):
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        response = TestClient(app).get(
            "/health?code=PRIVATE_OAUTH_CODE&query=PRIVATE_NOTE_BODY"
        )

    assert response.status_code == 200
    messages = [record.getMessage() for record in caplog.records if record.name == "uvicorn.error"]
    assert len(messages) == 1
    assert "method=GET" in messages[0]
    assert "route=/health" in messages[0]
    assert "status=200" in messages[0]
    assert "duration_ms=" in messages[0]
    assert "PRIVATE_OAUTH_CODE" not in messages[0]
    assert "PRIVATE_NOTE_BODY" not in messages[0]


def test_http_log_does_not_echo_an_unmatched_path(caplog):
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        response = TestClient(app).get("/PRIVATE_PATH_TOKEN?state=PRIVATE_STATE")

    assert response.status_code == 404
    messages = [record.getMessage() for record in caplog.records if record.name == "uvicorn.error"]
    assert len(messages) == 1
    assert "route=unmatched" in messages[0]
    assert "PRIVATE_PATH_TOKEN" not in messages[0]
    assert "PRIVATE_STATE" not in messages[0]


def test_readiness_fails_without_configuration(monkeypatch):
    monkeypatch.setattr(settings, "database_url", None)
    assert TestClient(app).get("/ready").status_code == 503


def test_owned_database_closes_when_development_bootstrap_fails(monkeypatch):
    class FailingBootstrapDatabase:
        def __init__(self, _database_url):
            self.opened = False
            self.closed = False

        def open(self):
            self.opened = True

        def bootstrap_development_workspace(self, _identity, _workspace_name):
            raise RuntimeError("bootstrap failed")

        def close(self):
            self.closed = True

    fake_database = FailingBootstrapDatabase("unused")
    monkeypatch.setattr(main_module, "Database", lambda _url: fake_database)
    configured = Settings(
        database_url="postgresql://unused",
        cors_origins=[],
        dev_mode=True,
        environment="test",
        dev_workspace_id=uuid4(),
        dev_user_id="lifecycle-test-user",
        dev_workspace_name="Lifecycle Test",
    )

    with pytest.raises(RuntimeError, match="bootstrap failed"):
        with TestClient(main_module.create_app(configured)):
            pass

    assert fake_database.opened is True
    assert fake_database.closed is True
