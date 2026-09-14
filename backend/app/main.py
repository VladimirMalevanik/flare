"""Flare HTTP application."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.api.analytics import router as analytics_router
from app.api.auth import router as auth_router
from app.api.flares import router as flares_router
from app.api.analysis import router as analysis_router
from app.api.analysis_schedule import router as analysis_schedule_router
from app.api.github import router as github_router
from app.api.imports import router as imports_router
from app.api.export import router as export_router
from app.api import ops
from app.config import Settings, settings
from app.models.database import Database, WorkspaceIdentity
from app.services.email import EmailSender
from app.services.smtp_email import LoggingEmailSender, SmtpEmailSender


# Uvicorn configures this logger at INFO even when its raw access logger is off.
request_logger = logging.getLogger("uvicorn.error")
# Deployment commands also pass --no-access-log. Keep this defense here so an
# accidental command override cannot put OAuth/query values back into logs.
logging.getLogger("uvicorn.access").disabled = True
_LOGGED_HTTP_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"})

def create_app(
    application_settings: Settings | None = None,
    *,
    database: Database | None = None,
    email_sender: EmailSender | None = None,
) -> FastAPI:
    configured = application_settings or settings

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        logging.getLogger("uvicorn.access").disabled = True
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
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Content-Type", "Idempotency-Key"],
    )
    @application.middleware("http")
    async def origin_guard(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("origin") not in configured.cors_origins:
                return JSONResponse({"detail": "Request origin is not allowed"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith((
            "/auth", "/items", "/imports", "/flares", "/analyze", "/analysis-runs",
            "/integrations", "/ops", "/analytics",
            "/analysis-schedule", "/analysis/daily-status",
            "/export",
        )):
            response.headers["Cache-Control"] = "no-store"
        return response

    @application.middleware("http")
    async def safe_request_log(request: Request, call_next):
        """Log request outcomes without URLs, query strings, bodies or errors."""
        started = perf_counter()
        response_status = 500
        try:
            response = await call_next(request)
            response_status = response.status_code
            return response
        finally:
            route = request.scope.get("route")
            route_template = getattr(route, "path", None)
            if not isinstance(route_template, str) or not route_template.startswith("/"):
                route_template = "unmatched"
            method = request.method if request.method in _LOGGED_HTTP_METHODS else "OTHER"
            request_logger.info(
                "http_request method=%s route=%s status=%s duration_ms=%.1f",
                method,
                route_template,
                response_status,
                max(0.0, (perf_counter() - started) * 1_000),
            )

    @application.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        # Pydantic's default errors include input values (including passwords).
        return JSONResponse({"detail": [
            {"loc": e["loc"], "msg": e["msg"], "type": e["type"]}
            for e in error.errors()
        ]}, status_code=422)

    application.include_router(auth_router)
    application.include_router(imports_router)
    application.include_router(flares_router)
    application.include_router(analysis_router)
    application.include_router(analysis_schedule_router)
    application.include_router(github_router)
    application.include_router(export_router)
    application.include_router(ops.router)
    application.include_router(analytics_router)
    application.include_router(router)
    return application


app = create_app()
