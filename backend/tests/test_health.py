from uuid import uuid4

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
        dev_workspace_id=uuid4(),
        dev_user_id="lifecycle-test-user",
        dev_workspace_name="Lifecycle Test",
    )

    with pytest.raises(RuntimeError, match="bootstrap failed"):
        with TestClient(main_module.create_app(configured)):
            pass

    assert fake_database.opened is True
    assert fake_database.closed is True
