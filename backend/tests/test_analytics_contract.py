"""Focused safety and authorization checks for product telemetry."""

from contextlib import contextmanager
import logging
from pathlib import Path
from typing import get_args
from uuid import uuid4

from pydantic import ValidationError
import pytest

import app.api.analytics as analytics_api
from app.api.schemas import AnalyticsEventRequest
from app.models.database import WorkspaceIdentity
from app.services import analytics_service as analytics_module
from app.services.analytics_service import (
    ALLOWED_EVENTS,
    AnalyticsRateLimited,
    CLIENT_EVENTS,
    AnalyticsService,
    _METADATA_RULES_BY_EVENT,
    _TARGET_TYPE_BY_EVENT,
    _sanitize_metadata,
    track_event_best_effort,
)


def test_analytics_contract_tables_cover_every_event_and_client_schema_matches():
    assert set(_METADATA_RULES_BY_EVENT) == ALLOWED_EVENTS
    assert set(_TARGET_TYPE_BY_EVENT) == ALLOWED_EVENTS
    annotation = AnalyticsEventRequest.model_fields["event_type"].annotation
    assert set(get_args(annotation)) == CLIENT_EVENTS


@pytest.mark.parametrize(
    "payload",
    [
        {"eventType": "capture_started", "targetType": "capture"},
        {
            "eventType": "capture_submitted",
            "targetType": "item",
            "targetId": str(uuid4()),
            "metadata": {"sourceType": "note"},
        },
        {
            "eventType": "capture_submitted",
            "targetType": "item",
            "targetId": str(uuid4()),
            "metadata": {"sourceType": "audio"},
        },
        {
            "eventType": "capture_file_attached",
            "targetType": "import",
            "metadata": {"format": "md", "fileSize": 42},
        },
        {
            "eventType": "item_viewed",
            "targetType": "item",
            "targetId": str(uuid4()),
            "metadata": {"sourceType": "file"},
        },
        {
            "eventType": "flare_viewed",
            "targetType": "flare",
            "targetId": str(uuid4()),
            "metadata": {"source": "insights_feed"},
        },
        {
            "eventType": "screen_opened",
            "targetType": "screen",
            "metadata": {"screen": "sources_from_insights"},
        },
    ],
)
def test_client_event_schema_accepts_only_shipped_ui_events(payload):
    assert AnalyticsEventRequest.model_validate(payload).event_type == payload["eventType"]


@pytest.mark.parametrize(
    "event_type",
    [
        "item_created",
        "item_deleted",
        "import_completed",
        "analysis_requested",
        "schedule_updated",
        "queue_maintenance_run",
        "github_repository_selected",
    ],
)
def test_client_event_schema_rejects_server_outcome_events(event_type):
    with pytest.raises(ValidationError):
        AnalyticsEventRequest.model_validate({"eventType": event_type})


@pytest.mark.parametrize(
    ("event_type", "metadata"),
    [
        ("capture_started", {"source": "PRIVATE NOTE BODY"}),
        ("capture_started", {"channel": "oauth-token-value"}),
        ("capture_submitted", {"sourceType": "csv with customer rows"}),
        ("capture_file_attached", {"format": "csv", "fileSize": True}),
        ("capture_file_attached", {"format": "csv", "fileSize": 200_001}),
        ("item_viewed", {"sourceType": "private document title"}),
        ("flare_viewed", {"source": "https://secret.invalid/?token=value"}),
        ("analysis_refresh_failed", {"error_code": "provider response body", "attempt": 1}),
        ("github_repository_selected", {"private": "true"}),
        ("github_repository_selected", {"providerPayload": "secret"}),
    ],
)
def test_event_metadata_rejects_content_and_values_outside_exact_schema(event_type, metadata):
    with pytest.raises(ValueError):
        _sanitize_metadata(event_type, metadata)


def test_required_event_metadata_cannot_be_omitted():
    with pytest.raises(ValueError, match="missing required"):
        _sanitize_metadata("capture_file_attached", {"format": "csv"})
    with pytest.raises(ValueError, match="missing required"):
        _sanitize_metadata("flare_viewed", {})


def test_queue_maintenance_metadata_matches_all_bounded_operations():
    metadata = {
        "dry_run": True,
        "recover_stale": True,
        "max_rows": 2_000,
        "analysis_completed_retention_days": 30,
        "analysis_failed_retention_days": 14,
        "flare_completed_retention_days": 30,
        "flare_failed_retention_days": 14,
        "cycle_failed_retention_days": 14,
        "activity_event_retention_days": 90,
    }
    assert _sanitize_metadata("queue_maintenance_run", metadata) == metadata


class _Database:
    def __init__(self):
        self.write_flags: list[bool] = []

    @contextmanager
    def workspace_transaction(self, _identity, *, write=False):
        self.write_flags.append(write)
        yield object()


class _Repository:
    def __init__(self, _connection):
        self.events: list[dict] = []

    def insert(self, **event):
        self.events.append(event)

    def client_target_exists(self, **_target):
        return True

    def reserve_client_event_slot(self, **_budget):
        return True


@pytest.mark.parametrize(
    "event",
    [
        {"event_type": "item_created", "target_type": "item", "target_id": uuid4(),
         "metadata": {"item_type": "note"}},
        {"event_type": "item_updated", "target_type": "item", "target_id": uuid4(),
         "metadata": {"item_type": "file", "version_number": 2}},
        {"event_type": "source_replaced", "target_type": "item", "target_id": uuid4(),
         "metadata": {"item_type": "url", "version_number": 3}},
        {"event_type": "item_deleted", "target_type": "item", "target_id": uuid4()},
        {"event_type": "queue_health_requested"},
        {"event_type": "import_started", "target_type": "import"},
        {"event_type": "import_completed", "target_type": "import", "target_id": uuid4()},
        {"event_type": "import_failed", "target_type": "import"},
        {"event_type": "analysis_requested", "target_type": "analysis_run",
         "target_id": uuid4(), "metadata": {"mode": "manual"}},
        {"event_type": "schedule_updated", "target_type": "analysis_schedule",
         "metadata": {"enabled": True}},
        {"event_type": "github_connection_started", "target_type": "github_connection"},
        {"event_type": "github_installation_authorized", "target_type": "github_connection"},
        {"event_type": "github_repository_selected", "target_type": "github_connection",
         "metadata": {"private": True}},
        {"event_type": "github_disconnected", "target_type": "github_connection"},
    ],
)
def test_server_call_sites_match_exact_event_contract(monkeypatch, event):
    database = _Database()
    monkeypatch.setattr(analytics_module, "ActivityEventRepository", _Repository)
    AnalyticsService(database, WorkspaceIdentity(uuid4(), "server-user")).track_event(**event)
    assert database.write_flags == [False]


def test_view_event_does_not_require_editor_permission(monkeypatch):
    database = _Database()
    monkeypatch.setattr(analytics_module, "ActivityEventRepository", _Repository)
    service = AnalyticsService(database, WorkspaceIdentity(uuid4(), "viewer-user"))

    service.track_event(
        event_type="item_viewed",
        target_type="item",
        target_id=uuid4(),
        metadata={"sourceType": "note"},
    )

    assert database.write_flags == [False]


def test_client_view_event_rejects_a_target_missing_from_the_workspace(monkeypatch):
    class _MissingTargetRepository(_Repository):
        def client_target_exists(self, **_target):
            return False

    database = _Database()
    monkeypatch.setattr(
        analytics_module, "ActivityEventRepository", _MissingTargetRepository
    )
    service = AnalyticsService(database, WorkspaceIdentity(uuid4(), "viewer-user"))

    with pytest.raises(ValueError, match="target is unavailable"):
        service.track_event(
            event_type="item_viewed",
            target_type="item",
            target_id=uuid4(),
            metadata={"sourceType": "note"},
        )


def test_browser_event_rate_limit_is_checked_inside_the_insert_transaction(monkeypatch):
    class _ExhaustedRepository(_Repository):
        def reserve_client_event_slot(self, **_budget):
            return False

    database = _Database()
    monkeypatch.setattr(analytics_module, "ActivityEventRepository", _ExhaustedRepository)
    service = AnalyticsService(database, WorkspaceIdentity(uuid4(), "busy-user"))

    with pytest.raises(AnalyticsRateLimited):
        service.track_event(event_type="capture_started", target_type="capture")
    assert database.write_flags == [False]


def test_expected_browser_rate_limit_does_not_amplify_warning_logs(caplog):
    class _LimitedAnalytics:
        workspace_id = uuid4()

        def track_event(self, **_event):
            raise AnalyticsRateLimited

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        track_event_best_effort(
            _LimitedAnalytics(), event_type="capture_started", target_type="capture"
        )
    assert caplog.records == []


@pytest.mark.parametrize(
    "event",
    [
        {
            "event_type": "flare_viewed",
            "target_type": "flare",
            "metadata": {"source": "insights_feed"},
        },
        {
            "event_type": "screen_opened",
            "target_type": "screen",
            "target_id": str(uuid4()),
            "metadata": {"screen": "sources_from_insights"},
        },
        {
            "event_type": "capture_submitted",
            "target_type": "import",
            "target_id": str(uuid4()),
            "metadata": {"sourceType": "file"},
        },
    ],
)
def test_event_target_contract_rejects_missing_or_mismatched_targets(event):
    service = AnalyticsService(_Database(), WorkspaceIdentity(uuid4(), "member-user"))
    with pytest.raises(ValueError):
        service.track_event(**event)


def test_best_effort_warning_contains_only_safe_dimensions(caplog):
    workspace_id = uuid4()

    class _BrokenAnalytics:
        def __init__(self):
            self.workspace_id = workspace_id

        def track_event(self, **_event):
            raise RuntimeError("PRIVATE NOTE BODY oauth-code provider-payload")

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        track_event_best_effort(_BrokenAnalytics(), event_type="item_created")

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "uvicorn.error"
    ]
    assert messages == [
        f"analytics_event event_type=item_created workspace_id={workspace_id} status=dropped"
    ]
    assert "PRIVATE" not in caplog.text
    assert "oauth-code" not in caplog.text
    assert "provider-payload" not in caplog.text


def test_best_effort_warning_does_not_log_an_unrecognized_event_name(caplog):
    workspace_id = uuid4()

    class _BrokenAnalytics:
        def __init__(self):
            self.workspace_id = workspace_id

        def track_event(self, **_event):
            raise RuntimeError("ignored")

    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        track_event_best_effort(
            _BrokenAnalytics(),
            event_type="PRIVATE_OAUTH_TOKEN_AS_EVENT_NAME",
        )

    message = next(
        record.getMessage()
        for record in caplog.records
        if record.name == "uvicorn.error"
    )
    assert message == f"analytics_event event_type=invalid workspace_id={workspace_id} status=dropped"
    assert "PRIVATE_OAUTH_TOKEN_AS_EVENT_NAME" not in caplog.text


def test_client_endpoint_keeps_storage_failure_best_effort_and_logs_safely(caplog):
    workspace_id = uuid4()

    class _BrokenAnalytics:
        def __init__(self):
            self.workspace_id = workspace_id

        def track_event(self, **_event):
            raise RuntimeError("PRIVATE QUERY BODY AND DATABASE DETAILS")

    payload = AnalyticsEventRequest.model_validate(
        {"eventType": "capture_started", "targetType": "capture"}
    )
    with caplog.at_level(logging.WARNING, logger="uvicorn.error"):
        assert analytics_api.track_event(payload, _BrokenAnalytics()) is None

    message = next(
        record.getMessage()
        for record in caplog.records
        if record.name == "uvicorn.error"
    )
    assert message == (
        f"analytics_event event_type=capture_started workspace_id={workspace_id} status=dropped"
    )
    assert "PRIVATE QUERY BODY" not in caplog.text
    assert "DATABASE DETAILS" not in caplog.text


def test_container_disables_uvicorn_raw_access_log():
    dockerfile = Path(__file__).parents[1] / "Dockerfile"
    assert '"--no-access-log"' in dockerfile.read_text(encoding="utf-8")
