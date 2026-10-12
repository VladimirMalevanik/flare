"""Read-only exact migration and restricted capability validation (synthetic CI)."""
import os
from pathlib import Path
import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.models.database import CURRENT_SCHEMA_REVISION, database_is_ready


def main():
    root=Path(__file__).resolve().parents[1]
    cfg=Config(str(root/'alembic.ini'))
    assert ScriptDirectory.from_config(cfg).get_heads()==[CURRENT_SCHEMA_REVISION]
    assert database_is_ready(os.environ['DATABASE_URL'])
    with psycopg.connect(os.environ['TEST_DATABASE_URL']) as c:
        assert c.execute('SELECT version_num FROM public.alembic_version').fetchone()==(CURRENT_SCHEMA_REVISION,)
        for role in ('flare_app','flare_worker'):
            for table in ('signup_attribution','acquisition_visitors','funnel_facts'):
                assert not c.execute('SELECT has_table_privilege(%s,%s,%s)',(role,'public.'+table,'SELECT,INSERT,UPDATE,DELETE')).fetchone()[0]
            assert not c.execute("SELECT has_function_privilege(%s,'public.growth_report(timestamptz,timestamptz,text,text)','EXECUTE')",(role,)).fetchone()[0]
    print(f'single head {CURRENT_SCHEMA_REVISION}; runtime ready; app/worker private facts and reporting denied')

if __name__=='__main__':main()
