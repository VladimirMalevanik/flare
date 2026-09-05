"""Public HTTP routes."""

import psycopg
from fastapi import APIRouter, HTTPException

from app.api.schemas import HealthResponse
from app.config import settings
from app.models.database import database_is_ready

router = APIRouter()


@router.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    return HealthResponse(status="ok")


@router.get("/ready", response_model=HealthResponse, tags=["health"])
def ready() -> HealthResponse:
    """Check the migration and the restricted runtime database role."""
    if not settings.database_url:
        raise HTTPException(status_code=503, detail="Database is not configured")
    try:
        if not database_is_ready(settings.database_url):
            raise HTTPException(status_code=503, detail="Database is not initialized")
    except psycopg.Error:
        # Never expose connection strings, credentials or SQL details over HTTP.
        raise HTTPException(status_code=503, detail="Database is unavailable") from None
    return HealthResponse(status="ready")
