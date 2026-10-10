import os
import psycopg
import pytest
from app.models.database import CURRENT_SCHEMA_REVISION, _connection_is_ready, database_is_ready


def test_single_head_forced_rls_privileges_and_search_path():
    if not os.getenv('TEST_DATABASE_URL'):pytest.skip('Disposable migrated database required')
    assert database_is_ready(os.environ['DATABASE_URL'])
    with psycopg.connect(os.environ['TEST_DATABASE_URL']) as c:
        assert c.execute('SELECT version_num FROM public.alembic_version').fetchone()==(CURRENT_SCHEMA_REVISION,)
        assert c.execute("SELECT count(*) FROM pg_class WHERE relname IN ('growth_policy','acquisition_visitors','acquisition_budgets','signup_attribution','growth_workspace_optouts','funnel_facts') AND relrowsecurity AND relforcerowsecurity").fetchone()==(6,)
        rows=c.execute("SELECT proname,proconfig,proacl FROM pg_proc WHERE pronamespace='public'::regnamespace AND (proname LIKE 'growth_%' OR proname LIKE 'acquisition_%')").fetchall()
        assert rows
        for name,config,acl in rows:
            assert 'search_path=pg_catalog, public, pg_temp' in config
            assert not any(str(x).startswith('=') for x in acl)



def test_legacy_actor_fk_is_unvalidated_but_enforces_new_rows():
    if not os.getenv('TEST_DATABASE_URL'): pytest.skip('Disposable migrated database required')
    from uuid import uuid4
    with psycopg.connect(os.environ['TEST_DATABASE_URL']) as c:
        assert c.execute("SELECT convalidated,confdeltype FROM pg_constraint WHERE conrelid='public.activity_events'::regclass AND conname='growth_activity_actor_fk'").fetchone()==(False,'c')
        assert not c.execute("SELECT has_function_privilege('flare_app','public.growth_observation_allowed(uuid,text)','EXECUTE')").fetchone()[0]
        wid=uuid4()
        c.execute("INSERT INTO public.workspaces(id,name) VALUES(%s,'Synthetic')",(wid,))
        # Independently verify the FK safety net, rather than only its BEFORE
        # guard. The test-only trigger change and all rows are rolled back.
        c.execute('ALTER TABLE public.activity_events DISABLE TRIGGER growth_event_privacy')
        with pytest.raises(psycopg.errors.ForeignKeyViolation),c.transaction():
            c.execute("INSERT INTO public.activity_events(workspace_id,actor_id,event_type,target_type) VALUES(%s,%s,'capture_started','capture')",(wid,'synthetic-absent|'+uuid4().hex))
        c.rollback()


@pytest.mark.parametrize("corruption", [
    "GRANT SELECT(key) ON public.import_staging_blocks TO flare_app",
    "GRANT SELECT(data) ON public.import_staging_blocks TO flare_worker",
    "ALTER TABLE public.import_staging_health NO FORCE ROW LEVEL SECURITY",
    "GRANT EXECUTE ON FUNCTION public.import_staging_read(text,uuid,uuid,bigint,integer) TO flare_app",
    "GRANT EXECUTE ON FUNCTION public.import_staging_upload(text,uuid,text,integer,bytea) TO PUBLIC",
    "ALTER FUNCTION public.import_staging_probe() RESET ALL",
])
def test_readiness_rejects_exposed_staging_bytes_or_capabilities(corruption):
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("Disposable migrated database required")
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        try:
            connection.execute(corruption)
            connection.execute("SET LOCAL ROLE flare_app")
            assert _connection_is_ready(connection) is False
        finally:
            # Fixture-only DDL and grants must never escape the test transaction.
            connection.rollback()
