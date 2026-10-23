"""Database connection lifecycle and tenant-safe transaction boundaries."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import secrets
from uuid import UUID

import psycopg
from psycopg import Connection
from psycopg.rows import dict_row, tuple_row
from psycopg_pool import ConnectionPool
from pwdlib import PasswordHash


CURRENT_SCHEMA_REVISION = "0026"
DATABASE_STARTUP_TIMEOUT_SECONDS = 300
DATABASE_READINESS_TIMEOUT_SECONDS = 3
IMPORT_STAGING_TABLES = ("import_staging_blocks", "import_staging_health")
# These are private tables, rather than member-readable tenant projections. The
# API and worker get only their exact capabilities; even a column SELECT grant
# on the payload would violate the staging boundary.
IMPORT_STAGING_FUNCTIONS = {
    "import_staging_upload(text,uuid,text,integer,bytea)": ("flare_app",),
    "import_staging_read(text,uuid,uuid,bigint,integer)": ("flare_worker",),
    "import_staging_size(text,uuid,uuid,bigint)": ("flare_worker",),
    "import_staging_retire(text,uuid)": ("flare_worker",),
    "import_staging_heartbeat(text)": ("flare_worker",),
    "import_staging_ready()": ("flare_app",),
    "import_staging_probe()": ("flare_app", "flare_worker"),
    "_import_staging_upload_guard(text,uuid)": (),
    "_import_staging_job_guard(text,uuid,uuid,bigint)": (),
    "guard_import_staging_seal()": (),
    "guard_import_staging_package_rate()": (),
}
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
    "source_connections", "source_auth_states", "source_jobs", "source_items",
    "campaign_links",
    "campaign_link_daily_opens",
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

    team_tables = ['team_policy','team_projects','team_invitations','team_tasks','team_task_history','team_member_events']
    team_private = connection.execute('''SELECT count(*)=6 AND bool_and(relrowsecurity AND relforcerowsecurity
        AND NOT has_table_privilege('flare_app',c.oid,'SELECT')
        AND NOT has_table_privilege('flare_app',c.oid,'INSERT')
        AND NOT has_table_privilege('flare_app',c.oid,'UPDATE')
        AND NOT has_table_privilege('flare_worker',c.oid,'SELECT'))
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname=ANY(%s)''',(team_tables,)).fetchone()
    if team_private != (True,):
        return False
    team_functions = connection.execute('''SELECT count(*)=25 AND bool_and(p.prosecdef
        AND p.proconfig @> ARRAY[CASE WHEN r.rolname='flare_owner' THEN 'search_path=pg_catalog, public, flare_team_scope, pg_temp' ELSE 'search_path=pg_catalog, public, pg_temp' END]
        AND r.rolname IN ('flare_owner','flare_team_executor') AND NOT r.rolsuper AND NOT r.rolbypassrls
        AND NOT r.rolcreatedb AND NOT r.rolcreaterole
        AND (r.rolname='flare_owner' OR NOT r.rolcanlogin AND NOT r.rolinherit)
        AND NOT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid)
        AND NOT has_function_privilege('public',p.oid,'EXECUTE')
        AND NOT has_function_privilege('flare_worker',p.oid,'EXECUTE')
        AND has_function_privilege('flare_app',p.oid,'EXECUTE')=(left(p.proname,6)<>'_team_' AND p.proname<>'guard_team_content'))
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_roles r ON r.oid=p.proowner
        WHERE n.nspname='public' AND (left(p.proname,5)='team_' OR left(p.proname,6)='_team_' OR p.proname='guard_team_content')''').fetchone()
    if team_functions != (True,):
        return False
    managed_team_guard = connection.execute('''SELECT NOT EXISTS(
        SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace JOIN pg_roles r ON r.oid=p.proowner
        WHERE n.nspname='public' AND r.rolname='flare_owner' AND p.prosecdef
          AND left(p.proname,5)<>'team_' AND left(p.proname,6)<>'_team_' AND p.proname<>'guard_team_content'
          AND NOT EXISTS(SELECT 1 FROM unnest(p.proconfig) setting WHERE setting LIKE 'search_path=%' AND position('flare_team_scope' IN setting)=0))''').fetchone()
    if managed_team_guard != (True,):
        return False
    marker_schema = connection.execute("""SELECT
        (NOT EXISTS(SELECT 1 FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
            WHERE p.proname='team_projects_list' AND r.rolname='flare_owner')
         OR EXISTS(SELECT 1 FROM pg_namespace WHERE nspname='flare_team_scope'))
        AND NOT EXISTS(SELECT 1 FROM pg_namespace n
        WHERE n.nspname='flare_team_scope' AND (pg_get_userbyid(n.nspowner)<>'flare_owner'
          OR has_schema_privilege('flare_app',n.oid,'CREATE') OR has_schema_privilege('flare_worker',n.oid,'CREATE')
          OR EXISTS(SELECT 1 FROM pg_class WHERE relnamespace=n.oid)
          OR EXISTS(SELECT 1 FROM pg_proc WHERE pronamespace=n.oid)))""").fetchone()
    if marker_schema != (True,):
        return False
    team_worker_admission = connection.execute('''SELECT count(*)=5 AND bool_and(
        position('public._team_workspace_paid' IN pg_get_functiondef(p.oid))>0)
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname='public' AND p.proname=ANY(%s)''',
        (['materialize_analysis_cycles','claim_analysis_cycle_refresh','enqueue_due_analysis_cycles','claim_analysis_job','analysis_job_check'],)).fetchone()
    if team_worker_admission != (True,):
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
               UNION ALL SELECT 1 FROM (SELECT workspace_id FROM public.source_connections) source_connections_visible
               UNION ALL SELECT 1 FROM (SELECT workspace_id FROM public.source_auth_states) source_states_visible
               UNION ALL SELECT 1 FROM (SELECT workspace_id FROM public.source_jobs) source_jobs_visible
               UNION ALL SELECT 1 FROM (SELECT workspace_id FROM public.source_items) source_items_visible
               UNION ALL SELECT 1 FROM public.campaign_links
               UNION ALL SELECT 1 FROM public.campaign_link_daily_opens
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

    if not _source_storage_is_safe(connection):
        return False

    if not _import_staging_is_safe(connection):
        return False

    if not _campaign_activity_is_safe(connection):
        return False
    if not _campaign_links_are_safe(connection):
        return False

    extension = connection.execute(
        "SELECT 1 FROM pg_extension "
        "WHERE extname IN ('vector', 'pgvector') AND to_regtype('vector') IS NOT NULL"
    ).fetchone()
    return extension is not None


def _campaign_activity_is_safe(connection: Connection) -> bool:
    """Daily aggregates are read-only for owners and private to the same tenant."""
    safe = connection.execute("""SELECT relrowsecurity AND relforcerowsecurity
        AND has_table_privilege('flare_app',oid,'SELECT')
        AND NOT has_table_privilege('flare_app',oid,'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
        AND NOT has_any_column_privilege('flare_app',oid,'INSERT,UPDATE,REFERENCES')
        AND NOT has_table_privilege('flare_worker',oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
        AND NOT has_any_column_privilege('flare_worker',oid,'SELECT,INSERT,UPDATE,REFERENCES')
        AND NOT has_table_privilege('public',oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
        AND NOT has_any_column_privilege('public',oid,'SELECT,INSERT,UPDATE,REFERENCES')
        AND NOT has_column_privilege('flare_app','public.campaign_links','activity_started_at','INSERT')
        AND NOT has_column_privilege('flare_app','public.campaign_links','activity_started_at','UPDATE')
        AND (SELECT count(*)=2 FROM pg_policy WHERE polrelid='public.campaign_link_daily_opens'::regclass)
        AND EXISTS(SELECT 1 FROM pg_policy p
            WHERE p.polrelid='public.campaign_link_daily_opens'::regclass
              AND p.polname='campaign_daily_owner' AND p.polcmd='r'
              AND p.polroles=ARRAY[(SELECT oid FROM pg_roles WHERE rolname='flare_app')]
              AND position('app.workspace_id' IN pg_get_expr(p.polqual,p.polrelid))>0
              AND position('app.user_id' IN pg_get_expr(p.polqual,p.polrelid))>0
              AND position('owner' IN pg_get_expr(p.polqual,p.polrelid))>0)
        AND EXISTS(SELECT 1 FROM pg_policy p
            WHERE p.polrelid='public.campaign_link_daily_opens'::regclass
              AND p.polname='campaign_daily_executor' AND p.polcmd='*'
              AND cardinality(p.polroles)=1
              AND EXISTS(SELECT 1 FROM pg_roles r WHERE r.oid=p.polroles[1]
                  AND r.rolname IN ('flare_owner','flare_job_executor'))
              AND pg_get_expr(p.polqual,p.polrelid)='true'
              AND pg_get_expr(p.polwithcheck,p.polrelid)='true')
        FROM pg_class WHERE oid='public.campaign_link_daily_opens'::regclass""").fetchone()
    return safe == (True,)


def _campaign_links_are_safe(connection: Connection) -> bool:
    """Require owner-scoped metadata and narrow anonymous counter capabilities."""
    table = connection.execute("""SELECT relrowsecurity AND relforcerowsecurity
        AND has_table_privilege('flare_app',oid,'SELECT')
        AND NOT has_table_privilege('flare_app',oid,'DELETE,TRUNCATE,REFERENCES,TRIGGER')
        AND NOT has_any_column_privilege('flare_app',oid,'REFERENCES')
        AND NOT has_table_privilege('flare_worker',oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
        AND NOT has_any_column_privilege('flare_worker',oid,'SELECT,INSERT,UPDATE,REFERENCES')
        AND NOT has_table_privilege('public',oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
        AND NOT has_any_column_privilege('public',oid,'SELECT,INSERT,UPDATE,REFERENCES')
        AND has_column_privilege('flare_app',oid,'label','UPDATE')
        AND has_column_privilege('flare_app',oid,'archived_at','UPDATE')
        AND has_column_privilege('flare_app',oid,'id','INSERT')
        AND has_column_privilege('flare_app',oid,'workspace_id','INSERT')
        AND NOT has_column_privilege('flare_app',oid,'created_by_user_id','INSERT')
        AND has_column_privilege('flare_app',oid,'label','INSERT')
        AND has_column_privilege('flare_app',oid,'slug','INSERT')
        AND has_column_privilege('flare_app',oid,'destination_path','INSERT')
        AND has_column_privilege('flare_app',oid,'utm_source','INSERT')
        AND has_column_privilege('flare_app',oid,'utm_medium','INSERT')
        AND has_column_privilege('flare_app',oid,'utm_campaign','INSERT')
        AND has_column_privilege('flare_app',oid,'utm_content','INSERT')
        AND NOT has_column_privilege('flare_app',oid,'click_count','INSERT')
        AND NOT has_column_privilege('flare_app',oid,'created_at','INSERT')
        AND NOT has_column_privilege('flare_app',oid,'archived_at','INSERT')
        AND NOT has_column_privilege('flare_app',oid,'id','UPDATE')
        AND NOT has_column_privilege('flare_app',oid,'workspace_id','UPDATE')
        AND NOT has_column_privilege('flare_app',oid,'created_by_user_id','UPDATE')
        AND NOT has_column_privilege('flare_app',oid,'slug','UPDATE')
        AND NOT has_column_privilege('flare_app',oid,'destination_path','UPDATE')
        AND NOT has_column_privilege('flare_app',oid,'utm_source','UPDATE')
        AND NOT has_column_privilege('flare_app',oid,'utm_medium','UPDATE')
        AND NOT has_column_privilege('flare_app',oid,'utm_campaign','UPDATE')
        AND NOT has_column_privilege('flare_app',oid,'utm_content','UPDATE')
        AND NOT has_column_privilege('flare_app',oid,'click_count','UPDATE')
        AND NOT has_column_privilege('flare_app',oid,'created_at','UPDATE')
        FROM pg_class WHERE oid='public.campaign_links'::regclass""").fetchone()
    if table != (True,):
        return False
    creator_contract = connection.execute("""SELECT
        EXISTS(
            SELECT 1
              FROM pg_attribute attribute
              JOIN pg_attrdef default_value
                ON default_value.adrelid=attribute.attrelid
               AND default_value.adnum=attribute.attnum
             WHERE attribute.attrelid='public.campaign_links'::regclass
               AND attribute.attname='created_by_user_id'
               AND pg_get_expr(default_value.adbin,default_value.adrelid)=
                   'NULLIF(current_setting(''app.user_id''::text, true), ''''::text)'
        )
        AND EXISTS(
            SELECT 1
              FROM pg_constraint relationship
             WHERE relationship.conrelid='public.campaign_links'::regclass
               AND relationship.contype='f'
               AND relationship.confrelid='public.auth_users'::regclass
               AND relationship.confdeltype='n'
               AND relationship.convalidated
               AND relationship.conkey=ARRAY[(
                   SELECT attnum FROM pg_attribute
                    WHERE attrelid='public.campaign_links'::regclass
                      AND attname='created_by_user_id'
               )]::smallint[]
               AND relationship.confkey=ARRAY[(
                   SELECT attnum FROM pg_attribute
                    WHERE attrelid='public.auth_users'::regclass
                      AND attname='id'
               )]::smallint[]
        )""").fetchone()
    if creator_contract != (True,):
        return False
    policies = connection.execute("""SELECT
        (SELECT count(*)=2 FROM pg_policy
          WHERE polrelid='public.campaign_links'::regclass)
        AND EXISTS(SELECT 1 FROM pg_policy p
          WHERE p.polrelid='public.campaign_links'::regclass
            AND p.polname='campaign_links_owner' AND p.polcmd='*'
            AND p.polroles=ARRAY[(SELECT oid FROM pg_roles WHERE rolname='flare_app')]
            AND position('app.workspace_id' IN pg_get_expr(p.polqual,p.polrelid))>0
            AND position('app.user_id' IN pg_get_expr(p.polqual,p.polrelid))>0
            AND position('owner' IN pg_get_expr(p.polqual,p.polrelid))>0
            AND position('app.workspace_id' IN pg_get_expr(p.polwithcheck,p.polrelid))>0
            AND position('app.user_id' IN pg_get_expr(p.polwithcheck,p.polrelid))>0
            AND position('owner' IN pg_get_expr(p.polwithcheck,p.polrelid))>0)
        AND EXISTS(SELECT 1 FROM pg_policy p
          WHERE p.polrelid='public.campaign_links'::regclass
            AND p.polname='campaign_links_executor' AND p.polcmd='*'
            AND cardinality(p.polroles)=1
            AND EXISTS(SELECT 1 FROM pg_roles r WHERE r.oid=p.polroles[1]
                AND r.rolname IN ('flare_owner','flare_job_executor'))
            AND pg_get_expr(p.polqual,p.polrelid)='true'
            AND pg_get_expr(p.polwithcheck,p.polrelid)='true')""").fetchone()
    if policies != (True,):
        return False
    signatures = [
        "public.guard_campaign_link_limit()",
        "public.campaign_link_resolve(text)",
        "public.campaign_link_count(text)",
    ]
    functions = connection.execute("""SELECT count(*)=%s AND bool_and(
        p.prosecdef
        AND p.proconfig @> ARRAY['search_path=pg_catalog, public, pg_temp']
        AND r.rolname IN ('flare_owner','flare_job_executor')
        AND NOT r.rolsuper AND NOT r.rolbypassrls
        AND NOT r.rolcreatedb AND NOT r.rolcreaterole
        AND (r.rolname='flare_owner' OR (NOT r.rolcanlogin AND NOT r.rolinherit))
        AND NOT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid)
        AND NOT has_function_privilege('public',p.oid,'EXECUTE')
        AND NOT has_function_privilege('flare_worker',p.oid,'EXECUTE'))
        FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
        WHERE p.oid=ANY(%s::regprocedure[])""", (len(signatures), signatures)).fetchone()
    if functions != (True,):
        return False
    grants = connection.execute("""SELECT
        NOT has_function_privilege('flare_app','public.guard_campaign_link_limit()','EXECUTE')
        AND has_function_privilege('flare_app','public.campaign_link_resolve(text)','EXECUTE')
        AND has_function_privilege('flare_app','public.campaign_link_count(text)','EXECUTE')
        AND EXISTS(SELECT 1 FROM pg_trigger WHERE tgrelid='public.campaign_links'::regclass
            AND tgname='campaign_link_limit_guard' AND NOT tgisinternal)""").fetchone()
    return grants == (True,)


def _import_staging_is_safe(connection: Connection) -> bool:
    """Require private staging payloads and narrowly owned capabilities."""
    tables = ["public." + table for table in IMPORT_STAGING_TABLES]
    private_tables = connection.execute(
        """SELECT count(*) = %s AND bool_and(c.relrowsecurity AND c.relforcerowsecurity
               AND NOT has_table_privilege('public', c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
               AND NOT has_table_privilege('flare_app', c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
               AND NOT has_table_privilege('flare_worker', c.oid, 'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
               AND NOT has_any_column_privilege('public', c.oid, 'SELECT,INSERT,UPDATE,REFERENCES')
               AND NOT has_any_column_privilege('flare_app', c.oid, 'SELECT,INSERT,UPDATE,REFERENCES')
               AND NOT has_any_column_privilege('flare_worker', c.oid, 'SELECT,INSERT,UPDATE,REFERENCES'))
           FROM pg_class c WHERE c.oid = ANY(%s::regclass[])""",
        (len(tables), tables),
    ).fetchone()
    if private_tables != (True,):
        return False

    signatures = ["public." + signature for signature in IMPORT_STAGING_FUNCTIONS]
    safe_owners = connection.execute(
        """SELECT count(*) = %s AND bool_and(coalesce(p.prosecdef
               AND p.proconfig @> ARRAY['search_path=pg_catalog, public, pg_temp']
               AND r.rolname IN ('flare_owner','flare_job_executor')
               AND NOT r.rolsuper AND NOT r.rolbypassrls AND NOT r.rolcreatedb AND NOT r.rolcreaterole
               AND (r.rolname='flare_owner' OR NOT r.rolcanlogin)
               AND NOT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid), false))
           FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner
           WHERE p.oid = ANY(%s::regprocedure[])""",
        (len(signatures), signatures),
    ).fetchone()
    if safe_owners != (True,):
        return False

    grants = connection.execute(
        """SELECT bool_and(
               has_function_privilege('flare_app', signature, 'EXECUTE') = app_allowed
               AND has_function_privilege('flare_worker', signature, 'EXECUTE') = worker_allowed
               AND NOT has_function_privilege('public', signature, 'EXECUTE'))
           FROM unnest(%s::text[], %s::boolean[], %s::boolean[])
             AS capabilities(signature, app_allowed, worker_allowed)""",
        (
            signatures,
            ["flare_app" in roles for roles in IMPORT_STAGING_FUNCTIONS.values()],
            ["flare_worker" in roles for roles in IMPORT_STAGING_FUNCTIONS.values()],
        ),
    ).fetchone()
    return grants == (True,)


def _source_storage_is_safe(connection: Connection) -> bool:
    tables = ["source_connections", "source_auth_states", "source_jobs", "source_items", "source_worker_health"]
    table_safety = connection.execute("""SELECT count(*)=5 AND bool_and(relrowsecurity AND relforcerowsecurity
      AND NOT has_table_privilege('flare_app',oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
      AND NOT has_table_privilege('flare_worker',oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
      AND NOT has_any_column_privilege('flare_worker',oid,'SELECT,INSERT,UPDATE,REFERENCES')
      AND NOT has_table_privilege('public',oid,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
      AND NOT has_any_column_privilege('public',oid,'SELECT,INSERT,UPDATE,REFERENCES'))
      FROM pg_class WHERE relnamespace='public'::regnamespace AND relname=ANY(%s)""", (tables,)).fetchone()
    if table_safety != (True,): return False
    columns_private = connection.execute("""SELECT bool_and(NOT has_column_privilege('flare_app',table_name,column_name,'SELECT,INSERT,UPDATE,REFERENCES'))
      FROM (SELECT 'public.'||c.relname AS table_name,a.attname AS column_name FROM pg_class c JOIN pg_attribute a ON a.attrelid=c.oid WHERE c.relnamespace='public'::regnamespace AND c.relname=ANY(%s) AND a.attnum>0 AND NOT a.attisdropped AND a.attname<>'workspace_id') columns""", (tables,)).fetchone()
    if columns_private != (True,): return False
    signatures = ['public.source_api(text,uuid,jsonb)','public.claim_source_job(text[],integer)',
                  'public.source_worker_step(uuid,uuid,bigint,text,jsonb)']
    functions_safe = connection.execute("""SELECT count(*)=3 AND bool_and(p.prosecdef
      AND p.proconfig @> ARRAY['search_path=pg_catalog, public, pg_temp']
      AND r.rolname IN ('flare_owner','flare_job_executor') AND NOT r.rolsuper AND NOT r.rolbypassrls
      AND NOT r.rolcreatedb AND NOT r.rolcreaterole AND (r.rolname='flare_owner' OR NOT r.rolcanlogin)
      AND NOT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=r.oid))
      FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner WHERE p.oid=ANY(%s::regprocedure[])""", (signatures,)).fetchone()
    if functions_safe != (True,): return False
    grants_safe = connection.execute("""SELECT bool_and(
      has_function_privilege('flare_app',signature,'EXECUTE')=app_allowed
      AND has_function_privilege('flare_worker',signature,'EXECUTE')=worker_allowed
      AND NOT has_function_privilege('public',signature,'EXECUTE'))
      FROM unnest(%s::text[],%s::boolean[],%s::boolean[]) AS f(signature,app_allowed,worker_allowed)""",
      (signatures,[True,False,False],[False,True,True])).fetchone()
    return grants_safe == (True,)


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
            # Azure can need several minutes to establish the first TLS database
            # connection while an App Service instance is warming. Keep startup
            # bounded, but don't turn that transient warmup into a restart loop.
            self._pool.open(wait=True, timeout=DATABASE_STARTUP_TIMEOUT_SECONDS)
            with self._pool.connection() as connection:
                # The pool serves dictionaries to application code, while the
                # exhaustive startup fence intentionally compares tuple results.
                previous_row_factory = connection.row_factory
                connection.row_factory = tuple_row
                try:
                    ready = _connection_is_ready(connection)
                finally:
                    connection.row_factory = previous_row_factory
                if not ready:
                    raise RuntimeError(
                        "Application database failed the schema and security readiness fence"
                    )
        except Exception:
            self._pool.close()
            raise

    def is_ready(self, *, timeout: float = DATABASE_READINESS_TIMEOUT_SECONDS) -> bool:
        """Check serving readiness through the existing pool in one round trip."""
        with self._pool.connection(timeout=timeout) as connection:
            row = connection.execute(
                """SELECT
                    EXISTS (
                        SELECT 1 FROM pg_roles
                         WHERE rolname = current_user
                           AND rolname = 'flare_app'
                           AND NOT rolsuper
                           AND NOT rolbypassrls
                           AND NOT rolcreatedb
                           AND NOT rolcreaterole
                           AND NOT EXISTS (
                               SELECT 1 FROM pg_auth_members
                                WHERE member = pg_roles.oid
                           )
                    )
                    AND (
                        SELECT count(*) = 1 AND bool_and(version_num = %s)
                          FROM public.alembic_version
                    )
                    AND current_setting('transaction_read_only') = 'off'
                    AND NOT pg_is_in_recovery()
                    AND to_regtype('vector') IS NOT NULL AS ready""",
                (CURRENT_SCHEMA_REVISION,),
            ).fetchone()
            return row is not None and row["ready"] is True

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
        timeout: float | None = None,
        statement_timeout_ms: int | None = None,
        lock_timeout_ms: int | None = None,
    ) -> Iterator[Connection]:
        """Select one workspace locally, verify membership, then yield a transaction."""
        if snapshot and write:
            raise ValueError("A workspace snapshot is read-only")
        with self._pool.connection(timeout=timeout) as connection:
            with connection.transaction():
                if snapshot:
                    connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                for name, value in (('statement_timeout', statement_timeout_ms), ('lock_timeout', lock_timeout_ms)):
                    if value is not None:
                        if type(value) is not int or value <= 0:
                            raise ValueError('Transaction deadlines must be positive integers')
                        connection.execute('SELECT set_config(%s,%s,true)', (name, str(value)))
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
