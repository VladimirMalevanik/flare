"""Restricted, process-local worker database connection pools."""

import atexit
from hashlib import sha256
from itertools import count
from threading import Lock
from typing import Any

from psycopg_pool import ConnectionPool


# Azure PostgreSQL can take more than three seconds to complete a fresh TLS
# connection while an App Service instance is warming. A pool checkout gets a
# little extra time for a failed connection check to be discarded and replaced;
# each physical connection attempt remains bounded to exactly 15 seconds.
WORKER_DATABASE_CONNECT_TIMEOUT_SECONDS = 15
WORKER_DATABASE_POOL_WAIT_TIMEOUT_SECONDS = 20


_pools: dict[tuple[bytes, frozenset[tuple[str, Any]]], ConnectionPool] = {}
_pools_lock = Lock()
_pool_names = count(1)


def _pool_key(database_url: str, kwargs: dict[str, Any]):
    try:
        profile = frozenset(kwargs.items())
    except TypeError:
        # Pool profiles are deliberately finite and stable. Refuse an option
        # that cannot be compared instead of accidentally sharing a connection
        # configured for a different caller.
        raise TypeError("Worker database connection options must be hashable") from None
    # Keep credentials out of the process registry and diagnostic reprs. The
    # pool itself necessarily retains its conninfo, but the lookup key does not.
    return sha256(database_url.encode("utf-8")).digest(), profile


def _worker_database_pool(database_url: str, kwargs: dict[str, Any]) -> ConnectionPool:
    key = _pool_key(database_url, kwargs)
    with _pools_lock:
        pool = _pools.get(key)
        if pool is None:
            connection_kwargs = dict(kwargs)
            connection_kwargs["connect_timeout"] = WORKER_DATABASE_CONNECT_TIMEOUT_SECONDS
            pool = ConnectionPool(
                conninfo=database_url,
                kwargs=connection_kwargs,
                min_size=0,
                max_size=1,
                open=True,
                check=ConnectionPool.check_connection,
                name=f"flare-worker-{next(_pool_names)}",
                timeout=WORKER_DATABASE_POOL_WAIT_TIMEOUT_SECONDS,
                # A cold pool may briefly have both the first requester and a
                # concurrent caller waiting while its single physical
                # connection is established. Keep that queue bounded without
                # rejecting the second operation before either can run.
                max_waiting=2,
                reconnect_timeout=WORKER_DATABASE_POOL_WAIT_TIMEOUT_SECONDS,
                num_workers=1,
            )
            _pools[key] = pool
        return pool


def connect_worker_database(database_url: str, **kwargs: Any):
    """Borrow one checked connection while retaining short transaction semantics.

    The returned context manager commits a successful operation, rolls back a
    failed operation, and returns the connection to its process-local pool.
    SQL is never retried here: an ambiguous operation failure propagates to the
    durable lease/retry logic, while the next operation may use a replacement
    connection if the previous one was broken.
    """
    if "connect_timeout" in kwargs:
        raise TypeError("Worker database connect timeout is centrally managed")
    pool = _worker_database_pool(database_url, kwargs)
    return pool.connection(timeout=WORKER_DATABASE_POOL_WAIT_TIMEOUT_SECONDS)


def _close_worker_database_pools() -> None:
    """Close process-local pools at interpreter shutdown and in isolated tests."""
    with _pools_lock:
        pools = tuple(_pools.values())
        _pools.clear()
    for pool in pools:
        pool.close()


atexit.register(_close_worker_database_pools)
