"""Owner-managed UTM links and public aggregate redirect counting."""

from datetime import date, datetime
import threading
from typing import Annotated, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import verified_user
from app.api.routes import _database
from app.models.campaign_links import (
    CampaignLinkLimitReached,
    CampaignLinkNotFound,
    CampaignLinkOpener,
    CampaignLinkRecord,
    CampaignLinkRepository,
    SLUG_PATTERN,
)
from app.models.database import Database, MembershipRequiredError, WritePermissionRequiredError
from app.services.auth_service import AuthenticatedUser
from app.services.campaign_links import (
    CampaignLinkService,
    InvalidCampaignLink,
    destination_url,
    public_origin,
)
from app.services.developer_mail import can_send as has_internal_account_grant


router = APIRouter(prefix="/campaign-links", tags=["campaign-links"])
_REDIRECT_CAPACITY = 4
_REDIRECT_INTAKE = threading.BoundedSemaphore(_REDIRECT_CAPACITY)


class CreateCampaignLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    label: str = Field(min_length=1, max_length=80)
    destination_path: str = Field(alias="destinationPath", min_length=1, max_length=20)
    utm_source: str = Field(alias="utmSource", min_length=1, max_length=80)
    utm_medium: str = Field(alias="utmMedium", min_length=1, max_length=80)
    utm_campaign: str = Field(alias="utmCampaign", min_length=1, max_length=80)
    utm_content: str | None = Field(default=None, alias="utmContent", max_length=80)


class UpdateCampaignLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    label: str = Field(min_length=1, max_length=80)


class CampaignLinkResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: UUID
    label: str
    slug: str
    short_url: str = Field(alias="shortUrl")
    destination_path: str = Field(alias="destinationPath")
    utm_source: str = Field(alias="utmSource")
    utm_medium: str = Field(alias="utmMedium")
    utm_campaign: str = Field(alias="utmCampaign")
    utm_content: str | None = Field(alias="utmContent")
    click_count: int = Field(alias="clickCount", ge=0)
    created_at: datetime = Field(alias="createdAt")
    archived_at: datetime | None = Field(alias="archivedAt")


class CampaignActivityDay(BaseModel):
    date: date
    opens: int | None = Field(ge=0)


class CampaignActivityLink(BaseModel):
    id: UUID
    label: str
    opens: int = Field(ge=0)
    archivedAt: datetime | None


class CampaignActivityResponse(BaseModel):
    days: Literal[7, 30, 90]
    timezone: Literal["UTC"]
    generatedAt: datetime
    recordingStartedAt: datetime | None
    totalOpens: int = Field(ge=0)
    daily: list[CampaignActivityDay]
    topLinks: list[CampaignActivityLink]


def _can_manage(request: Request, user: AuthenticatedUser) -> bool:
    settings = request.app.state.settings
    # Local development identities have no mailbox. Keep the fixture/demo path
    # usable outside production while the deployed service fails closed unless
    # the exact verified account ID and email are privately granted.
    internal = (
        settings.dev_mode and settings.environment in {"development", "test"}
        and settings.dev_user_id == user.user_id
        and settings.dev_workspace_id == user.workspace_id
    ) or has_internal_account_grant(user, settings.developer_mail_accounts)
    return user.role == "owner" and internal


def _owner(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(verified_user)],
) -> AuthenticatedUser:
    if not _can_manage(request, user):
        raise HTTPException(
            403,
            {"code": "campaign_links_forbidden", "message": "Campaign links are unavailable for this account."},
        )
    return user


def _service(
    user: Annotated[AuthenticatedUser, Depends(_owner)],
    database: Annotated[Database, Depends(_database)],
) -> CampaignLinkService:
    return CampaignLinkService(CampaignLinkRepository(database, user.identity))


def _error(error: Exception) -> None:
    if isinstance(error, CampaignLinkNotFound):
        raise HTTPException(404, {"code": "campaign_link_not_found", "message": "Campaign link not found."}) from None
    if isinstance(error, CampaignLinkLimitReached):
        raise HTTPException(409, {"code": "campaign_link_limit", "message": "Archive a link before creating another one."}) from None
    if isinstance(error, InvalidCampaignLink):
        raise HTTPException(422, {"code": str(error), "message": "Check the campaign link fields."}) from None
    if isinstance(error, (MembershipRequiredError, WritePermissionRequiredError, psycopg.errors.InsufficientPrivilege)):
        raise HTTPException(403, {"code": "campaign_links_forbidden", "message": "Campaign links are unavailable for this account."}) from None
    if isinstance(error, psycopg.Error):
        raise HTTPException(503, {"code": "campaign_links_unavailable", "message": "Campaign links are temporarily unavailable."}) from None
    raise error


def _campaign_origin(request: Request) -> str:
    try:
        return public_origin(
            request.app.state.settings.app_public_url,
            str(request.base_url),
        )
    except InvalidCampaignLink:
        raise HTTPException(
            503,
            {"code": "campaign_links_unavailable", "message": "Campaign links are temporarily unavailable."},
        ) from None


def _response(record: CampaignLinkRecord, origin: str) -> CampaignLinkResponse:
    return CampaignLinkResponse(
        id=record.id,
        label=record.label,
        slug=record.slug,
        shortUrl=f"{origin}/r/{record.slug}",
        destinationPath=record.destination_path,
        utmSource=record.utm_source,
        utmMedium=record.utm_medium,
        utmCampaign=record.utm_campaign,
        utmContent=record.utm_content,
        clickCount=record.click_count,
        createdAt=record.created_at,
        archivedAt=record.archived_at,
    )


@router.get("/r/{slug}", response_class=RedirectResponse)
def open_campaign_link(
    slug: str,
    database: Annotated[Database, Depends(_database)],
) -> Response:
    # Reject malformed probes before they can occupy either redirect capacity
    # or a database-pool connection.
    if not SLUG_PATTERN.fullmatch(slug):
        raise HTTPException(404, "Campaign link not found")
    if not _REDIRECT_INTAKE.acquire(blocking=False):
        raise HTTPException(
            503,
            "Campaign links are temporarily busy",
            headers={"Retry-After": "1"},
        )
    try:
        try:
            destination = CampaignLinkOpener(database).open(slug)
        except Exception:
            raise HTTPException(503, "Campaign link is temporarily unavailable") from None
    finally:
        _REDIRECT_INTAKE.release()
    if destination is None:
        raise HTTPException(404, "Campaign link not found")
    response = RedirectResponse(destination_url(destination), status_code=302)
    response.headers["Cache-Control"] = "no-store"
    return response


@router.get("", response_model=list[CampaignLinkResponse])
def list_campaign_links(
    request: Request,
    links: Annotated[CampaignLinkService, Depends(_service)],
) -> list[CampaignLinkResponse]:
    try:
        origin = _campaign_origin(request)
        return [_response(record, origin) for record in links.list()]
    except Exception as error:
        _error(error)


@router.get("/capability")
def campaign_links_capability(
    request: Request,
    response: Response,
    user: Annotated[AuthenticatedUser, Depends(verified_user)],
) -> dict[str, bool]:
    response.headers["Cache-Control"] = "no-store"
    return {"allowed": _can_manage(request, user)}


@router.post("", response_model=CampaignLinkResponse, status_code=201)
def create_campaign_link(
    payload: CreateCampaignLinkRequest,
    request: Request,
    links: Annotated[CampaignLinkService, Depends(_service)],
) -> CampaignLinkResponse:
    try:
        # Validate the canonical frontend origin before committing the row. A
        # copied /r link must never point at the internal API host.
        origin = _campaign_origin(request)
        record = links.create(
            label=payload.label,
            destination_path=payload.destination_path,
            utm_source=payload.utm_source,
            utm_medium=payload.utm_medium,
            utm_campaign=payload.utm_campaign,
            utm_content=payload.utm_content,
        )
        return _response(record, origin)
    except Exception as error:
        _error(error)


@router.get("/activity", response_model=CampaignActivityResponse)
def campaign_link_activity(
    response: Response,
    user: Annotated[AuthenticatedUser, Depends(_owner)],
    database: Annotated[Database, Depends(_database)],
    days: Annotated[int, Query(ge=7, le=90)] = 30,
    link_id: Annotated[UUID | None, Query(alias="linkId")] = None,
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    if days not in {7, 30, 90}:
        raise HTTPException(422, "Choose a 7, 30 or 90 day period.")
    try:
        return CampaignLinkRepository(database, user.identity).activity(days, link_id)
    except Exception as error:
        _error(error)


@router.get("/{link_id}", response_model=CampaignLinkResponse)
def get_campaign_link(
    link_id: UUID,
    request: Request,
    links: Annotated[CampaignLinkService, Depends(_service)],
) -> CampaignLinkResponse:
    try:
        origin = _campaign_origin(request)
        return _response(links.get(link_id), origin)
    except Exception as error:
        _error(error)


@router.patch("/{link_id}", response_model=CampaignLinkResponse)
def update_campaign_link(
    link_id: UUID,
    payload: UpdateCampaignLinkRequest,
    request: Request,
    links: Annotated[CampaignLinkService, Depends(_service)],
) -> CampaignLinkResponse:
    try:
        origin = _campaign_origin(request)
        return _response(links.rename(link_id, payload.label), origin)
    except Exception as error:
        _error(error)


@router.post("/{link_id}/archive", response_model=CampaignLinkResponse)
def archive_campaign_link(
    link_id: UUID,
    request: Request,
    links: Annotated[CampaignLinkService, Depends(_service)],
) -> CampaignLinkResponse:
    try:
        origin = _campaign_origin(request)
        return _response(links.archive(link_id), origin)
    except Exception as error:
        _error(error)
