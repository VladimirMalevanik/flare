"""Authenticated enqueue/status only; no provider invocation in the API process."""
from typing import Annotated, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import verified_user
from app.api.routes import _database
from app.config import load_ai_settings
from app.ai_engine.flare_config import load_flare_settings
from app.models.database import Database, MembershipRequiredError, WritePermissionRequiredError
from app.models.analysis_jobs import AnalysisJobs
from app.models.analysis_runs import NoEligibleContext
from app.services.analysis_jobs import AnalysisJobService
from app.services.auth_service import AuthenticatedUser
from app.workers.config import load_worker_settings

router = APIRouter(tags=['analysis'])


class EmptyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class RunResponse(BaseModel):
    id: UUID
    status: Literal['pending', 'processing', 'completed', 'failed']
    stage: Literal['analysis', 'flare_generation', 'completed', 'failed']
    selectedChunkCount: int = Field(ge=1, le=100)
    flareIds: list[UUID]
    error: str | None = None


def cookie_user(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(verified_user)],
) -> AuthenticatedUser:
    if not request.cookies.get(request.app.state.settings.session_cookie_name):
        raise HTTPException(401, 'Authentication required')
    return user


def service(database: Annotated[Database, Depends(_database)]):
    try:
        return AnalysisJobService(AnalysisJobs(database), load_ai_settings(), load_worker_settings())
    except ValueError:
        raise HTTPException(503, 'configuration') from None


def failure(error):
    if isinstance(error, (MembershipRequiredError, WritePermissionRequiredError, psycopg.errors.InsufficientPrivilege)):
        raise HTTPException(403, 'permission_denied') from None
    if isinstance(error, NoEligibleContext):
        raise HTTPException(422, 'no_eligible_context') from None
    if isinstance(error, (psycopg.IntegrityError, psycopg.errors.InvalidParameterValue)):
        raise HTTPException(409, 'selection_changed') from None
    raise HTTPException(503, 'database_unavailable') from None


@router.post('/analyze', response_model=RunResponse, status_code=202)
def analyze(payload: EmptyRequest, response: Response,
            user: Annotated[AuthenticatedUser, Depends(cookie_user)],
            jobs: Annotated[AnalysisJobService, Depends(service)],
            idempotency_key: Annotated[UUID, Header(alias='Idempotency-Key')]):
    try:
        generation = load_flare_settings().revision(jobs.ai)
        result = jobs.start_run(user.identity, idempotency_key, generation)
    except ValueError as error:
        if isinstance(error, NoEligibleContext):
            failure(error)
        raise HTTPException(503, 'configuration') from None
    except (psycopg.Error, MembershipRequiredError, WritePermissionRequiredError) as error:
        failure(error)
    response.status_code = 200 if result['status'] in ('completed', 'failed') else 202
    return result


@router.get('/analysis-runs/{run_id}', response_model=RunResponse)
def analysis_run(run_id: UUID, user: Annotated[AuthenticatedUser, Depends(cookie_user)],
                 database: Annotated[Database, Depends(_database)]):
    from app.models.analysis_runs import AnalysisRuns
    try:
        with database.workspace_transaction(user.identity) as conn:
            result = AnalysisRuns.read(conn, run_id)
    except (psycopg.Error, MembershipRequiredError) as error:
        failure(error)
    if result is None:
        raise HTTPException(404, 'run_not_found')
    return result
