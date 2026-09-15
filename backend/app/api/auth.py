"""Cookie authentication endpoints and server-owned identity dependencies."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.database import MembershipRequiredError
from app.services.auth_service import (
    AuthService,
    AuthenticatedUser,
    EmailDeliveryFailed,
    EmailNotVerified,
    InvalidCredentials,
    RegistrationUnavailable,
    VerificationInvalid,
)

router = APIRouter(prefix="/auth", tags=["authentication"])


def auth_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code, {"code": code, "message": message})


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

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Name is required")
        return value.strip()


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
                user_id, workspace_id, "", name, membership["role"], name, True
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
    response.headers["Cache-Control"] = "no-store"


@router.post("/register", status_code=201)
def register(payload: RegisterRequest, request: Request, response: Response):
    try:
        token = auth_service(request).register(
            payload.email, payload.password, payload.name
        )
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
        },
        "workspace": {
            "id": str(user.workspace_id),
            "name": user.workspace_name,
            "role": user.role,
        },
    }


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
