"""Bounded temporary PostgreSQL ZIP staging and private consumer health."""
import os
from pathlib import Path
from alembic import op

revision = '0022'
down_revision = '0021'
branch_labels = None
depends_on = None

FUNCTIONS = {
    '_import_staging_upload_guard(text,uuid)': (),
    '_import_staging_job_guard(text,uuid,uuid,bigint)': (),
    'import_staging_upload(text,uuid,text,integer,bytea)': ('flare_app',),
    'import_staging_size(text,uuid,uuid,bigint)': ('flare_worker',),
    'import_staging_read(text,uuid,uuid,bigint,integer)': ('flare_worker',),
    'import_staging_retire(text,uuid)': ('flare_worker',),
    'guard_import_staging_seal()': (),
    'guard_import_staging_package_rate()': (),
    'import_staging_heartbeat(text)': ('flare_worker',),
    'import_staging_ready()': ('flare_app',),
    'import_staging_probe()': ('flare_app', 'flare_worker'),
}


def upgrade():
    owner = 'flare_owner' if os.getenv('FLARE_DATABASE_PROVIDER') == 'yandex' else 'flare_job_executor'
    if owner != 'flare_owner':
        op.execute('''DO $$ BEGIN
            IF current_user IN ('flare_app','flare_worker','flare_onboarding') THEN
                RAISE EXCEPTION 'Runtime roles cannot migrate import staging';
            END IF;
            IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='flare_job_executor'
                AND NOT rolcanlogin AND NOT rolsuper AND NOT rolcreatedb AND NOT rolcreaterole
                AND NOT rolinherit AND NOT rolbypassrls)
                OR EXISTS(SELECT 1 FROM pg_auth_members WHERE member='flare_job_executor'::regrole)
                OR EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid='flare_job_executor'::regrole
                    AND (member<>current_user::regrole OR current_user IN ('flare_app','flare_worker','flare_onboarding')))
                OR has_schema_privilege('flare_job_executor','public','CREATE') THEN
                RAISE EXCEPTION 'Unsafe import staging executor';
            END IF;
            PERFORM set_config('app.import_staging_temp_grant','false',true);
            IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=current_user AND rolsuper)
                AND NOT (pg_has_role(current_user,'flare_job_executor','SET')
                         AND pg_has_role(current_user,'flare_job_executor','USAGE')) THEN
                IF NOT EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid='flare_job_executor'::regrole
                    AND member=current_user::regrole AND admin_option)
                    OR EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid='flare_job_executor'::regrole
                        AND member=current_user::regrole AND grantor=current_user::regrole) THEN
                    RAISE EXCEPTION 'Import staging migration requires controlled executor authority';
                END IF;
                -- Separate grantor record. The existing inert creator ADMIN edge
                -- is retained byte-for-byte; failure rolls this transaction back.
                EXECUTE format('GRANT flare_job_executor TO %I WITH ADMIN FALSE, INHERIT TRUE, SET TRUE GRANTED BY %I',current_user,current_user);
                PERFORM set_config('app.import_staging_temp_grant','true',true);
            END IF;
        END $$;''')
    op.execute(Path(__file__).resolve().parents[2].joinpath('db/import_staging.sql').read_text())
    for table in ('import_staging_blocks', 'import_staging_health'):
        op.execute(f'''ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE public.{table} FORCE ROW LEVEL SECURITY;
            REVOKE ALL ON public.{table} FROM PUBLIC,flare_app,flare_worker;
            GRANT SELECT,INSERT,UPDATE,DELETE ON public.{table} TO {owner};
            CREATE POLICY staging_executor ON public.{table} TO {owner} USING(true) WITH CHECK(true);''')
    if owner != 'flare_owner':
        op.execute(f'GRANT CREATE ON SCHEMA public TO {owner}')
    for signature, roles in FUNCTIONS.items():
        op.execute(f'ALTER FUNCTION public.{signature} OWNER TO {owner}')
        op.execute(f'REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC,flare_app,flare_worker')
        for role in roles:
            op.execute(f'GRANT EXECUTE ON FUNCTION public.{signature} TO {role}')
        op.execute(f"ALTER FUNCTION public.{signature} SET statement_timeout='5s'")
        op.execute(f"ALTER FUNCTION public.{signature} SET lock_timeout='2s'")
    if owner != 'flare_owner':
        op.execute(f'REVOKE CREATE ON SCHEMA public FROM {owner}')
        op.execute('''DO $$ BEGIN
            IF current_setting('app.import_staging_temp_grant',true)='true' THEN
                EXECUTE format('REVOKE flare_job_executor FROM %I GRANTED BY %I',current_user,current_user);
            END IF;
        END $$;''')


def downgrade():
    raise RuntimeError('0022 retains permanent import retirement fences; use a reviewed restore')
