"""Authenticated collaborative projects; invitations never grant access by themselves."""
import secrets
from datetime import datetime
from hashlib import sha256
from typing import Annotated, Literal
from uuid import UUID
import psycopg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.api.auth import verified_user, auth_service, LoginRequest
from app.models.auth import AuthRepository
from app.services.auth_service import AuthenticatedUser, EmailDeliveryFailed
from app.services.team import TeamService

router = APIRouter(prefix='/team', tags=['team'])


def service(request: Request, user: AuthenticatedUser):
    if not request.app.state.settings.team_enabled:
        raise HTTPException(503, {'code': 'team_not_configured', 'message': 'Team is not available yet.'})
    db = request.app.state.database
    if db is None:
        raise HTTPException(503, {'code': 'team_unavailable', 'message': 'Team is temporarily unavailable.'})
    return TeamService(db, user.user_id)


def invoke(svc: TeamService, operation: str, *args):
    try:
        return svc.call(operation, *args)
    except psycopg.Error as error:
        statuses = {
            '42501': (403, 'team_permission', 'A verified account with the required project role is needed.'),
            'P0001': (403, 'team_subscription_required', 'An active Team subscription is required.'),
            'P0002': (404, 'team_not_found', 'This project, task or invitation is unavailable for your account.'),
            'P0003': (409, 'team_limit', 'A limit was reached, or this action cannot continue. Check the project limits and try again later.'),
            '40001': (409, 'team_conflict', 'Someone changed this task. Keep your draft and reload the latest version.'),
            '22023': (422, 'team_invalid', 'Check the task, invitation or member details.'),
            '23505': (409, 'team_conflict', 'This request conflicts with an existing record.'),
        }
        status, code, message = statuses.get(error.sqlstate, (503, 'team_unavailable', 'Team is temporarily unavailable. Please retry.'))
        raise HTTPException(status, {'code': code, 'message': message}) from None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ProjectCreate(StrictModel):
    id: UUID
    name: str = Field(min_length=1, max_length=100)
    @field_validator('name')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Name is required')
        return value.strip()


class InvitationCreate(StrictModel):
    email: str = Field(min_length=3, max_length=254)
    role: Literal['editor', 'viewer'] = 'editor'
    sharingAcknowledged: Literal[True]
    @field_validator('email')
    @classmethod
    def email_format(cls, value):
        return LoginRequest.email_format(value)


class InvitationAccept(StrictModel):
    token: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')
    accept: Literal[True]


class InvitationToken(StrictModel):
    token: str = Field(pattern=r'^[A-Za-z0-9_-]{43}$')


class MembershipChange(StrictModel):
    action: Literal['remove', 'leave', 'role', 'transfer']
    role: Literal['editor', 'viewer'] | None = None


class TaskWrite(StrictModel):
    id: UUID
    expectedVersion: int = Field(ge=0, le=2147483646)
    title: str | None = Field(default=None, min_length=1, max_length=180)
    description: str | None = Field(default=None, max_length=10000)
    status: Literal['todo', 'doing', 'done'] | None = None
    assigneeId: str | None = Field(default=None, max_length=200)
    remove: bool = False
    @model_validator(mode='after')
    def valid(self):
        supplied = self.model_fields_set
        if not self.remove and (not supplied.intersection({'title','description','status','assigneeId'})
           or any(getattr(self, key) is None for key in ('title','description','status') if key in supplied)):
            raise ValueError('Task fields are required')
        if self.expectedVersion == 0 and (not self.title or self.remove):
            raise ValueError('New tasks require a title')
        if self.description is not None and len(self.description.encode('utf-8'))>10000:
            raise ValueError('Description is too long')
        return self


@router.get('/projects')
def projects(request: Request, user: Annotated[AuthenticatedUser, Depends(verified_user)]):
    svc = service(request, user)
    return {'projects': invoke(svc, 'projects'), 'capability': invoke(svc, 'capability')}


@router.post('/projects', status_code=201)
def create_project(payload: ProjectCreate, request: Request, user: Annotated[AuthenticatedUser, Depends(verified_user)]):
    result = invoke(service(request, user), 'create', payload.id, payload.name)
    return {'workspaceId': str(result)}


@router.get('/projects/{workspace_id}/members')
def members(workspace_id: UUID, request: Request, user: Annotated[AuthenticatedUser, Depends(verified_user)]):
    return invoke(service(request, user), 'members', workspace_id)


@router.post('/projects/{workspace_id}/members/{member_id}')
def change_member(workspace_id: UUID, member_id: str, payload: MembershipChange, request: Request, user: Annotated[AuthenticatedUser, Depends(verified_user)]):
    invoke(service(request, user), 'membership', workspace_id, member_id, payload.action, payload.role)
    return {'ok': True}


@router.get('/projects/{workspace_id}/invitations')
def invitations(workspace_id: UUID, request: Request, user: Annotated[AuthenticatedUser, Depends(verified_user)]):
    return invoke(service(request, user), 'invitations', workspace_id)


@router.post('/projects/{workspace_id}/invitations', status_code=201)
def invite(workspace_id: UUID, payload: InvitationCreate, request: Request, user: Annotated[AuthenticatedUser, Depends(verified_user)]):
    svc = service(request, user)
    sender = request.app.state.email_sender
    origin = request.app.state.settings.app_public_url
    if sender is None or not origin:
        raise HTTPException(503, {'code':'team_email_unavailable','message':'Invitation email is not configured. No invitation was sent.'})
    token = secrets.token_urlsafe(32)
    result = invoke(svc, 'invite', workspace_id, payload.email, payload.role, sha256(token.encode()).hexdigest())
    project = next(p for p in invoke(svc, 'projects') if p['id']==str(workspace_id))
    # Fragment tokens do not enter server query logs, referrers or registration URLs.
    link = origin.rstrip('/')+'/join#'+token
    subject = 'Your Flare project invitation'
    text = (f'{user.name} invited you to the project "{project["name"]}" in Flare.\n'
        f'Role: {payload.role}. Members can see the saved materials in this project.\n\n'
        f'Join with your invited email address: {link}\n\nThis invitation expires in seven days.\n')
    try:
        sender.send(to=payload.email, subject=subject, text=text)
    except Exception:
        # Delivery may have an unknown SMTP result. Retire that token and never
        # claim success or send automatically again. A manual retry is bounded.
        invoke(svc, 'cancel', workspace_id, UUID(result['id']))
        raise HTTPException(503, {'code':'team_email_failed','message':'Invitation delivery could not be confirmed. The link was canceled; retry later.'}) from None
    return {**result, 'status':'pending'}


@router.delete('/projects/{workspace_id}/invitations/{invitation_id}', status_code=204)
def cancel_invite(workspace_id: UUID, invitation_id: UUID, request: Request, user: Annotated[AuthenticatedUser, Depends(verified_user)]):
    invoke(service(request, user), 'cancel', workspace_id, invitation_id)
    return Response(status_code=204)


@router.post('/invitations/accept')
def accept_invite(payload: InvitationAccept, request: Request, user: Annotated[AuthenticatedUser, Depends(verified_user)]):
    return invoke(service(request, user), 'accept', sha256(payload.token.encode()).hexdigest())


@router.post('/invitations/preview')
def preview_invite(payload: InvitationToken, request: Request, user: Annotated[AuthenticatedUser, Depends(verified_user)]):
    return invoke(service(request, user), 'preview', sha256(payload.token.encode()).hexdigest())


@router.post('/verify-email')
def verify_team_email(request: Request, user: Annotated[AuthenticatedUser, Depends(verified_user)]):
    svc = service(request, user)
    if not invoke(svc, 'capability')['requiresVerification']:
        return {'ok': True, 'alreadyVerified': True}
    auth = auth_service(request)
    token = secrets.token_urlsafe(32)
    with svc.database.connection() as connection, connection.transaction():
        repository = AuthRepository(connection)
        account = repository.find_user(user.email, lock=True)
        if not account or account['disabled']:
            raise HTTPException(403, 'Account unavailable')
        last = repository.last_verification_created_at(user.user_id)
        now = connection.execute('SELECT now() AS now').fetchone()['now']
        if last and (now-last).total_seconds()<60:
            raise HTTPException(429, {'code':'team_verification_wait','message':'Wait a minute before requesting another verification email.'})
        repository.insert_email_verification(sha256(token.encode()).hexdigest(),user.user_id,user.email,auth.email_verification_ttl)
    try:
        auth._deliver_verification(user.email, token, remove_on_failure=True)
    except EmailDeliveryFailed:
        raise HTTPException(503, {'code':'team_email_failed','message':'Verification email could not be sent. Please retry.'}) from None
    return {'ok':True}


@router.get('/projects/{workspace_id}/tasks')
def tasks(workspace_id: UUID, request: Request, user: Annotated[AuthenticatedUser, Depends(verified_user)], beforeAt: datetime | None = None, beforeId: UUID | None = None):
    if (beforeAt is None)!=(beforeId is None) or beforeAt is not None and beforeAt.tzinfo is None:
        raise HTTPException(422,'Provide a complete, timezone-aware cursor')
    rows = invoke(service(request, user), 'tasks', workspace_id, beforeAt, beforeId)
    visible = rows[:100]
    next_cursor = {'beforeAt':visible[-1]['updatedAt'],'beforeId':visible[-1]['id']} if len(rows)>100 else None
    return {'tasks':visible,'nextCursor':next_cursor}


@router.post('/projects/{workspace_id}/tasks')
def write_task(workspace_id: UUID, payload: TaskWrite, request: Request, user: Annotated[AuthenticatedUser, Depends(verified_user)]):
    from psycopg.types.json import Jsonb
    values = payload.model_dump(include={'title','description','status','assigneeId'},exclude_unset=True)
    return invoke(service(request, user),'task',workspace_id,payload.id,payload.expectedVersion,Jsonb(values),payload.remove)


@router.get('/projects/{workspace_id}/tasks/{task_id}/history')
def history(workspace_id: UUID, task_id: UUID, request: Request, user: Annotated[AuthenticatedUser, Depends(verified_user)]):
    return invoke(service(request, user), 'history', workspace_id, task_id)


@router.get('/projects/{workspace_id}/tasks/{task_id}')
def get_task(workspace_id: UUID, task_id: UUID, request: Request, user: Annotated[AuthenticatedUser, Depends(verified_user)]):
    return invoke(service(request, user), 'task_get', workspace_id, task_id)
