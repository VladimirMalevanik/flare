from uuid import uuid4
import logging
from contextlib import contextmanager

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import dict_row, tuple_row
from psycopg_pool import PoolTimeout

import app.main as main_module
import app.models.database as database_module
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


class _ReadinessDatabase:
    def __init__(self, result=True, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def open(self):
        pass

    def close(self):
        pass

    def is_ready(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def _readiness_client(database):
    configured = Settings(
        database_url="postgresql://unused",
        cors_origins=[],
        environment="test",
        email_verification_required=False,
    )
    return TestClient(main_module.create_app(configured, database=database))


@pytest.mark.parametrize(
    ("result", "status_code", "detail"),
    ((True, 200, None), (False, 503, "Database is not initialized")),
)
def test_readiness_uses_injected_pool(result, status_code, detail, monkeypatch):
    monkeypatch.setattr(
        database_module.psycopg,
        "connect",
        lambda *_args, **_kwargs: pytest.fail("readiness opened a direct connection"),
    )
    database = _ReadinessDatabase(result=result)
    with _readiness_client(database) as client:
        response = client.get("/ready")
    assert response.status_code == status_code
    assert database.calls == 1
    if detail is None:
        assert response.json() == {"status": "ready"}
    else:
        assert response.json() == {"detail": detail}


@pytest.mark.parametrize(
    "error",
    (psycopg.OperationalError("connection unavailable"), PoolTimeout("pool unavailable")),
)
def test_readiness_sanitizes_database_errors(error):
    database = _ReadinessDatabase(error=error)
    with _readiness_client(database) as client:
        response = client.get("/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database is unavailable"}
    assert "unavailable" not in response.text.replace("Database is unavailable", "")


def test_pooled_readiness_is_one_bounded_query():
    class Result:
        def fetchone(self):
            return {"ready": True}

    class Connection:
        def __init__(self):
            self.calls = []

        def execute(self, query, params):
            self.calls.append((query, params))
            return Result()

    connection = Connection()

    class Pool:
        @contextmanager
        def connection(self, *, timeout=None):
            assert timeout == 1.25
            yield connection

    database = database_module.Database.__new__(database_module.Database)
    database._pool = Pool()
    assert database.is_ready(timeout=1.25) is True
    assert len(connection.calls) == 1
    query, params = connection.calls[0]
    assert "current_user" in query
    assert "transaction_read_only" in query
    assert "pg_is_in_recovery" in query
    assert "to_regtype('vector')" in query
    assert params == (database_module.CURRENT_SCHEMA_REVISION,)


def test_database_open_runs_full_fence_with_bounded_warmup(monkeypatch):
    class Connection:
        def __init__(self):
            self.row_factory = dict_row

    connection = Connection()

    class Pool:
        def __init__(self):
            self.open_args = None
            self.closed = False

        def open(self, *, wait, timeout):
            self.open_args = (wait, timeout)

        @contextmanager
        def connection(self):
            yield connection

        def close(self):
            self.closed = True

    pool = Pool()
    observed = []
    original_row_factory = connection.row_factory

    def full_fence(candidate):
        observed.append(candidate.row_factory)
        return True

    monkeypatch.setattr(database_module, "_connection_is_ready", full_fence)
    database = database_module.Database.__new__(database_module.Database)
    database._pool = pool
    database.open()

    assert pool.open_args == (True, database_module.DATABASE_STARTUP_TIMEOUT_SECONDS)
    assert observed == [tuple_row]
    assert connection.row_factory is original_row_factory
    assert pool.closed is False


def test_database_open_closes_pool_when_full_fence_fails(monkeypatch):
    class Connection:
        def __init__(self):
            self.row_factory = dict_row

    class Pool:
        def __init__(self):
            self.closed = False

        def open(self, *, wait, timeout):
            pass

        @contextmanager
        def connection(self):
            yield Connection()

        def close(self):
            self.closed = True

    pool = Pool()
    monkeypatch.setattr(database_module, "_connection_is_ready", lambda _connection: False)
    database = database_module.Database.__new__(database_module.Database)
    database._pool = pool

    with pytest.raises(RuntimeError, match="schema and security readiness fence"):
        database.open()
    assert pool.closed is True


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
