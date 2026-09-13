"""Application-facing analytics helpers for operational insights."""

from datetime import datetime, timedelta, timezone
import json
import math
from typing import TypedDict
from uuid import UUID

from psycopg import errors as pg_errors

from app.models.database import Database, WorkspaceIdentity
from app.models.events import EventSummary, ActivityEventRepository


class InvalidEventType(ValueError):
    """Raised when a client sends an unsupported analytics event."""


class EventSummaryByType(TypedDict):
    event_type: str
    count: int


class EventSummaryResponse(TypedDict):
    window_hours: int
    since: str
    until: str
    events: list[EventSummaryByType]


ALLOWED_EVENTS = {
    "capture_started",
    "capture_submitted",
    "capture_file_attached",
    "capture_voice_started",
    "capture_voice_stopped",
    "item_created",
    "item_deleted",
    "item_viewed",
    "flare_viewed",
    "queue_health_requested",
    "queue_maintenance_run",
    "import_started",
    "import_completed",
    "import_failed",
}
_ALLOWED_TARGET_TYPES = {"capture", "flare", "import", "item", "note", "screen"}

# Telemetry is intentionally a small, structured signal rather than a second
# document store.  Values stay bounded even when clients call the endpoint
# directly instead of going through the browser UI.
_METADATA_KEYS_BY_EVENT: dict[str, frozenset[str]] = {
    "capture_started": frozenset({"channel", "source"}),
    "capture_submitted": frozenset(),
    "capture_file_attached": frozenset({"format", "fileSize", "fileType"}),
    "capture_voice_started": frozenset(),
    "capture_voice_stopped": frozenset(),
    "item_created": frozenset({"item_type"}),
    "item_deleted": frozenset(),
    "item_viewed": frozenset({"sourceType"}),
    "flare_viewed": frozenset({"source", "screen"}),
    "queue_health_requested": frozenset(),
    "queue_maintenance_run": frozenset(
        {
            "dry_run",
            "recover_stale",
            "max_rows",
            "analysis_completed_retention_days",
            "analysis_failed_retention_days",
            "flare_completed_retention_days",
            "flare_failed_retention_days",
        }
    ),
    "import_started": frozenset(),
    "import_completed": frozenset(),
    "import_failed": frozenset(),
}
_MAX_METADATA_FIELDS = 16
_MAX_METADATA_KEY_LENGTH = 64
_MAX_METADATA_STRING_LENGTH = 128
_MAX_METADATA_BYTES = 2_048


class AnalyticsService:
    def __init__(self, database: Database, identity: WorkspaceIdentity):
        self._database = database
        self._identity = identity

    def track_event(
        self,
        *,
        event_type: str,
        target_type: str | None = None,
        target_id: str | None = None,
        metadata: dict | None = None,
    ) -> None:
        if event_type not in ALLOWED_EVENTS:
            raise InvalidEventType
        if target_type is not None and target_type not in _ALLOWED_TARGET_TYPES:
            raise ValueError("target type is not allowed")

        sanitized_metadata = _sanitize_metadata(event_type, metadata)
        parsed_target_id = _parse_uuid_or_none(target_id)

        with self._database.workspace_transaction(self._identity, write=True) as connection:
            repository = ActivityEventRepository(connection)
            try:
                repository.insert(
                    workspace_id=self._identity.workspace_id,
                    actor_id=self._identity.user_id,
                    event_type=event_type,
                    target_type=target_type,
                    target_id=parsed_target_id,
                    metadata=sanitized_metadata,
                )
            except pg_errors.UndefinedTable:
                # Backward-compatible no-op for legacy runtimes where event sink
                # is not yet deployed.
                return

    def summary(self, *, window_hours: int) -> EventSummaryResponse:
        if window_hours < 1 or window_hours > 24 * 30:
            raise ValueError("window_hours must be between 1 and 720")
        until = datetime.now(timezone.utc)
        since = until - timedelta(hours=window_hours)
        with self._database.workspace_transaction(self._identity) as connection:
            try:
                repository = ActivityEventRepository(connection)
                rows: list[EventSummary] = repository.event_summary(self._identity.workspace_id, since)
            except pg_errors.UndefinedTable:
                return {
                    "window_hours": window_hours,
                    "since": since.isoformat(),
                    "until": until.isoformat(),
                    "events": [],
                }
        events = [{"event_type": row.event_type, "count": row.count} for row in rows]
        return {
            "window_hours": window_hours,
            "since": since.isoformat(),
            "until": until.isoformat(),
            "events": events,
        }


def _sanitize_metadata(event_type: str, metadata: dict | None) -> dict:
    if not metadata:
        return {}
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    if len(metadata) > _MAX_METADATA_FIELDS:
        raise ValueError("metadata has too many fields")
    allowed_keys = _METADATA_KEYS_BY_EVENT[event_type]
    sanitized: dict = {}
    for key, value in metadata.items():
        if (
            not isinstance(key, str)
            or not key
            or len(key) > _MAX_METADATA_KEY_LENGTH
            or key not in allowed_keys
        ):
            raise ValueError("metadata key is not allowed")
        if isinstance(value, str):
            if len(value) > _MAX_METADATA_STRING_LENGTH:
                raise ValueError("metadata string is too long")
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError("metadata number must be finite")
        elif not isinstance(value, (int, bool)) and value is not None:
            raise ValueError("metadata values must be scalar")
        sanitized[key] = value
    serialized = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(serialized.encode("utf-8")) > _MAX_METADATA_BYTES:
        raise ValueError("metadata is too large")
    return sanitized


def _parse_uuid_or_none(value: str | None) -> UUID | None:
    if value is None:
        return None
    return UUID(value)
