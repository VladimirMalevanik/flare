"""Initial knowledge schema with tenant isolation and source versions."""
import os
from pathlib import Path

from alembic import op
from sqlalchemy import text

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _is_yandex_managed_postgres() -> bool:
    return os.getenv("FLARE_DATABASE_PROVIDER", "self-managed") == "yandex"


def _validate_yandex_prerequisites() -> None:
    """Fail before DDL unless Yandex-side users and pgvector are ready."""
    row = op.get_bind().execute(text("""
        SELECT
            current_user,
            pg_get_userbyid(d.datdba) AS database_owner,
            r.rolsuper,
            r.rolbypassrls,
            r.rolcreaterole,
            r.rolcreatedb,
            NOT EXISTS (
                SELECT 1 FROM pg_auth_members owner_memberships
                WHERE owner_memberships.member = r.oid
            ) AS safe_owner,
            EXISTS (
                SELECT 1 FROM pg_roles app
                WHERE app.rolname = 'flare_app'
                  AND app.rolcanlogin
                  AND NOT app.rolsuper
                  AND NOT app.rolbypassrls
                  AND NOT app.rolcreaterole
                  AND NOT app.rolcreatedb
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_auth_members memberships
                      WHERE memberships.member = app.oid
                  )
            ) AS safe_app,
            EXISTS (
                SELECT 1 FROM pg_roles worker
                WHERE worker.rolname = 'flare_worker'
                  AND worker.rolcanlogin
                  AND NOT worker.rolsuper
                  AND NOT worker.rolbypassrls
                  AND NOT worker.rolcreaterole
                  AND NOT worker.rolcreatedb
                  AND NOT EXISTS (
                      SELECT 1 FROM pg_auth_members memberships
                      WHERE memberships.member = worker.oid
                  )
            ) AS safe_worker,
            EXISTS (
                SELECT 1 FROM pg_extension
                WHERE extname IN ('vector', 'pgvector')
            ) AND to_regtype('vector') IS NOT NULL AS vector_enabled
        FROM pg_database d
        JOIN pg_roles r ON r.rolname = current_user
        WHERE d.datname = current_database()
    """)).one()
    if tuple(row) != (
        "flare_owner",
        "flare_owner",
        False,
        False,
        False,
        False,
        True,
        True,
        True,
        True,
    ):
        raise RuntimeError(
            "Yandex migrations require a non-privileged, membership-free "
            "flare_owner that owns "
            "the database, safe flare_app/flare_worker users, and pgvector "
            "enabled through Yandex Cloud"
        )


def upgrade():
    # Treat this SQL file as immutable after release; add a new migration for changes.
    schema = Path(__file__).resolve().parents[2] / "db" / "schema.sql"
    schema_sql = schema.read_text(encoding="utf-8")
    if _is_yandex_managed_postgres():
        _validate_yandex_prerequisites()
        extension_ddl = "CREATE EXTENSION IF NOT EXISTS vector;"
        if schema_sql.count(extension_ddl) != 1:
            raise RuntimeError("Expected exactly one pgvector extension statement")
        # Managed PostgreSQL installs extensions through its control plane.
        schema_sql = schema_sql.replace(extension_ddl, "")
    op.execute(schema_sql)
    op.execute("GRANT USAGE ON SCHEMA public TO flare_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON "
        "workspaces, workspace_members, documents, document_versions, "
        "chunks, insights, insight_sources TO flare_app"
    )


def downgrade():
    raise RuntimeError("This initial migration contains customer data; restore a backup instead.")
