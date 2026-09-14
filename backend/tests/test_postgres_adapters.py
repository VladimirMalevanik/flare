"""Fast regression checks for values passed into psycopg's PostgreSQL driver."""

from datetime import datetime, timezone
from uuid import uuid4

from psycopg.types.json import Jsonb
import pytest

from app.models.events import ActivityEventRepository, EventSummary
from app.models.tables import ItemRepository
from app.services.analytics_service import _sanitize_metadata


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
    repository.insert_version(
        version_id=version_id,
        workspace_id=workspace_id,
        document_id=item_id,
        content_hash="a" * 64,
        parser_version="import-file-v1",
        snapshot_title="Signals",
        snapshot_source_url=None,
        snapshot_metadata={"sourceType": "file"},
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
    assert isinstance(connection.calls[2][1][-1], Jsonb)


def test_item_repository_pages_by_latest_update():
    connection = _Connection()
    repository = ItemRepository(connection)

    assert repository.list_active(
        query=None,
        item_type=None,
        limit=50,
    ) == []

    statement, parameters = connection.calls[-1]
    assert "ORDER BY d.updated_at DESC, d.id DESC LIMIT %s" in statement
    assert parameters == [50]

    cursor_time = datetime(2026, 9, 14, 12, 0, tzinfo=timezone.utc)
    cursor_id = uuid4()
    assert repository.list_active(
        query="customer",
        item_type="file",
        limit=51,
        before_updated_at=cursor_time,
        before_id=cursor_id,
    ) == []
    statement, parameters = connection.calls[-1]
    assert "(d.updated_at, d.id) < (%s, %s)" in statement
    assert "ORDER BY d.updated_at DESC, d.id DESC LIMIT %s" in statement
    assert parameters[-3:] == [cursor_time, cursor_id, 51]


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


def test_analytics_metadata_is_small_scalar_allowlisted_telemetry():
    assert _sanitize_metadata(
        "capture_file_attached",
        {"format": "csv", "fileSize": 42, "fileType": "text/csv"},
    ) == {"format": "csv", "fileSize": 42, "fileType": "text/csv"}

    with pytest.raises(ValueError, match="not allowed"):
        _sanitize_metadata("capture_file_attached", {"content": "customer source text"})
    with pytest.raises(ValueError, match="too long"):
        _sanitize_metadata("capture_started", {"channel": "x" * 129})
    assert _sanitize_metadata("analysis_requested", {"mode": "manual"}) == {"mode": "manual"}
    assert _sanitize_metadata("analysis_refresh_completed", {"source_count": 5}) == {
        "source_count": 5
    }
    assert _sanitize_metadata("github_repository_selected", {"private": True}) == {
        "private": True
    }
    with pytest.raises(ValueError, match="not allowed"):
        _sanitize_metadata("analysis_refresh_failed", {"content": "private source"})
    with pytest.raises(ValueError, match="not allowed"):
        _sanitize_metadata("github_repository_selected", {"repository": "private/name"})
