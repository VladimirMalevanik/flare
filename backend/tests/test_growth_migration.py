import os
import psycopg
import pytest
from app.models.database import database_is_ready


def test_single_head_forced_rls_privileges_and_search_path():
    if not os.getenv('TEST_DATABASE_URL'):pytest.skip('Disposable migrated database required')
    assert database_is_ready(os.environ['DATABASE_URL'])
    with psycopg.connect(os.environ['TEST_DATABASE_URL']) as c:
        assert c.execute('SELECT version_num FROM public.alembic_version').fetchone()==('0020',)
        assert c.execute("SELECT count(*) FROM pg_class WHERE relname IN ('growth_policy','acquisition_visitors','acquisition_budgets','signup_attribution','growth_workspace_optouts','funnel_facts') AND relrowsecurity AND relforcerowsecurity").fetchone()==(6,)
        rows=c.execute("SELECT proname,proconfig,proacl FROM pg_proc WHERE pronamespace='public'::regnamespace AND (proname LIKE 'growth_%' OR proname LIKE 'acquisition_%')").fetchall()
        assert rows
        for name,config,acl in rows:
            assert 'search_path=pg_catalog, public, pg_temp' in config
            assert not any(str(x).startswith('=') for x in acl)
