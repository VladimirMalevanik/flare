"""Flare HTTP application."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.auth import router as auth_router
from app.api.flares import router as flares_router
from app.api.analysis import router as analysis_router
from app.config import Settings, settings
from app.models.database import Database, WorkspaceIdentity
from app.services.email import EmailSender
from app.services.smtp_email import LoggingEmailSender, SmtpEmailSender

def create_app(
    application_settings: Settings | None = None,
    *,
    database: Database | None = None,
    email_sender: EmailSender | None = None,
) -> FastAPI:
    configured = application_settings or settings

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configured.validate()
        if email_sender is not None:
            application.state.email_sender = email_sender
        elif not configured.email_verification_required:
            application.state.email_sender = None
        elif configured.smtp_url:
            application.state.email_sender = SmtpEmailSender(
                configured.smtp_url, configured.email_from or ""
            )
        else:
            # validate() limits this sender to explicit localhost development/test.
            application.state.email_sender = LoggingEmailSender()
        managed_database = database
        owns_database = managed_database is None
        database_opened = False
        if managed_database is None and configured.database_url:
            managed_database = Database(configured.database_url)
        application.state.database = managed_database
        try:
            if managed_database is not None:
                managed_database.open()
                database_opened = True
                if configured.dev_mode:
                    workspace_id, user_id, workspace_name = configured.require_dev_identity()
                    managed_database.bootstrap_development_workspace(
                        WorkspaceIdentity(workspace_id, user_id),
                        workspace_name,
                    )
            yield
        finally:
            if owns_database and managed_database is not None and database_opened:
                managed_database.close()

    application = FastAPI(title="Flare API", version="0.2.0", lifespan=lifespan)
    application.state.settings = configured
    application.state.database = database
    application.state.email_sender = email_sender
    application.add_middleware(
        CORSMiddleware,
        allow_origins=configured.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )
    @application.middleware("http")
    async def origin_guard(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("origin") not in configured.cors_origins:
                return JSONResponse({"detail": "Request origin is not allowed"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith(("/auth", "/items", "/flares", "/analyze", "/analysis-runs")):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # Pydantic's default errors include input values (including passwords).
        return JSONResponse({"detail": [
            {"loc": e["loc"], "msg": e["msg"], "type": e["type"]}
            for e in error.errors()
        ]}, status_code=422)

    application.include_router(auth_router)
    application.include_router(flares_router)
    application.include_router(analysis_router)
    application.include_router(router)
    return application


app = create_app()
