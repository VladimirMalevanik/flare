"""Authenticated GitHub App connection endpoints; ingestion is intentionally absent."""

from typing import Annotated, Literal

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import current_user, verified_user
from app.api.routes import _database
from app.config import GitHubSettings, load_github_settings
from app.integrations.github import (
    GitHubClient,
    GitHubInstallationNotAuthorized,
    GitHubProviderError,
    GitHubRepository,
)
from app.models.database import Database, MembershipRequiredError, WritePermissionRequiredError
from app.models.github_connections import GitHubConnectionRecord
from app.services.auth_service import AuthenticatedUser
from app.services.github_service import (
    GitHubConnectionNotFound,
    GitHubConnectionService,
    GitHubRepositoryUnavailable,
    InvalidGitHubState,
)

router = APIRouter(prefix="/integrations/github", tags=["integrations"])


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RepositorySelectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    repositoryId: int = Field(gt=0)


class GitHubRepositoryResponse(BaseModel):
    id: int
    owner: str
    name: str
    fullName: str
    private: bool
    htmlUrl: str


class GitHubConnectionResponse(BaseModel):
    status: Literal["disconnected", "pending", "connected"]
    accountLogin: str | None = None
    repository: GitHubRepositoryResponse | None = None


def session_user(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> AuthenticatedUser:
    if not request.cookies.get(request.app.state.settings.session_cookie_name):
        raise HTTPException(401, "Authentication required")
    return verified_user(request, user)


def github_settings(request: Request) -> GitHubSettings:
    configured = getattr(request.app.state, "github_settings", None)
    try:
        return configured or load_github_settings()
    except ValueError:
        raise HTTPException(503, "GitHub integration is not configured") from None


def github_client(request: Request, configured: Annotated[GitHubSettings, Depends(github_settings)]) -> GitHubClient:
    return getattr(request.app.state, "github_client", None) or GitHubClient(configured)


def service(
    user: Annotated[AuthenticatedUser, Depends(session_user)],
    database: Annotated[Database, Depends(_database)],
    configured: Annotated[GitHubSettings, Depends(github_settings)],
    client: Annotated[GitHubClient, Depends(github_client)],
) -> GitHubConnectionService:
    return GitHubConnectionService(database, user.identity, configured, client)


def repository_response(repository: GitHubRepository) -> GitHubRepositoryResponse:
    return GitHubRepositoryResponse(
        id=repository.id,
        owner=repository.owner,
        name=repository.name,
        fullName=repository.full_name,
        private=repository.private,
        htmlUrl=repository.html_url,
    )


def connection_response(record: GitHubConnectionRecord | None) -> GitHubConnectionResponse:
    if record is None:
        return GitHubConnectionResponse(status="disconnected")
    repository = None
    if record.repository_id is not None:
        repository = GitHubRepositoryResponse(
            id=record.repository_id,
            owner=record.repository_owner or "",
            name=record.repository_name or "",
            fullName=record.repository_full_name or "",
            private=bool(record.repository_private),
            htmlUrl=record.repository_html_url or "",
        )
    return GitHubConnectionResponse(
        status=record.status,
        accountLogin=record.account_login,
        repository=repository,
    )


def provider_failure() -> None:
    raise HTTPException(502, "GitHub could not complete the request")


@router.post("/start")
def start_connection(
    payload: EmptyRequest,
    connection: Annotated[GitHubConnectionService, Depends(service)],
):
    try:
        return {"authorizationUrl": connection.start()}
    except (MembershipRequiredError, WritePermissionRequiredError):
        raise HTTPException(403, "Workspace write permission is required") from None
    except psycopg.Error:
        raise HTTPException(503, "GitHub connection storage is unavailable") from None


@router.get("/callback", response_class=RedirectResponse)
def callback(
    connection: Annotated[GitHubConnectionService, Depends(service)],
    configured: Annotated[GitHubSettings, Depends(github_settings)],
    installation_id: Annotated[int, Query(gt=0)],
    state: Annotated[str, Query(min_length=32, max_length=128)],
    code: Annotated[str, Query(min_length=1, max_length=256)],
    setup_action: Annotated[Literal["install", "update"], Query()] = "install",
):
    del setup_action
    try:
        connection.complete(state, installation_id, code)
    except InvalidGitHubState:
        raise HTTPException(400, "Invalid or expired GitHub connection state") from None
    except (MembershipRequiredError, WritePermissionRequiredError):
        raise HTTPException(403, "Workspace write permission is required") from None
    except GitHubInstallationNotAuthorized:
        raise HTTPException(403, "GitHub authorization does not permit this installation") from None
    except GitHubProviderError:
        provider_failure()
    except psycopg.Error:
        raise HTTPException(503, "GitHub connection storage is unavailable") from None
    separator = "&" if "?" in configured.frontend_return_url else "?"
    return RedirectResponse(f"{configured.frontend_return_url}{separator}github=select", status_code=303)


@router.get("", response_model=GitHubConnectionResponse)
def connection_status(connection: Annotated[GitHubConnectionService, Depends(service)]):
    try:
        return connection_response(connection.status())
    except MembershipRequiredError:
        raise HTTPException(403, "Workspace membership is required") from None
    except psycopg.Error:
        raise HTTPException(503, "GitHub connection storage is unavailable") from None


@router.get("/repositories", response_model=list[GitHubRepositoryResponse])
def repositories(connection: Annotated[GitHubConnectionService, Depends(service)]):
    try:
        return [repository_response(repository) for repository in connection.repositories()]
    except GitHubConnectionNotFound:
        raise HTTPException(404, "GitHub is not connected") from None
    except GitHubProviderError:
        provider_failure()
    except MembershipRequiredError:
        raise HTTPException(403, "Workspace membership is required") from None
    except psycopg.Error:
        raise HTTPException(503, "GitHub connection storage is unavailable") from None


@router.post("/repository", response_model=GitHubConnectionResponse)
def select_repository(
    payload: RepositorySelectionRequest,
    connection: Annotated[GitHubConnectionService, Depends(service)],
):
    try:
        return connection_response(connection.select_repository(payload.repositoryId))
    except GitHubConnectionNotFound:
        raise HTTPException(404, "GitHub is not connected") from None
    except GitHubRepositoryUnavailable:
        raise HTTPException(422, "Select a repository accessible to this installation") from None
    except (MembershipRequiredError, WritePermissionRequiredError):
        raise HTTPException(403, "Workspace write permission is required") from None
    except GitHubProviderError:
        provider_failure()
    except psycopg.Error:
        raise HTTPException(503, "GitHub connection storage is unavailable") from None


@router.delete("", status_code=204)
def disconnect(connection: Annotated[GitHubConnectionService, Depends(service)]):
    try:
        connection.disconnect()
    except (MembershipRequiredError, WritePermissionRequiredError):
        raise HTTPException(403, "Workspace write permission is required") from None
    except psycopg.Error:
        raise HTTPException(503, "GitHub connection storage is unavailable") from None
