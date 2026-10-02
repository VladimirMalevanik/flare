"""Durable ZIP onboarding, private checkpoints, publication gate and cleanup."""
import os
from pathlib import Path
from alembic import op

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None


def upgrade():
    owner = 'flare_owner' if os.getenv('FLARE_DATABASE_PROVIDER') == 'yandex' else 'flare_job_executor'
    op.execute(Path(__file__).resolve().parents[2].joinpath('db/import_packages.sql').read_text())
    for table in ('import_packages', 'import_package_entries', 'import_objects', 'import_publications'):
        op.execute(f'''ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON public.{table} FROM PUBLIC,flare_app,flare_worker;
        GRANT SELECT ON public.{table} TO flare_app;
        GRANT SELECT,INSERT,UPDATE,DELETE ON public.{table} TO {owner};
        CREATE POLICY import_member ON public.{table} TO flare_app USING (
          workspace_id=nullif(current_setting('app.workspace_id',true),'')::uuid
          AND EXISTS(SELECT 1 FROM public.workspace_members m WHERE m.workspace_id={table}.workspace_id
            AND m.user_id=nullif(current_setting('app.user_id',true),'')));
        CREATE POLICY import_executor ON public.{table} TO {owner} USING(true) WITH CHECK(true);''')
    # Do not expose private checkpoints or object keys through ordinary API SQL.
    op.execute('REVOKE SELECT ON public.import_objects,public.import_package_entries FROM flare_app')
    op.execute('GRANT SELECT(workspace_id) ON public.import_objects TO flare_app')
    op.execute('GRANT SELECT(workspace_id,package_id,ordinal,path,file_bytes,skip_reason,status,file_hash,document_id,version_id) ON public.import_package_entries TO flare_app')
    op.execute(f'''GRANT USAGE ON SEQUENCE public.import_publications_id_seq TO {owner};
    GRANT SELECT,UPDATE ON public.workspaces TO {owner};
    GRANT SELECT,INSERT,UPDATE,DELETE ON public.documents,public.document_versions,public.chunks TO {owner};''')
    for table in ('documents','document_versions','chunks'):
        op.execute(f'''DROP POLICY executor_member ON public.{table};
        CREATE POLICY executor_member ON public.{table} AS RESTRICTIVE TO {owner} USING (
         current_setting('app.import_cleanup',true)='true' OR EXISTS(SELECT 1 FROM public.workspace_members m
          WHERE m.workspace_id={table}.workspace_id AND m.user_id=nullif(current_setting('app.user_id',true),'') AND m.role IN ('owner','editor')));''')
    for signature,role in [('import_api(text,uuid,jsonb)','flare_app'),('claim_import_package(integer)','flare_worker'),
        ('import_worker_step(uuid,uuid,bigint,text,jsonb)','flare_worker'),('import_cleanup(text,uuid,text)','flare_worker')]:
        # 0018 correctly preserves non-CREATE executor grants; transfer while the
        # migration owner temporarily grants only CREATE, then revoke immediately.
        if owner != 'flare_owner':
            op.execute(f'GRANT CREATE ON SCHEMA public TO {owner}')
            op.execute(f'ALTER FUNCTION public.{signature} OWNER TO {owner}')
            op.execute(f'REVOKE CREATE ON SCHEMA public FROM {owner}')
        op.execute(f'REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC')
        op.execute(f'GRANT EXECUTE ON FUNCTION public.{signature} TO {role}')


def downgrade():
    raise RuntimeError('0019 contains published immutable source provenance; restore a backup instead')
