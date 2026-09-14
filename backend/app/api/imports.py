"""Authenticated JSON imports for bounded CSV, TXT and Markdown files."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.auth import verified_user
from app.api.schemas import CreateImportRequest, ImportResponse, ItemResponse
from app.models.database import (
    Database,
    MembershipRequiredError,
    WritePermissionRequiredError,
)
from app.services.analytics_service import AnalyticsService
from app.services.auth_service import AuthenticatedUser
from app.services.import_service import (
    ImportNotFoundError,
    ImportResult,
    ImportService,
    ImportUnavailableError,
    ImportValidationError,
)


router = APIRouter(tags=["imports"])


def _database(request: Request) -> Database:
    database = request.app.state.database
    if database is None:
        raise HTTPException(status_code=503, detail="Database is not configured")
    return database


def _import_service(
    user: Annotated[AuthenticatedUser, Depends(verified_user)],
    database: Annotated[Database, Depends(_database)],
) -> ImportService:
    return ImportService(database, user.identity)


def _analytics_service(
    user: Annotated[AuthenticatedUser, Depends(verified_user)],
    database: Annotated[Database, Depends(_database)],
) -> AnalyticsService:
    return AnalyticsService(database, user.identity)


def _response(result: ImportResult) -> ImportResponse:
    if result.batch.document_version_id is None:
        raise RuntimeError("Completed import has no source version")
    return ImportResponse(
        id=result.batch.id,
        format=result.batch.format,
        file_name=result.batch.file_name,
        item=ItemResponse.from_record(result.item),
        source_version_id=result.batch.document_version_id,
        superseded_at=result.batch.superseded_at,
        row_count=result.batch.row_count,
        chunk_count=result.batch.chunk_count,
        analysis_jobs_queued=result.batch.analysis_jobs_queued,
    )


def _track_safely(analytics: AnalyticsService, event_type: str, *, batch_id: UUID | None = None) -> None:
    """Product telemetry must not make a successful import unavailable."""
    try:
        analytics.track_event(
            event_type=event_type,
            target_type="import",
            target_id=str(batch_id) if batch_id else None,
        )
    except Exception:
        # The event sink is intentionally best-effort during staged migration
        # deploys. It receives no source content or other sensitive metadata.
        return


@router.post(
    "/imports",
    response_model=ImportResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_201_CREATED,
)
def create_import(
    payload: CreateImportRequest,
    response: Response,
    service: Annotated[ImportService, Depends(_import_service)],
    analytics: Annotated[AnalyticsService, Depends(_analytics_service)],
) -> ImportResponse:
    _track_safely(analytics, "import_started")
    try:
        result = service.create_import(
            format=payload.format,
            file_name=payload.file_name,
            file_type=payload.file_type,
            file_size=payload.file_size,
            content=payload.content,
        )
    except ImportValidationError as error:
        _track_safely(analytics, "import_failed")
        raise HTTPException(status_code=422, detail=error.detail) from None
    except (MembershipRequiredError, WritePermissionRequiredError) as error:
        detail = (
            "Workspace membership is required"
            if isinstance(error, MembershipRequiredError)
            else "Workspace write permission is required"
        )
        raise HTTPException(status_code=403, detail=detail) from None
    except ImportUnavailableError:
        raise HTTPException(status_code=409, detail="An import with this content is not available") from None

    _track_safely(analytics, "import_completed", batch_id=result.batch.id)
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return _response(result)


@router.get(
    "/imports/{batch_id}",
    response_model=ImportResponse,
    response_model_by_alias=True,
)
def get_import(
    batch_id: UUID,
    service: Annotated[ImportService, Depends(_import_service)],
) -> ImportResponse:
    try:
        return _response(service.get_import(batch_id))
    except (ImportNotFoundError, MembershipRequiredError):
        # Preserve tenant isolation: an inaccessible batch is indistinguishable
        # from an unknown one.
        raise HTTPException(status_code=404, detail="Import not found") from None
