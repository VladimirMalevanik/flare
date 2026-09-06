"""Public HTTP routes."""

from typing import Annotated, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.api.schemas import CreateItemRequest, HealthResponse, ItemResponse
from app.config import Settings
from app.models.database import (
    Database,
    MembershipRequiredError,
    WorkspaceIdentity,
    WritePermissionRequiredError,
    database_is_ready,
)
from app.services.item_service import ItemNotFoundError, ItemService

router = APIRouter()


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _database(request: Request) -> Database:
    database = request.app.state.database
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    return database


def _item_service(
    application_settings: Annotated[Settings, Depends(_settings)],
    database: Annotated[Database, Depends(_database)],
) -> ItemService:
    if not application_settings.dev_mode:
        raise HTTPException(
            status_code=503,
            detail="Item API requires authentication; development identity is disabled",
        )
    try:
        workspace_id, user_id, _ = application_settings.require_dev_identity()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from None
    return ItemService(database, WorkspaceIdentity(workspace_id, user_id))


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
) -> ItemResponse:
    try:
        return ItemResponse.from_record(
            service.create_note(title=payload.title, content=payload.content)
        )
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
) -> list[ItemResponse]:
    try:
        records = service.list_items(
            query=query,
            item_type=None if type == "all" else type,
            limit=limit,
        )
        return [ItemResponse.from_record(record) for record in records]
    except MembershipRequiredError as error:
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
) -> ItemResponse:
    try:
        return ItemResponse.from_record(service.get_item(item_id))
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
) -> Response:
    try:
        service.delete_item(item_id)
    except (ItemNotFoundError, MembershipRequiredError, WritePermissionRequiredError) as error:
        _raise_http_error(error)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
