"""Flare API foundation. Business routes will follow authentication."""

import os

import psycopg
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException

load_dotenv()
app = FastAPI(title="Flare", version="0.1.0")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready", tags=["health"])
def ready() -> dict[str, str]:
    """Check connectivity, migration and that the API cannot bypass RLS."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        raise HTTPException(status_code=503, detail="Database is not configured")
    try:
        with psycopg.connect(database_url, connect_timeout=3) as connection:
            safe_role = connection.execute(
                "SELECT NOT rolsuper AND NOT rolbypassrls "
                "FROM pg_roles WHERE rolname = current_user"
            ).fetchone()
            if safe_role != (True,):
                raise HTTPException(status_code=503, detail="Database role is unsafe")
            # No workspace context: RLS must return no customer data.
            connection.execute("SELECT id FROM public.workspaces LIMIT 0")
            extension = connection.execute(
                "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
            ).fetchone()
            if extension is None:
                raise HTTPException(status_code=503, detail="Database is not initialized")
    except psycopg.Error:
        # Avoid exposing the database URL, credentials or SQL errors in HTTP responses.
        raise HTTPException(status_code=503, detail="Database is unavailable") from None
    return {"status": "ready"}

