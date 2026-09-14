"""Public HTTP routes."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.api.schemas import CreateItemRequest, HealthResponse, ItemResponse, UpdateItemRequest
from app.config import Settings
from app.api.auth import verified_user
from app.services.auth_service import AuthenticatedUser
from app.models.database import (
    Database,
    MembershipRequiredError,
    WritePermissionRequiredError,
    database_is_ready,
)
from app.services.item_service import (
    ItemConflictError,
    ItemNotFoundError,
    ItemService,
    ItemValidationError,
)
from app.services.analytics_service import AnalyticsService, track_event_best_effort

router = APIRouter()


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _database(request: Request) -> Database:
    database = request.app.state.database
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    return database


def _analytics_service(
    user: Annotated[AuthenticatedUser, Depends(verified_user)],
    database: Annotated[Database, Depends(_database)],
) -> AnalyticsService:
    return AnalyticsService(database, user.identity)


def _item_service(
    user: Annotated[AuthenticatedUser, Depends(verified_user)],
    database: Annotated[Database, Depends(_database)],
) -> ItemService:
    return ItemService(database, user.identity)


def _search_query(
    query: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> str | None:
    if query is None:
        return None
    normalized = query.strip()
    if not normalized:
        raise HTTPException(status_code=422, detail="query must contain non-whitespace text")
    return normalized


def _raise_http_error(error: Exception) -> None:
    if isinstance(error, ItemNotFoundError):
        raise HTTPException(status_code=404, detail="Item not found") from None
    if isinstance(error, ItemConflictError):
        raise HTTPException(
            status_code=409,
            detail="Item changed since it was loaded; reload it and retry",
        ) from None
    if isinstance(error, ItemValidationError):
        raise HTTPException(status_code=422, detail=str(error)) from None
    if isinstance(error, MembershipRequiredError):
        raise HTTPException(status_code=403, detail="Workspace membership is required") from None
    if isinstance(error, WritePermissionRequiredError):
        raise HTTPException(status_code=403, detail="Workspace write permission is required") from None
    raise error


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse, tags=["health"])
def ready(request: Request) -> HealthResponse:
    """Check the migration and the restricted runtime database role."""
    application_settings = _settings(request)
    if not application_settings.database_url:
        raise HTTPException(status_code=503, detail="Database is not configured")
    try:
        if not database_is_ready(application_settings.database_url):
            raise HTTPException(status_code=503, detail="Database is not initialized")
    except psycopg.Error:
        # Never expose connection strings, credentials or SQL details over HTTP.
        raise HTTPException(status_code=503, detail="Database is unavailable") from None
    return HealthResponse(status="ready")


@router.post(
    "/items",
    response_model=ItemResponse,
    response_model_by_alias=True,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
    tags=["items"],
)
def create_item(
    payload: CreateItemRequest,
    service: Annotated[ItemService, Depends(_item_service)],
    analytics: Annotated[AnalyticsService, Depends(_analytics_service)],
) -> ItemResponse:
    if payload.type == "audio":
        raise HTTPException(
            status_code=422,
            detail="Voice memos must contain a validated transcript",
        )
    content = payload.effective_content()
    if not content:
        raise HTTPException(status_code=422, detail="content is required for this item type")
    if payload.type == "url" and not payload.source_url:
        raise HTTPException(status_code=422, detail="sourceUrl is required for url items")
    if payload.type == "file" and not payload.file_name:
        raise HTTPException(status_code=422, detail="fileName is required for file items")
    try:
        item = ItemResponse.from_record(
            service.create_item(
                item_type=payload.type,
                title=payload.title,
                content=content,
                source_url=payload.source_url,
                file_name=payload.file_name,
                file_size=payload.file_size,
                file_type=payload.file_type,
            )
        )
        track_event_best_effort(
            analytics,
            event_type="item_created",
            target_type="item",
            target_id=str(item.id),
            metadata={"item_type": payload.type},
        )
        return item
    except (MembershipRequiredError, WritePermissionRequiredError) as error:
        _raise_http_error(error)


@router.get(
    "/items",
    response_model=list[ItemResponse],
    response_model_by_alias=True,
    response_model_exclude_none=True,
    tags=["items"],
)
def list_items(
    service: Annotated[ItemService, Depends(_item_service)],
    query: Annotated[str | None, Depends(_search_query)],
    type: Annotated[
        Literal["all", "note", "url", "file", "audio"],
        Query(),
    ] = "all",
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    before_updated_at: Annotated[
        datetime | None,
        Query(alias="beforeUpdatedAt"),
    ] = None,
    before_id: Annotated[UUID | None, Query(alias="beforeId")] = None,
) -> list[ItemResponse]:
    if (before_updated_at is None) != (before_id is None):
        raise HTTPException(422, "beforeUpdatedAt and beforeId must be provided together")
    if before_updated_at is not None and before_updated_at.tzinfo is None:
        raise HTTPException(422, "beforeUpdatedAt must include a timezone")
    try:
        records = service.list_items(
            query=query,
            item_type=None if type == "all" else type,
            limit=limit,
            before_updated_at=before_updated_at,
            before_id=before_id,
        )
        return [ItemResponse.from_record(record) for record in records]
    except MembershipRequiredError as error:
        _raise_http_error(error)


@router.patch(
    "/items/{item_id}",
    response_model=ItemResponse,
    response_model_by_alias=True,
    response_model_exclude_none=True,
    tags=["items"],
)
def update_item(
    item_id: UUID,
    payload: UpdateItemRequest,
    service: Annotated[ItemService, Depends(_item_service)],
    analytics: Annotated[AnalyticsService, Depends(_analytics_service)],
) -> ItemResponse:
    try:
        result = service.update_item(
            item_id,
            expected_current_version_id=payload.expected_current_version_id,
            changes=payload.changes(),
        )
        item = ItemResponse.from_record(result.item)
        if result.changed:
            safe_metadata = {
                "item_type": item.type,
                "version_number": item.version_number,
            }
            track_event_best_effort(
                analytics,
                event_type="item_updated",
                target_type="item",
                target_id=str(item.id),
                metadata=safe_metadata,
            )
            if result.source_replaced:
                track_event_best_effort(
                    analytics,
                    event_type="source_replaced",
                    target_type="item",
                    target_id=str(item.id),
                    metadata=safe_metadata,
                )
        return item
    except (
        ItemConflictError,
        ItemNotFoundError,
        ItemValidationError,
        MembershipRequiredError,
        WritePermissionRequiredError,
    ) as error:
        _raise_http_error(error)


@router.get(
    "/items/{item_id}",
    response_model=ItemResponse,
    response_model_by_alias=True,
    response_model_exclude_none=True,
    tags=["items"],
)
def get_item(
    item_id: UUID,
    service: Annotated[ItemService, Depends(_item_service)],
    analytics: Annotated[AnalyticsService, Depends(_analytics_service)],
) -> ItemResponse:
    try:
        item = ItemResponse.from_record(service.get_item(item_id))
        track_event_best_effort(
            analytics,
            event_type="item_viewed",
            target_type="item",
            target_id=str(item.id),
            metadata={"sourceType": item.type},
        )
        return item
    except (ItemNotFoundError, MembershipRequiredError) as error:
        _raise_http_error(error)


@router.delete(
    "/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    tags=["items"],
)
def delete_item(
    item_id: UUID,
    service: Annotated[ItemService, Depends(_item_service)],
    analytics: Annotated[AnalyticsService, Depends(_analytics_service)],
) -> Response:
    try:
        service.delete_item(item_id)
        track_event_best_effort(
            analytics,
            event_type="item_deleted",
            target_type="item",
            target_id=str(item_id),
        )
    except (ItemNotFoundError, MembershipRequiredError, WritePermissionRequiredError) as error:
        _raise_http_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
