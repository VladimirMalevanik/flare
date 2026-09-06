"""Database connection lifecycle and tenant-safe transaction boundaries."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


CURRENT_SCHEMA_REVISION = "0003"
TENANT_TABLES = (
    "workspaces",
    "workspace_members",
    "documents",
    "document_versions",
    "chunks",
    "insights",
    "insight_sources",
)


class MembershipRequiredError(Exception):
    """The configured identity is not a member of the selected workspace."""


class WritePermissionRequiredError(Exception):
    """The configured member is not allowed to mutate workspace data."""


@dataclass(frozen=True)
class WorkspaceIdentity:
    workspace_id: UUID
    user_id: str


def database_is_ready(database_url: str) -> bool:
    """Return true only for an initialized DB reached through a safe role."""
    with psycopg.connect(database_url, connect_timeout=3) as connection:
        return _connection_is_ready(connection)


def _connection_is_ready(connection: Connection) -> bool:
    """Validate the runtime role, schema head and fail-closed tenant access."""
    safe_role = connection.execute(
        "SELECT NOT rolsuper AND NOT rolbypassrls "
        "FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    if safe_role != (True,):
        return False

    # Make the check independent from PGOPTIONS or a reused caller connection.
    connection.execute("SELECT set_config('app.workspace_id', '', true)")

    revision = connection.execute(
        "SELECT version_num FROM public.alembic_version"
    ).fetchone()
    if revision != (CURRENT_SCHEMA_REVISION,):
        return False

    protected_tables = connection.execute(
        """SELECT count(*)
           FROM pg_class c
           JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public'
             AND c.relname = ANY(%s)
             AND c.relrowsecurity
             AND c.relforcerowsecurity""",
        (list(TENANT_TABLES),),
    ).fetchone()
    if protected_tables != (len(TENANT_TABLES),):
        return False

    # Execute real reads without tenant context. LIMIT 0 would only validate the
    # SQL shape and would not prove that RLS hides existing customer rows.
    customer_rows_are_hidden = connection.execute(
        """SELECT NOT EXISTS (
               SELECT 1 FROM public.workspaces
               UNION ALL SELECT 1 FROM public.workspace_members
               UNION ALL SELECT 1 FROM public.documents
               UNION ALL SELECT 1 FROM public.document_versions
               UNION ALL SELECT 1 FROM public.chunks
               UNION ALL SELECT 1 FROM public.insights
               UNION ALL SELECT 1 FROM public.insight_sources
           )"""
    ).fetchone()
    if customer_rows_are_hidden != (True,):
        return False

    extension = connection.execute(
        "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
    ).fetchone()
    return extension is not None


class Database:
    """Own the process connection pool and enforce RLS context per transaction."""

    def __init__(self, database_url: str, *, min_size: int = 1, max_size: int = 10):
        self._pool = ConnectionPool(
            conninfo=database_url,
            min_size=min_size,
            max_size=max_size,
            open=False,
            kwargs={"connect_timeout": 3, "row_factory": dict_row},
            name="flare-api",
        )

    def open(self) -> None:
        try:
            self._pool.open(wait=True, timeout=10)
            with self._pool.connection() as connection:
                safe_role = connection.execute(
                    """SELECT NOT rolsuper AND NOT rolbypassrls AS safe
                       FROM pg_roles WHERE rolname = current_user"""
                ).fetchone()
                if safe_role is None or safe_role["safe"] is not True:
                    raise RuntimeError(
                        "Application database connections must use a non-superuser, "
                        "non-BYPASSRLS role"
                    )
        except Exception:
            self._pool.close()
            raise

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        """Yield a pooled connection without selecting customer context."""
        with self._pool.connection() as connection:
            yield connection

    @contextmanager
    def workspace_transaction(
        self,
        identity: WorkspaceIdentity,
        *,
        write: bool = False,
    ) -> Iterator[Connection]:
        """Select one workspace locally, verify membership, then yield a transaction."""
        with self._pool.connection() as connection:
            with connection.transaction():
                connection.execute(
                    "SELECT set_config('app.workspace_id', %s, true)",
                    (str(identity.workspace_id),),
                )
                membership = connection.execute(
                    """SELECT role FROM public.workspace_members
                       WHERE workspace_id = %s AND user_id = %s""",
                    (identity.workspace_id, identity.user_id),
                ).fetchone()
                if membership is None:
                    raise MembershipRequiredError
                if write and membership["role"] not in {"owner", "editor"}:
                    raise WritePermissionRequiredError
                yield connection

    def bootstrap_development_workspace(
        self,
        identity: WorkspaceIdentity,
        workspace_name: str,
    ) -> None:
        """Idempotently create the fixed local identity after explicit dev opt-in."""
        with self._pool.connection() as connection:
            with connection.transaction():
                connection.execute(
                    "SELECT set_config('app.workspace_id', %s, true)",
                    (str(identity.workspace_id),),
                )
                connection.execute(
                    """INSERT INTO public.workspaces (id, name)
                       VALUES (%s, %s)
                       ON CONFLICT (id) DO NOTHING""",
                    (identity.workspace_id, workspace_name),
                )
                connection.execute(
                    """INSERT INTO public.workspace_members
                           (workspace_id, user_id, role)
                       VALUES (%s, %s, 'owner')
                       ON CONFLICT (workspace_id, user_id) DO NOTHING""",
                    (identity.workspace_id, identity.user_id),
                )
