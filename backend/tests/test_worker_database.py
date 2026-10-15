from unittest.mock import Mock

import pytest

from app.worker_database import (
    WORKER_DATABASE_CONNECT_TIMEOUT_SECONDS,
    connect_worker_database,
)


def test_worker_database_connect_uses_cold_start_safe_bounded_timeout(monkeypatch):
    connect = Mock(return_value=object())
    monkeypatch.setattr("app.worker_database.psycopg.connect", connect)

    result = connect_worker_database(
        "postgresql://worker.invalid/flare",
        application_name="flare-worker-test",
    )

    assert result is connect.return_value
    connect.assert_called_once_with(
        "postgresql://worker.invalid/flare",
        connect_timeout=15,
        application_name="flare-worker-test",
    )
    assert WORKER_DATABASE_CONNECT_TIMEOUT_SECONDS == 15


def test_worker_database_connect_rejects_per_caller_timeout_override(monkeypatch):
    connect = Mock()
    monkeypatch.setattr("app.worker_database.psycopg.connect", connect)

    with pytest.raises(TypeError, match="centrally managed"):
        connect_worker_database(
            "postgresql://worker.invalid/flare",
            connect_timeout=1,
        )

    connect.assert_not_called()
