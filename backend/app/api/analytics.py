"""Operational analytics for actions and feature adoption."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.auth import verified_user
from app.api.schemas import AnalyticsEventRequest, AnalyticsSummary
from app.api.routes import _database
from app.models.database import Database, MembershipRequiredError
from app.services.auth_service import AuthenticatedUser
from app.services.analytics_service import (
    AnalyticsService,
    CLIENT_EVENTS,
    InvalidEventType,
    log_dropped_event,
)


router = APIRouter(prefix="/analytics", tags=["analytics"])


def service(
    user: Annotated[AuthenticatedUser, Depends(verified_user)],
    db: Annotated[Database, Depends(_database)],
):
    return AnalyticsService(db, user.identity)


@router.post("/events", status_code=202)
def track_event(
    payload: AnalyticsEventRequest,
    analytics: Annotated[AnalyticsService, Depends(service)],
) -> None:
    if payload.event_type not in CLIENT_EVENTS:
        raise HTTPException(status_code=422, detail="Invalid client analytics event")
    try:
        analytics.track_event(
            event_type=payload.event_type,
            target_type=payload.target_type,
            target_id=payload.target_id,
            metadata=payload.metadata,
        )
    except (InvalidEventType, ValueError):
        raise HTTPException(status_code=422, detail="Invalid event type") from None
    except MembershipRequiredError:
        raise HTTPException(status_code=403, detail="Workspace membership is required") from None
    except Exception:
        # Client telemetry is best effort. Keep the product action successful,
        # and do not put a database/provider error into structured logs.
        log_dropped_event(analytics, payload.event_type)


@router.get("/events", response_model=AnalyticsSummary)
def summarize_events(
    analytics: Annotated[AnalyticsService, Depends(service)],
    window_hours: Annotated[int, Query(ge=1, le=720)] = 24,
) -> AnalyticsSummary:
    try:
        return AnalyticsSummary(**analytics.summary(window_hours=window_hours))
    except MembershipRequiredError:
        raise HTTPException(status_code=403, detail="Workspace membership is required") from None
