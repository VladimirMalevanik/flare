"""Cookie authentication endpoints and server-owned identity dependencies."""

from typing import Annotated, Literal
from dataclasses import replace
from uuid import UUID
from hashlib import sha256
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.responses import JSONResponse
from psycopg.errors import LockNotAvailable, QueryCanceled, DeadlockDetected, SerializationFailure
from psycopg_pool import PoolTimeout

from app.api.acquisition import COOKIE, clear_acquisition
from app.models.auth import AuthRepository
from app.models.database import MembershipRequiredError
from app.services.auth_service import (
    AuthService,
    AuthenticatedUser,
    EmailDeliveryFailed,
    EmailNotVerified,
    InvalidCredentials,
    RegistrationUnavailable,
    VerificationInvalid,
    PasswordResetInvalid,
    PasswordResetBusy,
    AuthenticationBusy,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def auth_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code, {"code": code, "message": message})


def busy_auth_error(code: str = "auth_busy") -> HTTPException:
    return HTTPException(429, {"code": code, "message": "Please try again shortly."}, headers={"Retry-After": "2"})


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def email_format(cls, value: str) -> str:
        normalized = value.strip().lower()
        local, separator, domain = normalized.partition("@")
        if (
            not separator
            or not local
            or "." not in domain
            or "@" in domain
            or any(character.isspace() for character in normalized)
        ):
            raise ValueError("Enter a valid email address")
        return normalized


class RegisterRequest(LoginRequest):
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    termsAccepted: Literal[True]
    privacyAccepted: Literal[True]
    acquisitionOptIn: bool = False

    @field_validator("acquisitionOptIn", mode="before")
    @classmethod
    def explicit_acquisition_opt_in(cls, value):
        # An optional measurement assertion must never block registration or
        # treat strings/numbers as consent. Only JSON true is eligible.
        return value is True

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name is required")
        return value.strip()


class LegalAcceptanceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    termsAccepted: Literal[True]
    privacyAccepted: Literal[True]


class VerifyEmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(max_length=256)


class ResendVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)

    @field_validator("email")
    @classmethod
    def email_format(cls, value: str) -> str:
        return LoginRequest.email_format(value)


class ResetPasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=43, max_length=43)
    password: str = Field(min_length=8, max_length=128)


def auth_service(request: Request) -> AuthService:
    database = request.app.state.database
    if database is None:
        raise HTTPException(503, "Database is unavailable")
    settings = request.app.state.settings
    return AuthService(
        database,
        lifetime=settings.session_lifetime_seconds,
        idle_seconds=settings.session_idle_seconds,
        email_verification_required=settings.email_verification_required,
        email_verification_ttl=settings.email_verification_ttl_seconds,
        email_verification_resend=settings.email_verification_resend_seconds,
        email_sender=request.app.state.email_sender,
        app_public_url=settings.app_public_url or "",
    )


def current_user(request: Request) -> AuthenticatedUser:
    settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie_name)
    # A presented but invalid credential never falls back to development identity.
    if request.headers.get("authorization") or (
        token is None
        and any(
            name in request.cookies
            for name in ("flare_session", "__Host-flare_session")
        )
    ):
        raise HTTPException(401, "Use the session cookie to authenticate")
    if token is None and not settings.dev_mode:
        raise HTTPException(401, "Authentication required")
    service = auth_service(request)
    if token is None and settings.dev_mode:
        try:
            workspace_id, user_id, name = settings.require_dev_identity()
        except RuntimeError:
            raise HTTPException(401, "Authentication required") from None
        from app.models.database import WorkspaceIdentity

        try:
            with service.database.workspace_transaction(
                WorkspaceIdentity(workspace_id, user_id)
            ) as connection:
                membership = connection.execute(
                    "SELECT role FROM public.workspace_members WHERE user_id=%s",
                    (user_id,),
                ).fetchone()
            return AuthenticatedUser(
                user_id, workspace_id, "", name, membership["role"], name, True, True
            )
        except MembershipRequiredError:
            raise HTTPException(403, "Workspace membership is required") from None
    try:
        return service.current(token)
    except InvalidCredentials:
        raise HTTPException(401, "Authentication required") from None
    except MembershipRequiredError:
        raise HTTPException(403, "Workspace membership is required") from None


def verified_user(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
) -> AuthenticatedUser:
    if request.app.state.settings.email_verification_required and not user.email_verified:
        raise auth_error(
            403,
            "email_verification_required",
            "Verify your email to continue.",
        )
    if not user.legal_accepted:
        raise auth_error(
            403,
            "legal_acceptance_required",
            "Review and accept the current Terms of Service and Privacy Policy to continue.",
        )
    selected = request.query_params.getlist("workspace")
    if not selected and request.url.path.endswith('/callback') and getattr(request.app.state.settings,'team_enabled',False):
        provider = 'github-app' if request.url.path == '/integrations/github/callback' else (
            request.url.path.split('/')[-2] if request.url.path.startswith('/integrations/sources/') else None)
        states = request.query_params.getlist('state')
        if provider and len(states)==1 and len(states[0])<=128:
            from app.services.team import TeamService
            from app.api.team import invoke
            target = invoke(TeamService(request.app.state.database,user.user_id),'oauth',sha256(states[0].encode()).hexdigest(),provider)
            if target is not None:
                selected = [str(target)]
                request.state.team_callback_workspace = str(target)
    if selected and not request.url.path.startswith(("/auth", "/team", "/ops", "/acquisition")):
        if len(selected) != 1:
            raise auth_error(400, "workspace_invalid", "Choose one project.")
        try:
            target = str(UUID(selected[0]))
        except ValueError:
            raise auth_error(400, "workspace_invalid", "Choose a valid project.") from None
        if target != str(user.workspace_id):
            if not request.app.state.settings.team_enabled:
                raise auth_error(403, "workspace_unavailable", "Project access is unavailable.")
            from app.services.team import TeamService
            from app.api.team import invoke
            projects = invoke(TeamService(request.app.state.database, user.user_id), "projects")
            project = next((p for p in projects if p["id"] == target), None)
            if project is None:
                raise auth_error(404, "workspace_unavailable", "Project unavailable for your account.")
            stops_job = request.url.path.endswith('/cancel') and request.url.path.startswith(('/imports/packages/','/integrations/sources/'))
            if not project["writable"] and request.method not in {"GET", "HEAD", "OPTIONS", "DELETE"} and not stops_job:
                raise auth_error(403, "team_subscription_required", "This project is read-only until its Team subscription is renewed.")
            user = replace(user, workspace_id=UUID(target), workspace_name=project["name"], role=project["role"])
    return user


def set_session(request: Request, response: Response, token: str) -> None:
    settings = request.app.state.settings
    # Rotate the browser's previous session after successful authentication.
    auth_service(request).logout(request.cookies.get(settings.session_cookie_name))
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
        path="/",
        max_age=settings.session_lifetime_seconds,
    )
    clear_acquisition(request, response)
    response.headers["Cache-Control"] = "no-store"


@router.post("/register", status_code=201)
def register(payload: RegisterRequest, request: Request, response: Response):
    try:
        token = auth_service(request).register(
            payload.email, payload.password, payload.name,
            acquisition_reference=(request.cookies.get(COOKIE) if payload.acquisitionOptIn is True
                and not request.cookies.get(request.app.state.settings.session_cookie_name) else None),
        )
    except AuthenticationBusy:
        raise busy_auth_error() from None
    except RegistrationUnavailable:
        raise auth_error(
            409,
            "registration_unavailable",
            "Registration could not be completed. Try signing in.",
        ) from None
    except EmailDeliveryFailed:
        raise auth_error(
            503,
            "email_delivery_failed",
            "Your account was created, but the verification email could not be sent. Request a new email to continue.",
        ) from None
    set_session(request, response, token)
    return {
        "ok": True,
        "emailVerificationRequired": request.app.state.settings.email_verification_required,
    }


@router.post("/login")
def login(payload: LoginRequest, request: Request, response: Response):
    try:
        token = auth_service(request).login(payload.email, payload.password)
    except AuthenticationBusy:
        raise busy_auth_error() from None
    except EmailNotVerified:
        raise auth_error(
            403,
            "email_verification_required",
            "Verify your email to continue.",
        ) from None
    except (InvalidCredentials, MembershipRequiredError):
        raise auth_error(
            401,
            "invalid_credentials",
            "Email or password is incorrect.",
        ) from None
    set_session(request, response, token)
    return {"ok": True}


@router.get("/me")
def me(
    user: Annotated[AuthenticatedUser, Depends(current_user)], response: Response
):
    response.headers["Cache-Control"] = "no-store"
    return {
        "user": {
            "id": user.user_id,
            "email": user.email,
            "name": user.name,
            "emailVerified": user.email_verified,
            "legalAccepted": user.legal_accepted,
        },
        "workspace": {
            "id": str(user.workspace_id),
            "name": user.workspace_name,
            "role": user.role,
        },
    }


@router.post("/accept-legal")
def accept_legal(
    payload: LegalAcceptanceRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_user)],
):
    database = request.app.state.database
    if database is None:
        raise HTTPException(503, "Database is unavailable")
    with database.connection() as connection, connection.transaction():
        AuthRepository(connection).accept_current_legal(user.user_id)
    return {"ok": True}


@router.post("/logout", status_code=204)
def logout(request: Request):
    settings = request.app.state.settings
    auth_service(request).logout(request.cookies.get(settings.session_cookie_name))
    response = Response(status_code=204, headers={"Cache-Control": "no-store"})
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.secure_cookies,
        httponly=True,
        samesite="lax",
    )
    clear_acquisition(request, response)
    return response


@router.post("/verify-email")
def verify_email(payload: VerifyEmailRequest, request: Request):
    try:
        auth_service(request).verify_email(payload.token)
    except VerificationInvalid:
        raise auth_error(
            400,
            "email_verification_invalid",
            "This verification link is invalid or has expired.",
        ) from None
    return {"ok": True}


@router.post("/resend-verification", status_code=202)
def resend_verification(payload: ResendVerificationRequest, request: Request):
    try:
        auth_service(request).resend_verification(payload.email)
    except EmailDeliveryFailed:
        # Keep the response enumeration-safe. Failed tokens are removed so a
        # later request can retry immediately.
        pass
    return {
        "ok": True,
        "message": "If verification is available for that address, a new email will arrive shortly.",
    }


@router.post("/forgot-password", status_code=202)
def forgot_password(payload: ResendVerificationRequest, request: Request):
    service = auth_service(request)
    if service.email_sender is None or not service.app_public_url:
        raise auth_error(503, "password_recovery_unavailable", "Password recovery is temporarily unavailable. Try again later.")
    # Enqueue before any account-dependent work, including DB lookup and SMTP.
    if not request.app.state.recovery_dispatcher.submit(service.request_password_reset, payload.email):
        raise busy_auth_error("password_recovery_busy")
    return {"ok": True, "message": "If password recovery is available for that address, an email will arrive shortly."}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, request: Request):
    service = auth_service(request)
    try:
        email = service.reset_password(payload.token, payload.password)
    except PasswordResetInvalid:
        raise auth_error(400, "password_reset_invalid", "This reset link is invalid or has expired. Request a new link.") from None
    except (PasswordResetBusy, AuthenticationBusy, LockNotAvailable, QueryCanceled,
            DeadlockDetected, SerializationFailure, PoolTimeout):
        raise busy_auth_error("password_recovery_busy") from None
    # Notification failure cannot undo a committed password/session update.
    if not request.app.state.recovery_dispatcher.submit(service.notify_password_changed, email):
        logging.getLogger(__name__).warning("password_change_notice_not_queued")
    return {"ok": True}


class AuthBodyLimit:
    """Bound streamed auth bodies before JSON/password validation."""
    limit = 8192
    timeout = 10
    paths = frozenset({"/auth/forgot-password", "/auth/reset-password", "/auth/login", "/auth/register",
        "/auth/verify-email", "/auth/resend-verification", "/auth/accept-legal"})

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST" or scope.get("path") not in self.paths:
            return await self.app(scope, receive, send)
        lengths = [v for k, v in scope.get("headers", []) if k.lower() == b"content-length"]
        if lengths:
            try:
                if len(lengths) != 1 or int(lengths[0]) < 0:
                    raise ValueError
                if int(lengths[0]) > self.limit:
                    return await JSONResponse({"detail": "Request body is too large"}, status_code=413)(scope, receive, send)
            except ValueError:
                return await JSONResponse({"detail": "Invalid request length"}, status_code=400)(scope, receive, send)
        body = bytearray()

        async def read():
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return False
                part = message.get("body", b"")
                if len(body) + len(part) > self.limit:
                    raise OverflowError
                body.extend(part)
                if not message.get("more_body", False):
                    return True

        try:
            if not await asyncio.wait_for(read(), self.timeout):
                return
        except OverflowError:
            return await JSONResponse({"detail": "Request body is too large"}, status_code=413)(scope, receive, send)
        except TimeoutError:
            return await JSONResponse({"detail": "Request body timed out"}, status_code=408)(scope, receive, send)
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
