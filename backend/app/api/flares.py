"""Authenticated read endpoints only; no Analyze or Flare creation route."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict
from app.api.auth import current_user
from app.api.routes import _database
from app.models.database import Database, MembershipRequiredError
from app.services.auth_service import AuthenticatedUser
from app.services.insight_service import FlareService, FlareNotFound


class EvidenceResponse(BaseModel):
    itemId: UUID
    sourceTitle: str
    sourceType: Literal['note','file','url','audio']
    excerpt: str
    sourceUrl: str | None


class FlareResponse(BaseModel):
    model_config=ConfigDict(populate_by_name=True)
    id: UUID
    type: Literal['Reminder','Warning','Recommendation']
    title: str
    statement: str
    action: str | None
    reason: str
    created_at: datetime=Field(serialization_alias='createdAt')
    evidence: list[EvidenceResponse]


def service(user: Annotated[AuthenticatedUser,Depends(current_user)],
            db: Annotated[Database,Depends(_database)]):
    return FlareService(db,user.identity)


router=APIRouter(prefix='/flares',tags=['flares'])


@router.get('',response_model=list[FlareResponse])
def list_flares(flares: Annotated[FlareService,Depends(service)],
                limit: Annotated[int,Query(ge=1,le=100)]=50):
    try:
        return flares.list(limit)
    except MembershipRequiredError:
        raise HTTPException(403,'Workspace membership is required') from None


@router.get('/{flare_id}',response_model=FlareResponse)
def get_flare(flare_id: UUID,flares: Annotated[FlareService,Depends(service)]):
    try:
        return flares.get(flare_id)
    except FlareNotFound:
        raise HTTPException(404,'Flare not found') from None
    except MembershipRequiredError:
        raise HTTPException(403,'Workspace membership is required') from None
