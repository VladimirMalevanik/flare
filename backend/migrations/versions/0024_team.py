"""Bounded collaborative projects, invitations and tasks; capability defaults off."""
import os
from pathlib import Path
from alembic import op
from sqlalchemy import text

revision = '0024'
# DATA-003/0023 is an independent unmerged PR. Rebase this parent to0023 when
# that PR lands; the combined migration lineage is explicitly tested in review.
down_revision = '0022'
branch_labels = None
depends_on = None

FUNCTIONS = {
 '_team_actor()': False, '_team_paid(uuid)': False, '_team_workspace_paid(uuid)': False,
 '_team_guard(uuid,text)': False, '_team_retire_connections(uuid,text)': False,
 'team_projects_list()': True, 'team_capability()': True,
 'team_project_create(uuid,text)': True, 'team_project_rename(uuid,text)': True, 'team_project_usage(uuid)': True,
 'team_oauth_workspace(text,text)': True, 'team_members_list(uuid)': True,
 'team_invite(uuid,text,text,text)': True, 'team_invitations_list(uuid)': True,
 'team_invitation_cancel(uuid,uuid)': True, 'team_invitation_accept(text)': True,
 'team_membership_change(uuid,text,text,text)': True,
 'team_tasks_list(uuid,timestamptz,uuid)': True,
 'team_task_write(uuid,uuid,integer,jsonb,boolean)': True,
 'team_task_history_list(uuid,uuid)': True, 'team_task_get(uuid,uuid)': True, 'team_tasks_export(uuid)': True,
 'team_invitation_preview(text)': True, 'team_license_snapshots(uuid)': True, 'guard_team_content()': False,
}
TABLES = ('team_policy','team_projects','team_invitations','team_tasks','team_task_history','team_member_events')


def upgrade():
    managed = os.getenv('FLARE_DATABASE_PROVIDER') == 'yandex'
    owner = 'flare_owner' if managed else 'flare_team_executor'
    if not managed:
        op.execute('''DO $$ DECLARE previous text;
        BEGIN
          IF current_user IN ('flare_app','flare_worker','flare_onboarding') THEN RAISE EXCEPTION 'Runtime cannot migrate Team'; END IF;
          IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='flare_team_executor') THEN
            previous:=current_setting('createrole_self_grant'); PERFORM set_config('createrole_self_grant','',true);
            CREATE ROLE flare_team_executor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
            PERFORM set_config('createrole_self_grant',previous,true);
          END IF;
          IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='flare_team_executor' AND (rolcanlogin OR rolsuper OR rolbypassrls OR rolcreatedb OR rolcreaterole OR rolinherit))
            OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member='flare_team_executor'::regrole)
            OR EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid='flare_team_executor'::regrole AND NOT
              (member=current_user::regrole AND grantor=10 AND admin_option AND NOT inherit_option AND NOT set_option))
            OR has_schema_privilege('flare_team_executor','public','CREATE') THEN RAISE EXCEPTION 'Unsafe Team executor'; END IF;
          IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolsuper) THEN
            EXECUTE format('GRANT flare_team_executor TO %I WITH ADMIN FALSE, INHERIT TRUE, SET TRUE GRANTED BY %I',current_user,current_user);
          END IF;
        END $$;''')
    op.execute(Path(__file__).resolve().parents[2].joinpath('db/team.sql').read_text())
    op.execute(f'GRANT USAGE ON SCHEMA public TO {owner}')
    for table in TABLES:
        op.execute(f'''ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
          ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;
          REVOKE ALL ON public.{table} FROM PUBLIC,flare_app,flare_worker;
          GRANT SELECT,INSERT,UPDATE,DELETE ON public.{table} TO {owner};
          CREATE POLICY team_executor ON public.{table} TO {owner} USING(true) WITH CHECK(true);''')
    # Explicit column grants keep the executor narrower than a migration owner.
    op.execute(f'''GRANT SELECT,INSERT,UPDATE(name) ON public.workspaces TO {owner};
      GRANT SELECT,INSERT,UPDATE,DELETE ON public.workspace_members TO {owner};
      GRANT SELECT ON public.auth_users,public.billing_subscriptions,public.documents,public.chunks TO {owner};
      GRANT SELECT(token_hash,workspace_id,user_id,consumed_at,expires_at) ON public.github_connection_states TO {owner};
      GRANT UPDATE(status) ON public.billing_subscriptions TO {owner};
      GRANT SELECT,UPDATE(updated_by_user_id) ON public.analysis_schedules TO {owner};''')
    for table in ('workspaces','workspace_members','billing_subscriptions','documents','chunks','analysis_schedules','github_connection_states'):
        access = "current_setting('application_name',true)='flare-team-management'" if managed else 'true'
        op.execute(f'CREATE POLICY team_executor_access ON public.{table} TO {owner} USING({access}) WITH CHECK({access})')
    if managed:
        # Managed PostgreSQL uses the existing migration owner, not a new role.
        # Pin the management marker on this function family only. Every other
        # owner function resets it, even if a caller forges the transaction GUC.
        op.execute('''DO $$ DECLARE f record; BEGIN
          FOR f IN SELECT p.oid::regprocedure AS signature FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' AND p.proowner='flare_owner'::regrole AND p.prosecdef LOOP
            EXECUTE format('ALTER FUNCTION %s SET application_name TO %L',f.signature,'flare-runtime');
          END LOOP;
        END $$;''')
        op.execute('''ALTER POLICY executor_identity ON public.workspace_members USING(
          user_id=nullif(current_setting('app.user_id',true),'') OR current_setting('application_name',true)='flare-team-management');''')
        for table in ('documents','document_versions','chunks'):
            op.execute(f'''ALTER POLICY executor_member ON public.{table} USING(
              current_setting('application_name',true)='flare-team-management' OR EXISTS(SELECT 1 FROM public.workspace_members m
                WHERE m.workspace_id={table}.workspace_id AND m.user_id=nullif(current_setting('app.user_id',true),'') AND m.role IN ('owner','editor')));''')
    if not managed:
        op.execute(f'GRANT CREATE ON SCHEMA public TO {owner}')
    op.execute(f'''DO $$ BEGIN
      IF to_regclass('public.source_connections') IS NOT NULL THEN
        GRANT SELECT(id,workspace_id,owner_user_id,provider,scope_revision),UPDATE(credential_blob,cursor_blob,resources,enabled,status,scope_revision,error_code,updated_at) ON public.source_connections TO {owner};
        GRANT SELECT(state_hash,workspace_id,user_id,connection_id,expires_at,scope_revision),DELETE ON public.source_auth_states TO {owner};
        GRANT SELECT(workspace_id,owner_user_id,status),UPDATE(status,lease_token,lease_expires_at,cursor_blob,completed_at,error_code) ON public.source_jobs TO {owner};
      END IF;
    END $$;''')
    for table in ('source_connections','source_auth_states','source_jobs'):
        access = "current_setting('application_name',true)='flare-team-management'" if managed else 'true'
        op.execute(f'''DO $$ BEGIN
          IF to_regclass('public.{table}') IS NOT NULL THEN
            CREATE POLICY team_retirement_access ON public.{table} TO {owner} USING({access}) WITH CHECK({access});
          END IF;
        END $$;''')
    for signature, public in FUNCTIONS.items():
        op.execute(f'ALTER FUNCTION public.{signature} OWNER TO {owner}')
        op.execute(f'REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC,flare_app,flare_worker')
        if public:
            op.execute(f'GRANT EXECUTE ON FUNCTION public.{signature} TO flare_app')
        op.execute(f"ALTER FUNCTION public.{signature} SET statement_timeout='5s'")
        op.execute(f"ALTER FUNCTION public.{signature} SET lock_timeout='2s'")
        if managed:
            op.execute(f"ALTER FUNCTION public.{signature} SET application_name='flare-team-management'")
    for table in ('documents','document_versions','chunks'):
        op.execute(f'''CREATE TRIGGER team_content_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{table}
          FOR EACH ROW EXECUTE FUNCTION public.guard_team_content()''')
    # Filter inactive Team projects before worker admission. A failing INSERT
    # trigger on a bulk queue would incorrectly block unrelated personal jobs.
    worker_owner = 'flare_owner' if managed else 'flare_job_executor'
    op.execute(f'GRANT EXECUTE ON FUNCTION public._team_workspace_paid(uuid) TO {worker_owner}')
    replacements = [
        ('materialize_analysis_cycles(timestamptz,integer)', 'WHERE s.enabled',
         'WHERE s.enabled AND public._team_workspace_paid(s.workspace_id)'),
        ('claim_analysis_cycle_refresh(uuid,integer)', "WHERE c.refresh_status='scheduled' AND c.refresh_due_at<=now_at",
         "WHERE c.refresh_status='scheduled' AND c.refresh_due_at<=now_at AND public._team_workspace_paid(c.workspace_id)"),
        ('enqueue_due_analysis_cycles(text,text,integer,timestamptz,integer)', "WHERE c.refresh_status='ready' AND c.analysis_run_id IS NULL",
         "WHERE c.refresh_status='ready' AND c.analysis_run_id IS NULL AND public._team_workspace_paid(c.workspace_id)"),
        ('claim_analysis_job(uuid,integer)', 'WHERE j.attempts < j.max_attempts AND (',
         'WHERE public._team_workspace_paid(j.workspace_id) AND j.attempts < j.max_attempts AND ('),
        ('analysis_job_check(public.analysis_jobs)', "PERFORM set_config('app.workspace_id', p_job.workspace_id::text, true);",
         "IF NOT public._team_workspace_paid(p_job.workspace_id) THEN RETURN 'authorization_revoked'; END IF;\n            PERFORM set_config('app.workspace_id', p_job.workspace_id::text, true);"),
    ]
    optional = [
        ('claim_source_job(text[],integer)', "m.role IN ('owner','editor')) THEN",
         "m.role IN ('owner','editor')) OR NOT public._team_workspace_paid(c.workspace_id) THEN"),
        ('source_worker_step(uuid,uuid,bigint,text,jsonb)', 'PERFORM id FROM public.auth_users WHERE id=j.owner_user_id',
         "IF NOT public._team_workspace_paid(j.workspace_id) THEN RETURN jsonb_build_object('error','authorization_lost'); END IF;\n PERFORM id FROM public.auth_users WHERE id=j.owner_user_id"),
    ]
    for signature, original, replacement in replacements + optional:
        definition = op.get_bind().execute(text('SELECT pg_get_functiondef(to_regprocedure(:signature))'),
                                          {'signature':'public.'+signature}).scalar_one()
        if definition is None and any(signature == candidate[0] for candidate in optional):
            continue
        if not definition or definition.count(original) != 1:
            raise RuntimeError('Team worker integration requires the reviewed function contract: '+signature)
        op.execute(definition.replace(original,replacement))
    if not managed:
        op.execute(f'REVOKE CREATE ON SCHEMA public FROM {owner}')
        op.execute('''DO $$ BEGIN
          IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolsuper) THEN
            EXECUTE format('REVOKE flare_team_executor FROM %I GRANTED BY %I',current_user,current_user);
          END IF;
        END $$;''')


def downgrade():
    raise RuntimeError('Team contains membership and authorship history; use a reviewed restore')
