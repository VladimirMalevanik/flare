"""Run migration 0018 with the schema privileges used by production."""

import os
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from app.models.database import CURRENT_SCHEMA_REVISION
from test_analysis_jobs import admin_url
from test_yandex_migrations import load_migration


pytestmark = pytest.mark.integration


class _DatabaseOp:
    def __init__(self, connection):
        self.connection = connection

    def execute(self, statement):
        self.connection.execute(statement)


def test_0018_upgrade_does_not_require_executor_create_on_public(admin_url, monkeypatch):
    if os.getenv("FLARE_DATABASE_PROVIDER", "self-managed") != "self-managed":
        pytest.skip("This regression covers the self-managed executor role")
    migration = load_migration("0018_rotate_analysis_context.py")
    monkeypatch.setenv("FLARE_DATABASE_PROVIDER", "self-managed")

    with psycopg.connect(admin_url) as connection:
        try:
            assert connection.execute(
                "SELECT version_num FROM public.alembic_version"
            ).fetchone() == (CURRENT_SCHEMA_REVISION,)

            admin_role, is_superuser = connection.execute(
                "SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user"
            ).fetchone()
            migration_role = admin_role
            if is_superuser:
                # The disposable fixture often connects as postgres. Exercise
                # PostgreSQL's real ownership checks with a non-superuser that
                # inherits the fixture admin's object rights.
                migration_role = f"flare_migration_0018_{uuid4().hex[:12]}"
                role = sql.Identifier(migration_role)
                connection.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER INHERIT").format(role))
                connection.execute(
                    sql.SQL("GRANT {} TO {}").format(sql.Identifier(admin_role), role)
                )
                connection.execute(sql.SQL("GRANT flare_job_executor TO {}").format(role))
                connection.execute(sql.SQL("GRANT CREATE ON SCHEMA public TO {}").format(role))
                connection.execute(sql.SQL("SET ROLE {}").format(role))

            assert connection.execute(
                "SELECT has_schema_privilege(current_user, 'public', 'CREATE'), "
                "has_schema_privilege('flare_job_executor', 'public', 'CREATE'), "
                "(SELECT rolsuper FROM pg_roles WHERE rolname = current_user)"
            ).fetchone() == (True, False, False)
            assert connection.execute(
                """SELECT EXISTS (
                    SELECT 1 FROM pg_auth_members m
                    JOIN pg_roles r ON r.oid = m.member
                    WHERE m.roleid = 'flare_job_executor'::regrole
                      AND r.rolname = current_user
                )"""
            ).fetchone() == (True,)

            monkeypatch.setattr(migration, "op", _DatabaseOp(connection))
            migration.downgrade()
            migration.upgrade()

            assert connection.execute(
                """SELECT pg_get_userbyid(proowner), prosecdef
                   FROM pg_proc
                  WHERE oid = 'public.record_analysis_chunk_selection()'::regprocedure"""
            ).fetchone() == (migration_role, False)
            assert connection.execute(
                "SELECT has_function_privilege('flare_worker', "
                "'public.record_analysis_chunk_selection()', 'EXECUTE')"
            ).fetchone() == (False,)
        finally:
            # Restore the migrated fixture, grants, and temporary role together.
            connection.rollback()
