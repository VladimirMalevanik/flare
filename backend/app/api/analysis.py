"""Historical run status; new analyses are started by the scheduler only."""
from typing import Annotated, Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.auth import verified_user
from app.api.routes import _database
from app.models.database import Database, MembershipRequiredError, WritePermissionRequiredError
from app.models.analysis_runs import DailyLimitReached, NoEligibleContext
from app.services.auth_service import AuthenticatedUser

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


def failure(error):
    if isinstance(error, (MembershipRequiredError, WritePermissionRequiredError, psycopg.errors.InsufficientPrivilege)):
        raise HTTPException(403, 'permission_denied') from None
    if isinstance(error, NoEligibleContext):
        raise HTTPException(422, error.code) from None
    if isinstance(error, DailyLimitReached):
        raise HTTPException(409, 'daily_limit') from None
    if isinstance(error, (psycopg.IntegrityError, psycopg.errors.InvalidParameterValue)):
        raise HTTPException(409, 'selection_changed') from None
    raise HTTPException(503, 'database_unavailable') from None


@router.post('/analyze', deprecated=True, responses={410: {'description': 'Manual analysis was removed; configure a daily schedule.'}})
def analyze(payload: EmptyRequest,
            user: Annotated[AuthenticatedUser, Depends(cookie_user)],
            idempotency_key: Annotated[UUID, Header(alias='Idempotency-Key')]):
    # Keep authentication/origin/body checks for old clients, but never resolve
    # AI settings or reserve a cycle/job/provider budget for a manual request.
    raise HTTPException(410, 'scheduled_analysis_only')


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
