"""Bounded acquisition and durable versioned funnel observations."""
import os
from pathlib import Path
from alembic import op

revision = '0020'
down_revision = '0019'
branch_labels = None
depends_on = None

TABLES = ('growth_policy', 'acquisition_visitors', 'acquisition_budgets', 'signup_attribution', 'growth_workspace_optouts', 'funnel_facts')
FUNCTIONS = {
    'acquisition_policy()': 'flare_app',
    'acquisition_touch(text,text,jsonb,text,boolean)': 'flare_app',
    'acquisition_freeze(text)': 'flare_app', 'acquisition_forget(text)': 'flare_app',
    'growth_fact(uuid,text,text,uuid,timestamptz,text,integer,integer)': None,
    'growth_committed()': None, 'growth_analyze_fact(uuid)': None, 'growth_terminal()': None,
    'growth_reconcile(integer)': 'flare_worker', 'growth_inspection(uuid,uuid,uuid)': 'flare_app',
    'growth_withdraw(boolean)': 'flare_app', 'growth_account_deleted()': None, 'growth_event_guard()': None,
    'growth_cleanup(integer)': 'flare_worker', 'growth_report(timestamptz,timestamptz,text,text)': None,
}


def upgrade():
    owner = 'flare_owner' if os.getenv('FLARE_DATABASE_PROVIDER') == 'yandex' else 'flare_job_executor'
    root = Path(__file__).resolve().parents[2] / 'db'
    for name in ('acquisition.sql', 'funnel.sql'):
        op.execute((root / name).read_text())
    op.execute(f'''GRANT SELECT(id,initial_workspace_id,created_at,verification_provenance,email_verified_at)
        ON public.auth_users TO {owner}''')
    op.execute(f'''GRANT SELECT(id,workspace_id,requested_by_user_id,status,completed_at,chunk_count)
        ON public.import_batches TO {owner};
        CREATE POLICY growth_import_reconcile ON public.import_batches FOR SELECT TO {owner} USING(true);''')
    for table in TABLES:
        op.execute(f'''ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON public.{table} FROM PUBLIC,flare_app,flare_worker;
        GRANT SELECT,INSERT,UPDATE,DELETE ON public.{table} TO {owner};
        CREATE POLICY growth_executor ON public.{table} TO {owner} USING(true) WITH CHECK(true);''')
    op.execute(f'''GRANT SELECT,INSERT,DELETE ON public.activity_events TO {owner};
    CREATE POLICY growth_event_executor ON public.activity_events TO {owner} USING(true) WITH CHECK(true);''')
    # Preserve existing queue checks and permit only actor-bound inspection.
    op.execute("""DO $$ DECLARE original text; BEGIN
      SELECT pg_get_expr(polwithcheck,polrelid) INTO original FROM pg_policy
      WHERE polname='activity_cycle_executor' AND polrelid='public.activity_events'::regclass;
      EXECUTE 'ALTER POLICY activity_cycle_executor ON public.activity_events WITH CHECK ((' || original || ') OR (
        event_type=''flare_viewed'' AND target_type=''flare'' AND interaction_id IS NOT NULL
        AND actor_id=nullif(current_setting(''app.user_id'',true),'''')
        AND workspace_id=nullif(current_setting(''app.workspace_id'',true),'''')::uuid
        AND metadata=jsonb_build_object(''source'',''insights_feed'')
        AND EXISTS(SELECT 1 FROM public.workspace_members m WHERE m.workspace_id=activity_events.workspace_id AND m.user_id=activity_events.actor_id)
        AND EXISTS(SELECT 1 FROM public.insights i WHERE i.workspace_id=activity_events.workspace_id AND i.id=activity_events.target_id AND i.flare_type IS NOT NULL)))';
    END $$;""")
    if owner != 'flare_owner':
        op.execute(f'GRANT CREATE ON SCHEMA public TO {owner}')
    for signature, role in FUNCTIONS.items():
        op.execute(f'ALTER FUNCTION public.{signature} OWNER TO {owner}')
        op.execute(f'REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC,flare_app,flare_worker')
        if role:
            op.execute(f'GRANT EXECUTE ON FUNCTION public.{signature} TO {role}')
        op.execute(f"ALTER FUNCTION public.{signature} SET statement_timeout='2s'")
    if owner != 'flare_owner':
        op.execute(f'REVOKE CREATE ON SCHEMA public FROM {owner}')
    op.execute("ALTER FUNCTION public.growth_committed() SET lock_timeout='100ms'")
    # Reporting principal is provisioned separately, never inherited by app/worker.
    op.execute('''DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='flare_growth_reporter') THEN
    GRANT EXECUTE ON FUNCTION public.growth_report(timestamptz,timestamptz,text,text) TO flare_growth_reporter;
    END IF; END $$;''')


def downgrade():
    raise RuntimeError('0020 retains account/privacy lineage; use a reviewed restore')
