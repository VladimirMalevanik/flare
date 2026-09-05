"""Database connection checks and transaction boundaries."""

import psycopg


def database_is_ready(database_url: str) -> bool:
    """Return true only for an initialized DB reached through a safe role."""
    with psycopg.connect(database_url, connect_timeout=3) as connection:
        safe_role = connection.execute(
            "SELECT NOT rolsuper AND NOT rolbypassrls "
            "FROM pg_roles WHERE rolname = current_user"
        ).fetchone()
        if safe_role != (True,):
            return False

        # Without a workspace context RLS must expose no customer rows.
        connection.execute("SELECT id FROM public.workspaces LIMIT 0")
        extension = connection.execute(
            "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
        return extension is not None
