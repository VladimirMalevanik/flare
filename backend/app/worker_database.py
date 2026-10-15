"""Restricted worker database connections with a cold-start-safe deadline."""

from typing import Any

import psycopg


# Azure PostgreSQL can take more than three seconds to complete a fresh TLS
# connection while an App Service instance is warming. Worker operations still
# keep their statement and lock deadlines; this only bounds connection setup.
WORKER_DATABASE_CONNECT_TIMEOUT_SECONDS = 15


def connect_worker_database(database_url: str, **kwargs: Any):
    """Open a worker connection with one shared, bounded connect deadline."""
    if "connect_timeout" in kwargs:
        raise TypeError("Worker database connect timeout is centrally managed")
    return psycopg.connect(
        database_url,
        connect_timeout=WORKER_DATABASE_CONNECT_TIMEOUT_SECONDS,
        **kwargs,
    )
