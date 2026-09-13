"""Operational endpoints for queue health, backlog and alerts."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.auth import verified_user
from app.api.routes import _database, _raise_http_error
from app.api.schemas import (
    QueueHealthResponse,
    QueueMaintenanceRequest,
    QueueMaintenanceResponse,
    QueueSummary,
)
from app.models.database import Database, WorkspaceIdentity, MembershipRequiredError
from app.services.analytics_service import AnalyticsService
from app.api.routes import _analytics_service
from app.services.auth_service import AuthenticatedUser
from app.services.ops_service import QueueHealth, QueueMaintenance, QueueService


router = APIRouter(prefix="/ops", tags=["ops"])


def _track_event_safely(analytics: AnalyticsService, **event: object) -> None:
    try:
        analytics.track_event(**event)
    except Exception:
        return


def _owner_required(
    user: Annotated[AuthenticatedUser, Depends(verified_user)],
) -> AuthenticatedUser:
    if user.role != "owner":
        raise HTTPException(status_code=403, detail="Workspace ownership is required")
    return user


def service(user: AuthenticatedUser = Depends(_owner_required),
            database: Database = Depends(_database)) -> "QueueService":
    identity = WorkspaceIdentity(user.workspace_id, user.user_id)
    return QueueService(database, identity)


def _to_schema(health: QueueHealth) -> QueueHealthResponse:
    return QueueHealthResponse(
        as_of=health.as_of,
        alerts=list(health.alerts),
        analysis=QueueSummary(
            pending=health.analysis.pending,
            processing=health.analysis.processing,
            completed=health.analysis.completed,
            failed=health.analysis.failed,
            due=health.analysis.due,
            stale_processing=health.analysis.stale_processing,
            oldest_pending_seconds=health.analysis.oldest_pending_seconds,
            oldest_processing_seconds=health.analysis.oldest_processing_seconds,
        ),
        flares=QueueSummary(
            pending=health.flares.pending,
            processing=health.flares.processing,
            completed=health.flares.completed,
            failed=health.flares.failed,
            due=health.flares.due,
            stale_processing=health.flares.stale_processing,
            oldest_pending_seconds=health.flares.oldest_pending_seconds,
            oldest_processing_seconds=health.flares.oldest_processing_seconds,
        ),
    )


def _to_maintenance_schema(maintenance: QueueMaintenance) -> QueueMaintenanceResponse:
    return QueueMaintenanceResponse(
        dry_run=maintenance.dry_run,
        applied=maintenance.applied,
        before=_to_schema(maintenance.before),
        after=_to_schema(maintenance.after),
        recovered_stale_analysis_jobs=maintenance.recovered_stale_analysis_jobs,
        recovered_stale_flare_runs=maintenance.recovered_stale_flare_runs,
        analysis_jobs={
            "candidates": maintenance.analysis_jobs_candidates,
            "deleted": maintenance.analysis_jobs_deleted,
        },
        flare_generation_runs={
            "candidates": maintenance.flare_generation_runs_candidates,
            "deleted": maintenance.flare_generation_runs_deleted,
        },
    )


@router.get("/queue", response_model=QueueHealthResponse)
def queue_health(
    user: Annotated[AuthenticatedUser, Depends(_owner_required)],
    op_service: Annotated[QueueService, Depends(service)],
    analytics: Annotated[AnalyticsService, Depends(_analytics_service)],
) -> QueueHealthResponse:
    try:
        _track_event_safely(analytics, event_type="queue_health_requested")
        return _to_schema(op_service.queue_health())
    except MembershipRequiredError as error:
        _raise_http_error(error)


@router.post("/queue/maintenance", response_model=QueueMaintenanceResponse)
def queue_maintenance(
    user: Annotated[AuthenticatedUser, Depends(_owner_required)],
    op_service: Annotated[QueueService, Depends(service)],
    analytics: Annotated[AnalyticsService, Depends(_analytics_service)],
    request: QueueMaintenanceRequest | None = None,
) -> QueueMaintenanceResponse:
    del user
    request = request or QueueMaintenanceRequest()
    try:
        result = _to_maintenance_schema(
            op_service.queue_maintenance(
                dry_run=request.dry_run,
                recover_stale=request.recover_stale,
                max_rows=request.max_rows,
                analysis_completed_retention_days=request.analysis_completed_retention_days,
                analysis_failed_retention_days=request.analysis_failed_retention_days,
                flare_completed_retention_days=request.flare_completed_retention_days,
                flare_failed_retention_days=request.flare_failed_retention_days,
            ),
        )
        _track_event_safely(
            analytics,
            event_type="queue_maintenance_run",
            metadata={
                "dry_run": request.dry_run,
                "recover_stale": request.recover_stale,
                "max_rows": request.max_rows,
                "analysis_completed_retention_days": request.analysis_completed_retention_days,
                "analysis_failed_retention_days": request.analysis_failed_retention_days,
                "flare_completed_retention_days": request.flare_completed_retention_days,
                "flare_failed_retention_days": request.flare_failed_retention_days,
            },
        )
        return result
    except MembershipRequiredError as error:
        _raise_http_error(error)
