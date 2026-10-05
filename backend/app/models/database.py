"""Database connection lifecycle and tenant-safe transaction boundaries."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import secrets
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool
from pwdlib import PasswordHash


CURRENT_SCHEMA_REVISION = "0021"
TENANT_TABLES = (
    "workspaces",
    "workspace_members",
    "documents",
    "document_versions",
    "chunks",
    "insights",
    "insight_sources",
    "analysis_jobs",
    "analysis_job_sources",
    "flare_generation_runs",
    "analysis_runs",
    "github_connection_states",
    "github_connections",
    "activity_events",
    "import_batches",
    "import_packages",
    "import_package_entries",
    "import_objects",
    "import_publications",
    "analysis_schedules",
    "analysis_daily_quotas",
    "analysis_cycles",
    "analysis_cycle_sources",
    "analysis_chunk_selection_history",
    "scheduled_analysis_notifications",
    "billing_checkout_intents",
    "billing_subscriptions",
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
        "SELECT rolname = 'flare_app' AND NOT rolsuper AND NOT rolbypassrls "
        "AND NOT rolcreatedb AND NOT rolcreaterole AND NOT EXISTS ("
        "SELECT 1 FROM pg_auth_members WHERE member = pg_roles.oid) "
        "FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    if safe_role != (True,):
        return False

    # Make the check independent from PGOPTIONS or a reused caller connection.
    connection.execute("SELECT set_config('app.workspace_id', '', true), set_config('app.user_id', '', true)")

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
               UNION ALL SELECT 1 FROM public.analysis_jobs
               UNION ALL SELECT 1 FROM public.analysis_job_sources
               UNION ALL SELECT 1 FROM public.flare_generation_runs
               UNION ALL SELECT 1 FROM public.analysis_runs
               UNION ALL SELECT 1 FROM public.github_connection_states
               UNION ALL SELECT 1 FROM public.github_connections
               UNION ALL SELECT 1 FROM public.activity_events
               UNION ALL SELECT 1 FROM (SELECT workspace_id FROM public.import_packages) visible_packages
               UNION ALL SELECT 1 FROM (SELECT workspace_id FROM public.import_package_entries) visible_package_entries
               UNION ALL SELECT 1 FROM (SELECT workspace_id FROM public.import_objects) visible_objects
               UNION ALL SELECT 1 FROM (SELECT workspace_id FROM public.import_publications) visible_publications
               UNION ALL SELECT 1 FROM public.import_batches
               UNION ALL SELECT 1 FROM public.analysis_schedules
               UNION ALL SELECT 1 FROM public.analysis_daily_quotas
               UNION ALL SELECT 1 FROM public.analysis_cycles
               UNION ALL SELECT 1 FROM public.analysis_cycle_sources
               UNION ALL SELECT 1 FROM public.analysis_chunk_selection_history
               UNION ALL SELECT 1 FROM public.scheduled_analysis_notifications
               UNION ALL SELECT 1 FROM (SELECT workspace_id FROM public.billing_checkout_intents) visible_billing_intents
               UNION ALL SELECT 1 FROM public.billing_subscriptions
           )"""
    ).fetchone()
    if customer_rows_are_hidden != (True,):
        return False

    growth_safe = connection.execute("""SELECT
        NOT has_table_privilege(current_user,'public.signup_attribution','SELECT')
        AND NOT has_table_privilege(current_user,'public.acquisition_visitors','SELECT')
        AND NOT has_function_privilege(current_user,'public.growth_report(timestamptz,timestamptz,text,text)','EXECUTE')
        AND has_function_privilege(current_user,'public.acquisition_touch(text,text,jsonb,text,boolean)','EXECUTE')
        AND has_function_privilege(current_user,'public.growth_inspection(uuid,uuid,uuid)','EXECUTE')
        AND (SELECT count(*)=6 FROM pg_class WHERE relnamespace='public'::regnamespace
          AND relname IN ('growth_policy','acquisition_visitors','acquisition_budgets','signup_attribution','growth_workspace_optouts','funnel_facts')
          AND relrowsecurity AND relforcerowsecurity)""").fetchone()
    if growth_safe != (True,):
        return False

    billing_safe = connection.execute("""SELECT
        NOT has_table_privilege(current_user,'public.billing_webhook_events','SELECT,INSERT,UPDATE,DELETE')
        AND NOT has_table_privilege(current_user,'public.billing_subscriptions','INSERT,UPDATE,DELETE')
        AND NOT has_table_privilege(current_user,'public.billing_checkout_intents','INSERT,UPDATE,DELETE')
        AND NOT has_column_privilege(current_user,'public.billing_checkout_intents','token_hash','SELECT')
        AND has_function_privilege(current_user,'public.create_billing_checkout_intent(text,text,integer)','EXECUTE')
        AND has_function_privilege(current_user,'public.apply_paddle_billing_event(jsonb)','EXECUTE')
        AND NOT has_function_privilege(current_user,'public._apply_paddle_billing_event(jsonb)','EXECUTE')
        AND NOT has_function_privilege('public','public.apply_paddle_billing_event(jsonb)','EXECUTE')
        AND (SELECT count(*)=3 FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
            WHERE p.oid IN ('public.create_billing_checkout_intent(text,text,integer)'::regprocedure,
                'public.apply_paddle_billing_event(jsonb)'::regprocedure,'public._apply_paddle_billing_event(jsonb)'::regprocedure)
            AND p.prosecdef AND p.proconfig @> ARRAY['search_path=pg_catalog, public, pg_temp']
            AND r.rolname IN ('flare_owner','flare_billing_executor') AND NOT r.rolsuper
            AND NOT r.rolbypassrls AND NOT r.rolcreatedb AND NOT r.rolcreaterole
            AND (r.rolname='flare_owner' OR NOT r.rolcanlogin)
            AND NOT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid))
        AND (SELECT relrowsecurity AND relforcerowsecurity FROM pg_class
            WHERE oid='public.billing_webhook_events'::regclass)""").fetchone()
    if billing_safe != (True,):
        return False

    extension = connection.execute(
        "SELECT 1 FROM pg_extension "
        "WHERE extname IN ('vector', 'pgvector') AND to_regtype('vector') IS NOT NULL"
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
                    """SELECT rolname = 'flare_app' AND NOT rolsuper AND NOT rolbypassrls
                              AND NOT rolcreatedb AND NOT rolcreaterole
                              AND NOT EXISTS (
                                  SELECT 1 FROM pg_auth_members WHERE member = pg_roles.oid
                              ) AS safe
                       FROM pg_roles WHERE rolname = current_user"""
                ).fetchone()
                if safe_role is None or safe_role["safe"] is not True:
                    raise RuntimeError(
                        "Application database connections must use a non-superuser, "
                        "non-BYPASSRLS flare_app role"
                    )
        except Exception:
            self._pool.close()
            raise

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def connection(self, *, timeout: float | None = None) -> Iterator[Connection]:
        """Yield a pooled connection without selecting customer context."""
        with self._pool.connection(timeout=timeout) as connection:
            yield connection

    @contextmanager
    def workspace_transaction(
        self,
        identity: WorkspaceIdentity,
        *,
        write: bool = False,
        snapshot: bool = False,
    ) -> Iterator[Connection]:
        """Select one workspace locally, verify membership, then yield a transaction."""
        if snapshot and write:
            raise ValueError("A workspace snapshot is read-only")
        with self._pool.connection() as connection:
            with connection.transaction():
                if snapshot:
                    # Establish the snapshot before context/membership reads;
                    # SET TRANSACTION leaves the pooled session default intact.
                    connection.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                    )
                connection.execute(
                    "SELECT set_config('app.workspace_id', %s, true), set_config('app.user_id', %s, true)",
                    (str(identity.workspace_id), identity.user_id),
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
                    "SELECT set_config('app.workspace_id', %s, true), set_config('app.user_id', %s, true)",
                    (str(identity.workspace_id), identity.user_id),
                )
                existing = connection.execute(
                    "SELECT role FROM public.workspace_members WHERE workspace_id = %s AND user_id = %s",
                    (identity.workspace_id, identity.user_id),
                ).fetchone()
                if existing is None:
                    connection.execute(
                        "SELECT public.provision_workspace(%s, %s)",
                        (identity.workspace_id, workspace_name),
                    )
                # Development identity is deliberately not a login credential:
                # the random password is discarded after its hash is stored.
                connection.execute(
                    """INSERT INTO public.auth_users
                           (id, email, password_hash, name, initial_workspace_id, disabled)
                       VALUES (%s, %s, %s, %s, %s, false)
                       ON CONFLICT (id) DO UPDATE SET disabled = false""",
                    (
                        identity.user_id,
                        self._development_user_email(identity.user_id),
                        PasswordHash.recommended().hash(secrets.token_urlsafe(32)),
                        "Development user",
                        identity.workspace_id,
                    ),
                )

    @staticmethod
    def _development_user_email(user_id: str) -> str:
        """Generate a valid, deterministic address without exposing the dev id."""
        fingerprint = sha256(user_id.encode("utf-8")).hexdigest()
        return f"dev-{fingerprint}@flare.invalid"
