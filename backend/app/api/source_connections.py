"""Session-bound selected source connections; no credentials in public responses."""
from typing import Annotated, Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from app.api.auth import current_user, verified_user
from app.api.routes import _database
from app.services.auth_service import AuthenticatedUser
from app.models.database import Database
from app.models.source_connections import SourceConnectionRepository, SourceStateError
from app.integrations.sources.settings import load_source_settings, SourceSettings, PROVIDERS
from app.integrations.sources.credentials import CredentialUnavailable
from app.integrations.sources.contracts import SourceProviderError
from app.integrations.sources.http import ProviderHTTP
from app.config import load_github_settings
from app.services.source_sync import SourceService

router=APIRouter(prefix='/integrations/sources',tags=['integrations'])
Provider=Literal['slack','gmail','drive','notion','github']


class Empty(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)


class Selection(Empty):
    expectedRevision:int=Field(gt=0)
    resourceIds:list[str]=Field(max_length=20)
    shareWithWorkspace:bool=False


def session(request:Request,user:Annotated[AuthenticatedUser,Depends(current_user)]):
    if not request.cookies.get(request.app.state.settings.session_cookie_name): raise HTTPException(401,'Authentication required')
    return user


def writer(request:Request,user:Annotated[AuthenticatedUser,Depends(session)]):
    return verified_user(request,user)


def repository(user:Annotated[AuthenticatedUser,Depends(session)],database:Annotated[Database,Depends(_database)]):
    return SourceConnectionRepository(database,user.identity)


def configuration(request):
    try: settings=getattr(request.app.state,'source_settings',None) or load_source_settings()
    except ValueError: settings=SourceSettings()
    try: github=getattr(request.app.state,'github_settings',None) or load_github_settings()
    except ValueError: github=None
    return settings,github


def service(request:Request,repository:Annotated[SourceConnectionRepository,Depends(repository)],user:Annotated[AuthenticatedUser,Depends(writer)]):
    settings,github=configuration(request)
    if not settings.enabled or not repository.ready(): raise HTTPException(503,{'code':'source_not_enabled'})
    return SourceService(repository,settings,github,getattr(request.app.state,'source_http_factory',None) or ProviderHTTP)


def operation(call):
    try: return call()
    except CredentialUnavailable: raise HTTPException(409,{'code':'authorization_lost'}) from None
    except (SourceProviderError,SourceStateError) as error:
        status=403 if error.code in ('forbidden','connection_owned_by_another_user') else 503 if error.code in ('source_not_enabled','source_worker_unavailable','provider_unavailable') else 409
        raise HTTPException(status,{'code':error.code}) from None


@router.get('')
def connections(request:Request,repository:Annotated[SourceConnectionRepository,Depends(repository)]):
    settings,github=configuration(request)
    ready=repository.ready()
    health=operation(repository.health) if ready else {'available':False,'providers':[]}
    return {'providers':[{'provider':name,'available':ready and settings.configured(name) and (name!='github' or github is not None),
                         'syncAvailable':ready and settings.configured(name) and health['available'] and name in health['providers'] and (name!='github' or github is not None)} for name in PROVIDERS],
            'connections':operation(repository.list) if ready else []}


@router.post('/{provider}/connect')
def connect(provider:Provider,body:Empty,service:Annotated[SourceService,Depends(service)]):
    return operation(lambda:service.connect(provider))


@router.get('/{provider}/callback')
def callback(request:Request,provider:Provider,service:Annotated[SourceService,Depends(service)],
             state:Annotated[str,Query(min_length=20,max_length=128)],code:Annotated[str|None,Query(max_length=6000)]=None,error:Annotated[str|None,Query(max_length=300)]=None):
    # Provider failures never leak their query text and never become a success.
    success=False
    if not error and code:
        try: service.callback(provider,state,code); success=True
        except (CredentialUnavailable,SourceProviderError,SourceStateError): pass
    return RedirectResponse(service.settings.frontend_url.rstrip('/')+'/sources?source='+provider+'&connection='+('success' if success else 'failed'),status_code=303)


@router.get('/connection/{connection_id}/resources')
def resources(connection_id:UUID,service:Annotated[SourceService,Depends(service)],cursor:Annotated[str|None,Query(max_length=6000)]=None):
    return operation(lambda:service.resources(connection_id,cursor))


@router.post('/connection/{connection_id}/selection')
def selection(connection_id:UUID,body:Selection,service:Annotated[SourceService,Depends(service)]):
    return operation(lambda:service.select(connection_id,body.expectedRevision,body.resourceIds,body.shareWithWorkspace))


@router.post('/connection/{connection_id}/{action}')
def action(connection_id:UUID,action:Literal['sync','cancel','disconnect'],body:Empty,
           request:Request,repository:Annotated[SourceConnectionRepository,Depends(repository)],user:Annotated[AuthenticatedUser,Depends(session)]):
    if action!='disconnect':
        verified_user(request,user)
        settings,_=configuration(request)
        if not settings.enabled: raise HTTPException(503,{'code':'source_not_enabled'})
    return operation(lambda:repository.action('enqueue' if action=='sync' else action,connection_id))
