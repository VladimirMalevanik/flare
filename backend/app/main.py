"""Flare HTTP application."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import Settings, settings
from app.models.database import Database, WorkspaceIdentity


def create_app(
    application_settings: Settings | None = None,
    *,
    database: Database | None = None,
) -> FastAPI:
    configured = application_settings or settings

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
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
    application.add_middleware(
        CORSMiddleware,
        allow_origins=configured.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    application.include_router(router)
    return application


app = create_app()
