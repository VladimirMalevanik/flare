"""Workspace daily-analysis schedule and status endpoints."""

import logging
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.analysis import cookie_user
from app.api.routes import _database
from app.models.database import Database, MembershipRequiredError, WritePermissionRequiredError
from app.models.analysis_schedules import AnalysisScheduleRepository
from app.services.analysis_schedule import AnalysisScheduleService, InvalidSchedule
from app.services.analytics_service import AnalyticsService
from app.services.auth_service import AuthenticatedUser


logger = logging.getLogger(__name__)
router = APIRouter(tags=["analysis"])


class ScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool
    timezone: str = Field(min_length=1, max_length=80)
    local_time: str = Field(alias="localTime", pattern=r"^\d{2}:\d{2}$")


class ScheduleResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool
    timezone: str
    local_time: str = Field(alias="localTime")
    lead_minutes: Literal[30] = Field(alias="leadMinutes")
    next_refresh_at: datetime | None = Field(alias="nextRefreshAt")
    next_run_at: datetime | None = Field(alias="nextRunAt")
    updated_at: datetime = Field(alias="updatedAt")


class GitHubSyncStatus(BaseModel):
    connected: bool
    ingestion_supported: Literal[False] = Field(alias="ingestionSupported")
    status: Literal["not_connected", "not_ingested"]


class SyncStatus(BaseModel):
    status: Literal["not_started", "running", "succeeded", "failed"]
    github: GitHubSyncStatus


class DailyStatusResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    local_date: str = Field(alias="localDate")
    timezone: str
    state: Literal["available", "scheduled", "refreshing", "ready", "queued", "processing", "completed", "failed"]
    cycle_id: UUID | None = Field(alias="cycleId")
    run_id: UUID | None = Field(alias="runId")
    mode: Literal["manual", "scheduled"] | None
    scheduled_for: datetime | None = Field(alias="scheduledFor")
    refresh_due_at: datetime | None = Field(alias="refreshDueAt")
    source_snapshot_count: int = Field(alias="sourceSnapshotCount", ge=0, le=100)
    can_request_today: bool = Field(alias="canRequestToday")
    reason: Literal["daily_limit", "no_eligible_context", "sync_failed"] | None
    sync: SyncStatus


def schedule_service(
    user: Annotated[AuthenticatedUser, Depends(cookie_user)],
    database: Annotated[Database, Depends(_database)],
) -> AnalysisScheduleService:
    return AnalysisScheduleService(AnalysisScheduleRepository(database, user.identity))


def _schedule_error(error: Exception) -> None:
    if isinstance(error, (MembershipRequiredError, WritePermissionRequiredError, psycopg.errors.InsufficientPrivilege)):
        raise HTTPException(403, "permission_denied") from None
    if isinstance(error, InvalidSchedule):
        raise HTTPException(422, str(error)) from None
    raise HTTPException(503, "database_unavailable") from None


@router.get("/analysis-schedule", response_model=ScheduleResponse)
def get_schedule(
    schedules: Annotated[AnalysisScheduleService, Depends(schedule_service)],
) -> dict:
    try:
        return schedules.get()
    except (psycopg.Error, MembershipRequiredError) as error:
        _schedule_error(error)


@router.put("/analysis-schedule", response_model=ScheduleResponse)
def put_schedule(
    payload: ScheduleRequest,
    user: Annotated[AuthenticatedUser, Depends(cookie_user)],
    database: Annotated[Database, Depends(_database)],
) -> dict:
    schedules = AnalysisScheduleService(AnalysisScheduleRepository(database, user.identity))
    try:
        result = schedules.put(
            enabled=payload.enabled,
            timezone_name=payload.timezone,
            local_time_value=payload.local_time,
        )
        try:
            AnalyticsService(database, user.identity).track_event(
                event_type="schedule_updated",
                target_type="analysis_schedule",
                metadata={"enabled": payload.enabled},
            )
        except Exception:
            pass
        logger.info(
            "analysis_schedule status=updated workspace_id=%s enabled=%s",
            user.identity.workspace_id,
            payload.enabled,
        )
        return result
    except (psycopg.Error, MembershipRequiredError, WritePermissionRequiredError, InvalidSchedule) as error:
        _schedule_error(error)


@router.get("/analysis/daily-status", response_model=DailyStatusResponse)
def daily_status(
    schedules: Annotated[AnalysisScheduleService, Depends(schedule_service)],
) -> dict:
    try:
        return schedules.daily_status()
    except (psycopg.Error, MembershipRequiredError) as error:
        _schedule_error(error)
