"""Bounded collaborative projects, invitations and tasks; capability defaults off."""
import os
from pathlib import Path
from alembic import op

revision = '0024'
# DATA-003/0023 is an independent unmerged PR. Rebase this parent to0023 when
# that PR lands; the combined migration lineage is explicitly tested in review.
down_revision = '0022'
branch_labels = None
depends_on = None

FUNCTIONS = {
 '_team_actor()': False, '_team_paid(uuid)': False, '_team_guard(uuid,text)': False,
 'team_projects_list()': True, 'team_capability()': True,
 'team_project_create(uuid,text)': True, 'team_members_list(uuid)': True,
 'team_invite(uuid,text,text,text)': True, 'team_invitations_list(uuid)': True,
 'team_invitation_cancel(uuid,uuid)': True, 'team_invitation_accept(text)': True,
 'team_membership_change(uuid,text,text,text)': True,
 'team_tasks_list(uuid,timestamptz,uuid)': True,
 'team_task_write(uuid,uuid,integer,jsonb,boolean)': True,
 'team_task_history_list(uuid,uuid)': True, 'team_license_snapshots(uuid)': True, 'guard_team_content()': False,
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
      GRANT UPDATE(status) ON public.billing_subscriptions TO {owner};
      GRANT SELECT,UPDATE(updated_by_user_id) ON public.analysis_schedules TO {owner};''')
    if not managed:
        for table in ('workspaces','workspace_members','billing_subscriptions','documents','chunks','analysis_schedules'):
            op.execute(f'CREATE POLICY team_executor_access ON public.{table} TO {owner} USING(true) WITH CHECK(true)')
        op.execute(f'GRANT CREATE ON SCHEMA public TO {owner}')
    for signature, public in FUNCTIONS.items():
        op.execute(f'ALTER FUNCTION public.{signature} OWNER TO {owner}')
        op.execute(f'REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC,flare_app,flare_worker')
        if public:
            op.execute(f'GRANT EXECUTE ON FUNCTION public.{signature} TO flare_app')
        op.execute(f"ALTER FUNCTION public.{signature} SET statement_timeout='5s'")
        op.execute(f"ALTER FUNCTION public.{signature} SET lock_timeout='2s'")
    for table in ('documents','document_versions','chunks'):
        op.execute(f'''CREATE TRIGGER team_content_guard BEFORE INSERT OR UPDATE OR DELETE ON public.{table}
          FOR EACH ROW EXECUTE FUNCTION public.guard_team_content()''')
    op.execute('''CREATE TRIGGER team_analysis_admission BEFORE INSERT ON public.analysis_jobs
      FOR EACH ROW EXECUTE FUNCTION public.guard_team_content()''')
    if not managed:
        op.execute(f'REVOKE CREATE ON SCHEMA public FROM {owner}')
        op.execute('''DO $$ BEGIN
          IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolsuper) THEN
            EXECUTE format('REVOKE flare_team_executor FROM %I GRANTED BY %I',current_user,current_user);
          END IF;
        END $$;''')


def downgrade():
    raise RuntimeError('Team contains membership and authorship history; use a reviewed restore')
