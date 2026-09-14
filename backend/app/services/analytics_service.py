"""Application-facing analytics helpers for operational insights."""

from datetime import datetime, timedelta, timezone
import json
import logging
from typing import Callable, TypedDict
from uuid import UUID

from psycopg import errors as pg_errors

from app.models.database import Database, WorkspaceIdentity
from app.models.events import EventSummary, ActivityEventRepository


# Uvicorn configures this logger for the API process even with access logs off.
operational_logger = logging.getLogger("uvicorn.error")


class InvalidEventType(ValueError):
    """Raised when a client sends an unsupported analytics event."""


class AnalyticsRateLimited(Exception):
    """The best-effort browser telemetry budget has been exhausted."""


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
    "item_updated",
    "source_replaced",
    "item_deleted",
    "item_viewed",
    "flare_viewed",
    "screen_opened",
    "queue_health_requested",
    "queue_maintenance_run",
    "import_started",
    "import_completed",
    "import_failed",
    "analysis_requested",
    "schedule_updated",
    "analysis_refresh_started",
    "analysis_refresh_completed",
    "analysis_refresh_failed",
    "github_connection_started",
    "github_installation_authorized",
    "github_repository_selected",
    "github_disconnected",
}

# Only interaction events emitted by the shipped browser UI are accepted by
# POST /analytics/events. Outcome and operational events remain server-only.
CLIENT_EVENTS = frozenset(
    {
        "capture_started",
        "capture_submitted",
        "capture_file_attached",
        "capture_voice_started",
        "capture_voice_stopped",
        "item_viewed",
        "flare_viewed",
        "screen_opened",
    }
)

# Telemetry is intentionally a small, structured signal rather than a second
# document store.  Values stay bounded even when clients call the endpoint
# directly instead of going through the browser UI.
MetadataValidator = Callable[[object], bool]


def _one_of(*values: str) -> MetadataValidator:
    allowed = frozenset(values)
    return lambda value: isinstance(value, str) and value in allowed


def _integer_between(minimum: int, maximum: int) -> MetadataValidator:
    return lambda value: type(value) is int and minimum <= value <= maximum


def _boolean(value: object) -> bool:
    return type(value) is bool


_ITEM_TYPES = ("note", "url", "file", "audio")
_METADATA_RULES_BY_EVENT: dict[str, dict[str, MetadataValidator]] = {
    "capture_started": {"channel": _one_of("orb", "keyboard")},
    "capture_submitted": {"sourceType": _one_of(*_ITEM_TYPES)},
    "capture_file_attached": {
        "format": _one_of("csv", "txt", "md"),
        "fileSize": _integer_between(0, 200_000),
        # Kept for compatibility with already shipped clients, but bounded to
        # known non-sensitive MIME labels. New clients omit this field.
        "fileType": _one_of(
            "text/csv",
            "text/plain",
            "text/markdown",
            "application/csv",
            "application/vnd.ms-excel",
            "application/octet-stream",
        ),
    },
    "capture_voice_started": {},
    "capture_voice_stopped": {},
    "item_created": {"item_type": _one_of(*_ITEM_TYPES)},
    "item_updated": {
        "item_type": _one_of(*_ITEM_TYPES),
        "version_number": _integer_between(1, 2_147_483_647),
    },
    "source_replaced": {
        "item_type": _one_of(*_ITEM_TYPES),
        "version_number": _integer_between(1, 2_147_483_647),
    },
    "item_deleted": {},
    "item_viewed": {"sourceType": _one_of(*_ITEM_TYPES)},
    "flare_viewed": {"source": _one_of("insights_feed")},
    "screen_opened": {"screen": _one_of("sources_from_insights")},
    "queue_health_requested": {},
    "queue_maintenance_run": {
        "dry_run": _boolean,
        "recover_stale": _boolean,
        "max_rows": _integer_between(1, 50_000),
        "analysis_completed_retention_days": _integer_between(1, 3_650),
        "analysis_failed_retention_days": _integer_between(1, 3_650),
        "flare_completed_retention_days": _integer_between(1, 3_650),
        "flare_failed_retention_days": _integer_between(1, 3_650),
        "cycle_failed_retention_days": _integer_between(1, 3_650),
        "activity_event_retention_days": _integer_between(1, 3_650),
    },
    "import_started": {},
    "import_completed": {},
    "import_failed": {},
    "analysis_requested": {"mode": _one_of("manual", "scheduled")},
    "schedule_updated": {"enabled": _boolean},
    "analysis_refresh_started": {"attempt": _integer_between(1, 3)},
    "analysis_refresh_completed": {"source_count": _integer_between(1, 100)},
    "analysis_refresh_failed": {
        "error_code": _one_of(
            "authorization_revoked",
            "no_eligible_context",
            "sync_failed",
            "source_invalid",
            "internal_error",
        ),
        "attempt": _integer_between(1, 3),
    },
    "github_connection_started": {},
    "github_installation_authorized": {},
    "github_repository_selected": {"private": _boolean},
    "github_disconnected": {},
}

_REQUIRED_METADATA_BY_EVENT: dict[str, frozenset[str]] = {
    event_type: frozenset(rules)
    for event_type, rules in _METADATA_RULES_BY_EVENT.items()
}
# A capture source hint and the legacy MIME label are optional. Every other
# declared field is part of the exact event contract.
_REQUIRED_METADATA_BY_EVENT["capture_started"] = frozenset()
_REQUIRED_METADATA_BY_EVENT["capture_file_attached"] = frozenset({"format", "fileSize"})

_TARGET_TYPE_BY_EVENT: dict[str, str | None] = {
    "capture_started": "capture",
    "capture_submitted": "item",
    "capture_file_attached": "import",
    "capture_voice_started": "capture",
    "capture_voice_stopped": "capture",
    "item_created": "item",
    "item_updated": "item",
    "source_replaced": "item",
    "item_deleted": "item",
    "item_viewed": "item",
    "flare_viewed": "flare",
    "screen_opened": "screen",
    "queue_health_requested": None,
    "queue_maintenance_run": None,
    "import_started": "import",
    "import_completed": "import",
    "import_failed": "import",
    "analysis_requested": "analysis_run",
    "schedule_updated": "analysis_schedule",
    "analysis_refresh_started": "analysis_cycle",
    "analysis_refresh_completed": "analysis_cycle",
    "analysis_refresh_failed": "analysis_cycle",
    "github_connection_started": "github_connection",
    "github_installation_authorized": "github_connection",
    "github_repository_selected": "github_connection",
    "github_disconnected": "github_connection",
}
_TARGET_ID_REQUIRED = frozenset(
    {
        "capture_submitted",
        "item_created",
        "item_updated",
        "source_replaced",
        "item_deleted",
        "item_viewed",
        "flare_viewed",
        "import_completed",
        "analysis_requested",
        "analysis_refresh_started",
        "analysis_refresh_completed",
        "analysis_refresh_failed",
    }
)
_TARGET_ID_OPTIONAL = frozenset()
_CLIENT_TARGET_EXISTENCE_EVENTS = frozenset(
    {"capture_submitted", "item_viewed", "flare_viewed"}
)
_MAX_METADATA_FIELDS = 16
_MAX_METADATA_KEY_LENGTH = 64
_MAX_METADATA_STRING_LENGTH = 128
_MAX_METADATA_BYTES = 2_048
MAX_CLIENT_EVENTS_PER_HOUR = 600


class AnalyticsService:
    def __init__(self, database: Database, identity: WorkspaceIdentity):
        self._database = database
        self._identity = identity

    def track_event(
        self,
        *,
        event_type: str,
        target_type: str | None = None,
        target_id: str | UUID | None = None,
        metadata: dict | None = None,
    ) -> None:
        if not isinstance(event_type, str) or event_type not in ALLOWED_EVENTS:
            raise InvalidEventType

        sanitized_metadata = _sanitize_metadata(event_type, metadata)
        _validate_target(event_type, target_type, target_id)
        parsed_target_id = _parse_uuid_or_none(target_id)

        # Activity events are safe for every workspace member to insert. The
        # activity_events RLS policy still binds workspace_id and actor_id.
        with self._database.workspace_transaction(self._identity) as connection:
            repository = ActivityEventRepository(connection)
            try:
                if event_type in CLIENT_EVENTS and not repository.reserve_client_event_slot(
                    workspace_id=self._identity.workspace_id,
                    actor_id=self._identity.user_id,
                    max_events_per_hour=MAX_CLIENT_EVENTS_PER_HOUR,
                    client_event_types=tuple(sorted(CLIENT_EVENTS)),
                ):
                    raise AnalyticsRateLimited
                if (
                    event_type in _CLIENT_TARGET_EXISTENCE_EVENTS
                    and parsed_target_id is not None
                    and not repository.client_target_exists(
                        workspace_id=self._identity.workspace_id,
                        event_type=event_type,
                        target_id=parsed_target_id,
                        source_type=sanitized_metadata.get("sourceType"),
                    )
                ):
                    raise ValueError("analytics target is unavailable")
                repository.insert(
                    workspace_id=self._identity.workspace_id,
                    actor_id=self._identity.user_id,
                    event_type=event_type,
                    target_type=target_type,
                    target_id=parsed_target_id,
                    metadata=sanitized_metadata,
                )
            except pg_errors.UndefinedTable:
                # Best-effort callers turn this into one safe dropped-event
                # warning during staged deployments.
                raise

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

    @property
    def workspace_id(self) -> UUID:
        return self._identity.workspace_id


def track_event_best_effort(analytics: AnalyticsService, **event: object) -> None:
    """Record telemetry without exposing payloads or exception details in logs."""
    event_type = event.get("event_type")
    try:
        analytics.track_event(**event)
    except AnalyticsRateLimited:
        return
    except Exception:
        log_dropped_event(analytics, event_type)


def log_dropped_event(analytics: AnalyticsService, event_type: object) -> None:
    """Emit only fixed dimensions; never interpolate the failed payload/error."""
    safe_event_type = (
        event_type
        if isinstance(event_type, str) and event_type in ALLOWED_EVENTS
        else "invalid"
    )
    operational_logger.warning(
        "analytics_event event_type=%s workspace_id=%s status=dropped",
        safe_event_type,
        analytics.workspace_id,
    )


def _sanitize_metadata(event_type: str, metadata: dict | None) -> dict:
    if not isinstance(event_type, str) or event_type not in ALLOWED_EVENTS:
        raise InvalidEventType
    metadata = {} if metadata is None else metadata
    if not isinstance(metadata, dict):
        raise ValueError("metadata must be an object")
    if len(metadata) > _MAX_METADATA_FIELDS:
        raise ValueError("metadata has too many fields")
    rules = _METADATA_RULES_BY_EVENT[event_type]
    sanitized: dict = {}
    for key, value in metadata.items():
        if (
            not isinstance(key, str)
            or not key
            or len(key) > _MAX_METADATA_KEY_LENGTH
            or key not in rules
        ):
            raise ValueError("metadata key is not allowed")
        if isinstance(value, str) and len(value) > _MAX_METADATA_STRING_LENGTH:
            raise ValueError("metadata string is too long")
        if not rules[key](value):
            raise ValueError("metadata value is not allowed")
        sanitized[key] = value
    if not _REQUIRED_METADATA_BY_EVENT[event_type].issubset(sanitized):
        raise ValueError("metadata is missing required fields")
    serialized = json.dumps(sanitized, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(serialized.encode("utf-8")) > _MAX_METADATA_BYTES:
        raise ValueError("metadata is too large")
    return sanitized


def _validate_target(
    event_type: str,
    target_type: str | None,
    target_id: str | UUID | None,
) -> None:
    if target_type != _TARGET_TYPE_BY_EVENT[event_type]:
        raise ValueError("target type is not allowed for this event")
    if event_type in _TARGET_ID_REQUIRED and target_id is None:
        raise ValueError("target id is required for this event")
    if event_type not in _TARGET_ID_REQUIRED | _TARGET_ID_OPTIONAL and target_id is not None:
        raise ValueError("target id is not allowed for this event")


def _parse_uuid_or_none(value: str | UUID | None) -> UUID | None:
    if value is None:
        return None
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        raise ValueError("target id must be a UUID")
    return UUID(value)
