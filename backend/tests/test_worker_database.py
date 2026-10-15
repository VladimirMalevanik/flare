from contextlib import contextmanager
from unittest.mock import ANY, Mock, sentinel

import psycopg
import pytest
from psycopg.rows import dict_row

from app import worker_database


class FakePool:
    def __init__(self, parameters):
        self.parameters = parameters
        self.connection = Mock(return_value=sentinel.connection_context)
        self.close = Mock()


@pytest.fixture
def pool_factory(monkeypatch):
    worker_database._close_worker_database_pools()
    pools = []

    def create(**parameters):
        pool = FakePool(parameters)
        pools.append(pool)
        return pool

    factory = Mock(side_effect=create)
    factory.check_connection = sentinel.connection_check
    monkeypatch.setattr(worker_database, "ConnectionPool", factory)
    yield factory, pools
    worker_database._close_worker_database_pools()


def test_worker_database_pool_is_cold_start_safe_and_strictly_bounded(pool_factory):
    factory, pools = pool_factory
    database_url = "postgresql://worker:private-secret@worker.invalid/flare"

    result = worker_database.connect_worker_database(
        database_url,
        row_factory=dict_row,
        application_name="flare-worker-test",
        options="-c statement_timeout=10000 -c lock_timeout=5000",
    )

    assert result is sentinel.connection_context
    factory.assert_called_once_with(
        conninfo=database_url,
        kwargs={
            "row_factory": dict_row,
            "application_name": "flare-worker-test",
            "options": "-c statement_timeout=10000 -c lock_timeout=5000",
            "connect_timeout": 15,
        },
        min_size=0,
        max_size=1,
        open=True,
        check=sentinel.connection_check,
        name=ANY,
        timeout=20,
        max_waiting=1,
        reconnect_timeout=20,
        num_workers=1,
    )
    pool_name = factory.call_args.kwargs["name"]
    assert pool_name.startswith("flare-worker-")
    assert "postgresql" not in pool_name
    pool_keys = tuple(worker_database._pools)
    assert len(pool_keys) == 1
    assert isinstance(pool_keys[0][0], bytes)
    assert "private-secret" not in repr(pool_keys)
    assert "worker.invalid" not in repr(pool_keys)
    pools[0].connection.assert_called_once_with(timeout=20)
    assert worker_database.WORKER_DATABASE_CONNECT_TIMEOUT_SECONDS == 15


def test_repeated_calls_reuse_pool_for_the_exact_profile(pool_factory):
    factory, pools = pool_factory
    profile = {
        "application_name": "flare-analysis-worker",
        "row_factory": dict_row,
        "options": "-c statement_timeout=10000 -c lock_timeout=5000",
    }

    first = worker_database.connect_worker_database(
        "postgresql://worker.invalid/flare", **profile
    )
    second = worker_database.connect_worker_database(
        "postgresql://worker.invalid/flare",
        options=profile["options"],
        row_factory=profile["row_factory"],
        application_name=profile["application_name"],
    )

    assert first is second is sentinel.connection_context
    factory.assert_called_once()
    assert pools[0].connection.call_count == 2
    assert profile == {
        "application_name": "flare-analysis-worker",
        "row_factory": dict_row,
        "options": "-c statement_timeout=10000 -c lock_timeout=5000",
    }


def test_database_url_and_every_caller_option_isolate_pool_profiles(pool_factory):
    factory, pools = pool_factory
    url = "postgresql://worker.invalid/flare"

    worker_database.connect_worker_database(url, application_name="analysis")
    worker_database.connect_worker_database(url, application_name="imports")
    worker_database.connect_worker_database(url, application_name="analysis", autocommit=True)
    worker_database.connect_worker_database(
        "postgresql://other-worker.invalid/flare", application_name="analysis"
    )
    worker_database.connect_worker_database(url, application_name="analysis")

    assert factory.call_count == 4
    assert len(pools) == 4
    assert pools[0].connection.call_count == 2
    assert all(pool.connection.call_count == 1 for pool in pools[1:])


def test_sql_failure_is_not_retried_and_later_checkout_reuses_pool(pool_factory):
    factory, pools = pool_factory
    database_error = psycopg.OperationalError("synthetic connection failure")
    attempts = []

    @contextmanager
    def failed_operation():
        attempts.append("failed")
        yield Mock(execute=Mock(side_effect=database_error))

    @contextmanager
    def later_operation():
        attempts.append("later")
        yield Mock(execute=Mock(return_value=sentinel.result))

    worker_database.connect_worker_database("postgresql://worker.invalid/flare")
    pool = pools[0]
    pool.connection.side_effect = [failed_operation(), later_operation()]

    with pytest.raises(psycopg.OperationalError, match="synthetic connection failure"):
        with worker_database.connect_worker_database("postgresql://worker.invalid/flare") as connection:
            connection.execute("SELECT durable_capability()")

    assert attempts == ["failed"]
    with worker_database.connect_worker_database("postgresql://worker.invalid/flare") as connection:
        assert connection.execute("SELECT durable_capability()") is sentinel.result

    assert attempts == ["failed", "later"]
    factory.assert_called_once()
    # One setup checkout plus the failed and subsequent independent checkouts.
    assert pool.connection.call_count == 3


def test_shutdown_closes_each_profile_once(pool_factory):
    _, pools = pool_factory
    worker_database.connect_worker_database("postgresql://worker.invalid/flare")
    worker_database.connect_worker_database(
        "postgresql://worker.invalid/flare", autocommit=True
    )

    worker_database._close_worker_database_pools()
    worker_database._close_worker_database_pools()

    assert len(pools) == 2
    for pool in pools:
        pool.close.assert_called_once_with()


def test_worker_database_connect_rejects_per_caller_timeout_override(pool_factory):
    factory, _ = pool_factory

    with pytest.raises(TypeError, match="centrally managed"):
        worker_database.connect_worker_database(
            "postgresql://worker.invalid/flare",
            connect_timeout=1,
        )

    factory.assert_not_called()


def test_worker_database_rejects_unhashable_profile_options(pool_factory):
    factory, _ = pool_factory

    with pytest.raises(TypeError, match="must be hashable"):
        worker_database.connect_worker_database(
            "postgresql://worker.invalid/flare",
            options=["synthetic", "unhashable"],
        )

    factory.assert_not_called()
