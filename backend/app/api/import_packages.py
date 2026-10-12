"""Authenticated bounded ZIP session API."""
from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, ConfigDict, Field
from app.api.auth import verified_user
from app.api.routes import _database
from app.models.database import MembershipRequiredError, WritePermissionRequiredError
from app.models.import_packages import ImportPackages, ImportPackageError
from app.services.auth_service import AuthenticatedUser
from app.services.import_packages import ImportPackageService

router = APIRouter(prefix='/imports/packages',tags=['imports'])


class CreatePackage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sourceKind: Literal['notion','obsidian']
    fileName: str = Field(min_length=1,max_length=255)
    fileSize: int = Field(gt=0,strict=True)
    requestKey: UUID


def service(request: Request, user: Annotated[AuthenticatedUser,Depends(verified_user)]):
    return ImportPackageService(ImportPackages(_database(request),user.identity),
        request.app.state.import_storage,request.app.state.import_policy)


def handle(error):
    if isinstance(error,(MembershipRequiredError,WritePermissionRequiredError)):
        raise HTTPException(403,detail='Workspace write permission is required') from None
    if isinstance(error, ImportPackageError):
        code = error.code
        status = 404 if code=='not_found' else 403 if code=='forbidden' else 503 if code=='storage_unavailable' else 413 if code in {'compressed_bytes','staged_quota','source_quota'} else 409
        raise HTTPException(status,detail=code) from None
    if isinstance(error,(TimeoutError,OSError)):
        raise HTTPException(503,detail='upload_unavailable') from None
    raise error


@router.post('',status_code=201)
def create(payload: CreatePackage, svc: Annotated[ImportPackageService,Depends(service)]):
    try:
        return svc.create(source_kind=payload.sourceKind,file_name=payload.fileName,file_size=payload.fileSize,request_key=payload.requestKey)
    except (ImportPackageError,MembershipRequiredError,WritePermissionRequiredError,OSError) as e: handle(e)


@router.get('')
def list_packages(svc: Annotated[ImportPackageService,Depends(service)]):
    try: return svc.repo.list()
    except OSError as e: handle(e)


@router.get('/publications')
def publications(svc: Annotated[ImportPackageService,Depends(service)],after: int=Query(0,ge=0),limit: int=Query(50,ge=1,le=100)):
    limit=min(limit,svc.policy.report_page)
    try: rows=svc.repo.publications(after,limit)
    except OSError as e: handle(e)
    return {'publications':rows,'nextCursor':rows[-1]['id'] if len(rows)==limit else None}


@router.get('/capabilities')
def capabilities(svc: Annotated[ImportPackageService,Depends(service)]):
    available = svc.storage is not None
    if available and hasattr(svc.storage, 'ready'):
        try:
            available = svc.storage.ready()
        except OSError:
            available = False
    return {'available':available,'maxUploadBytes':svc.policy.compressed_bytes if available else None}


@router.get('/{package_id}')
def get(package_id: UUID, svc: Annotated[ImportPackageService,Depends(service)]):
    try: return svc.repo.get(package_id)
    except (ImportPackageError,OSError) as e: handle(e)


@router.get('/{package_id}/entries')
def entries(package_id: UUID,svc: Annotated[ImportPackageService,Depends(service)],after: int=Query(-1,ge=-1),limit: int=Query(50,ge=1,le=100)):
    try:
        limit=min(limit,svc.policy.report_page)
        rows=svc.repo.entries(package_id,after,limit)
        return {'entries':rows,'nextCursor':rows[-1]['ordinal'] if len(rows)==limit else None}
    except (ImportPackageError,OSError) as e: handle(e)


@router.put('/{package_id}/upload')
async def upload(package_id: UUID,request: Request,svc: Annotated[ImportPackageService,Depends(service)]):
    if request.headers.get('content-type','').split(';')[0]!='application/octet-stream':
        raise HTTPException(415,detail='Use application/octet-stream')
    try: return await svc.upload(package_id,request.stream())
    except (ImportPackageError,MembershipRequiredError,WritePermissionRequiredError,TimeoutError,OSError) as e: handle(e)


@router.post('/{package_id}/{action}')
def action(package_id: UUID,action: Literal['finalize','cancel','retry'],svc: Annotated[ImportPackageService,Depends(service)]):
    try:
        result=svc.repo.action(action,package_id)
        return svc.repo.get(UUID(result['id']))
    except (ImportPackageError,MembershipRequiredError,WritePermissionRequiredError,OSError) as e: handle(e)
