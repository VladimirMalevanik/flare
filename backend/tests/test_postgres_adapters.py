"""Fast regression checks for values passed into psycopg's PostgreSQL driver."""

from datetime import datetime, timezone
from uuid import uuid4

from psycopg.types.json import Jsonb
import pytest

from app.models.events import ActivityEventRepository, EventSummary
from app.models.tables import ItemRepository
from app.services.analytics_service import _sanitize_metadata
from app.services.ops_service import QueueService


class _Result:
    def __init__(self, *, one=None, all_rows=None):
        self._one = one
        self._all_rows = all_rows or []

    def fetchone(self):
        return self._one

    def fetchall(self):
        return self._all_rows


class _Connection:
    def __init__(self):
        self.calls: list[tuple[str, tuple[object, ...] | None]] = []

    def execute(self, statement, parameters=None):
        self.calls.append((statement, parameters))
        return _Result(one={"created_at": datetime.now(timezone.utc)})


def test_item_repository_wraps_json_values_for_psycopg():
    connection = _Connection()
    repository = ItemRepository(connection)
    workspace_id, item_id, version_id, chunk_id = (uuid4() for _ in range(4))

    repository.insert_document(
        item_id=item_id,
        workspace_id=workspace_id,
        title="Signals",
        item_type="file",
        source_url=None,
        metadata={"sourceType": "file"},
    )
    repository.insert_chunk(
        chunk_id=chunk_id,
        workspace_id=workspace_id,
        version_id=version_id,
        content="source text",
        locator={"kind": "file"},
    )

    assert isinstance(connection.calls[0][1][-1], Jsonb)
    assert isinstance(connection.calls[1][1][-1], Jsonb)


def test_activity_event_repository_wraps_json_and_reads_dict_rows():
    connection = _Connection()
    repository = ActivityEventRepository(connection)
    workspace_id = uuid4()

    repository.insert(
        workspace_id=workspace_id,
        actor_id="auth:test",
        event_type="capture_started",
        target_type="capture",
        target_id=None,
        metadata={"channel": "keyboard"},
    )
    assert isinstance(connection.calls[0][1][-1], Jsonb)

    connection.execute = lambda *_args, **_kwargs: _Result(
        all_rows=[{"event_type": "capture_started", "count": 2}]
    )
    assert repository.event_summary(workspace_id, datetime.now(timezone.utc)) == [
        EventSummary(event_type="capture_started", count=2)
    ]


def test_queue_health_sql_filters_the_aggregate_before_elapsed_time_is_calculated():
    for statement in (QueueService._ANALYSIS_SQL, QueueService._FLARE_SQL):
        assert "MIN(created_at) FILTER (WHERE status='pending')" in statement
        assert "MIN(created_at) FILTER (WHERE status='processing')" in statement
        assert "MIN(created_at)) FILTER" not in statement


def test_analytics_metadata_is_small_scalar_allowlisted_telemetry():
    assert _sanitize_metadata(
        "capture_file_attached",
        {"format": "csv", "fileSize": 42, "fileType": "text/csv"},
    ) == {"format": "csv", "fileSize": 42, "fileType": "text/csv"}

    with pytest.raises(ValueError, match="not allowed"):
        _sanitize_metadata("capture_file_attached", {"content": "customer source text"})
    with pytest.raises(ValueError, match="too long"):
        _sanitize_metadata("capture_started", {"channel": "x" * 129})
