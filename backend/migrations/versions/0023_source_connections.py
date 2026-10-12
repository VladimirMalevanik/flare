"""Selected read-only sources with protected credentials and bounded jobs."""
import os
from pathlib import Path
from alembic import op

revision = '0023'
down_revision = '0022'
branch_labels = None
depends_on = None


def upgrade():
    owner = 'flare_owner' if os.getenv('FLARE_DATABASE_PROVIDER') == 'yandex' else 'flare_job_executor'
    op.execute(Path(__file__).resolve().parents[2].joinpath('db/source_connections.sql').read_text())
    for table in ('source_connections', 'source_auth_states', 'source_jobs', 'source_items'):
        op.execute(f'''ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON public.{table} FROM PUBLIC,flare_app,flare_worker;
        GRANT SELECT(workspace_id) ON public.{table} TO flare_app;
        GRANT SELECT,INSERT,UPDATE,DELETE ON public.{table} TO {owner};
        CREATE POLICY source_member ON public.{table} TO flare_app USING (
          workspace_id=nullif(current_setting('app.workspace_id',true),'')::uuid
          AND EXISTS(SELECT 1 FROM public.workspace_members m WHERE m.workspace_id={table}.workspace_id
            AND m.user_id=nullif(current_setting('app.user_id',true),'')));
        CREATE POLICY source_executor ON public.{table} TO {owner} USING(true) WITH CHECK(true);''')
    op.execute(f'''GRANT SELECT,UPDATE(connected_at) ON public.github_connections TO {owner};
    CREATE POLICY source_github_executor ON public.github_connections TO {owner} USING (
      workspace_id=nullif(current_setting('app.workspace_id',true),'')::uuid
      AND EXISTS(SELECT 1 FROM public.workspace_members m WHERE m.workspace_id=github_connections.workspace_id
        AND m.user_id=nullif(current_setting('app.user_id',true),'') AND m.role IN ('owner','editor')));
    GRANT SELECT,INSERT,UPDATE ON public.documents,public.document_versions,public.chunks TO {owner};''')
    op.execute(f'''ALTER TABLE public.source_worker_health ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.source_worker_health FORCE ROW LEVEL SECURITY;
    REVOKE ALL ON public.source_worker_health FROM PUBLIC,flare_app,flare_worker;
    GRANT SELECT,INSERT,UPDATE ON public.source_worker_health TO {owner};
    CREATE POLICY source_health_executor ON public.source_worker_health TO {owner} USING(true) WITH CHECK(true);''')
    for signature, role in [('source_api(text,uuid,jsonb)','flare_app'),('claim_source_job(text[],integer)','flare_worker'),
                            ('source_worker_step(uuid,uuid,bigint,text,jsonb)','flare_worker')]:
        if owner != 'flare_owner':
            op.execute(f'GRANT CREATE ON SCHEMA public TO {owner}')
            op.execute(f'ALTER FUNCTION public.{signature} OWNER TO {owner}')
            op.execute(f'REVOKE CREATE ON SCHEMA public FROM {owner}')
        op.execute(f'REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC')
        op.execute(f'GRANT EXECUTE ON FUNCTION public.{signature} TO {role}')


def downgrade():
    raise RuntimeError('0023 retains immutable imported source provenance; restore a verified backup instead')
