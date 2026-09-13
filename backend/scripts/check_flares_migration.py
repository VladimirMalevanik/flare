"""Verify 0005 -> 0006 using a fresh temporary PostgreSQL cluster (requires pgvector).

From backend/: python scripts/check_flares_migration.py --pg-bin /path/to/postgresql/bin
Never connects to an existing database; requires a non-root OS user for initdb.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from uuid import uuid4

import psycopg
from psycopg.conninfo import make_conninfo


def main(*, verify_analysis_runs=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-bin', default='', help='Directory containing initdb, pg_ctl and psql')
    parser.add_argument('--provider', choices=('self-managed', 'yandex'), default='self-managed')
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[1]
    def binary(name):
        return str(Path(args.pg_bin) / name) if args.pg_bin else name
    def run(command, **kwargs):
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, **kwargs)
    with tempfile.TemporaryDirectory(prefix='flare-flares-upgrade-', dir='/tmp') as root:
        data = str(Path(root) / 'data')
        run([binary('initdb'), '-D', data, '-U', 'flare_upgrade_admin', '--auth=trust', '--encoding=UTF8', '--no-locale'])
        # Unix socket only, unique directory: no listening TCP port or existing DB.
        run([binary('pg_ctl'), '-D', data, '-l', str(Path(root)/'server.log'),
             '-o', f"-h '' -k {root}", '-w', 'start'])
        try:
            dsn = make_conninfo(host=root, dbname='postgres', user='flare_upgrade_admin')
            owner = 'flare_owner' if args.provider == 'yandex' else 'flare_upgrade_admin'
            env = {**os.environ, 'FLARE_DATABASE_PROVIDER': args.provider,
                   'OWNER_PASSWORD': 'migration-test-only', 'APP_PASSWORD': 'migration-test-only',
                   'WORKER_PASSWORD': 'migration-test-only',
                   'MIGRATION_DATABASE_URL': f'postgresql+psycopg://{owner}@/postgres?host={root}'}
            # Only the disposable cluster is selected, never an ambient dotenv file.
            env.pop('FLARE_DOTENV_PATH', None)
            env['PYTHON_DOTENV_DISABLED'] = '1'
            bootstrap = 'provision-yandex-test.sql' if args.provider == 'yandex' else 'init-role.sql'
            run([binary('psql'), dsn, '-v', 'ON_ERROR_STOP=1', '-f', str(backend/'db'/bootstrap)], env=env)
            migrate = [sys.executable, '-m', 'alembic', '-c', str(backend/'alembic.ini'), 'upgrade']
            run(migrate + ['0005'], env=env)
            wid, doc, version, chunk = [uuid4() for _ in range(4)]
            tables = ('workspaces','workspace_members','documents','document_versions','chunks','auth_users','auth_sessions','insights','insight_sources','analysis_jobs','analysis_job_sources')
            def snapshot(conn):
                return [conn.execute(f'SELECT to_jsonb(t) FROM public.{table} t ORDER BY to_jsonb(t)::text').fetchall() for table in tables]
            with psycopg.connect(dsn) as conn:
                conn.execute("INSERT INTO workspaces(id,name) VALUES (%s,'Legacy workspace')", (wid,))
                conn.execute("INSERT INTO workspace_members(workspace_id,user_id,role) VALUES (%s,'legacy|string-owner','owner')", (wid,))
                conn.execute("INSERT INTO auth_users(id,email,password_hash,name,initial_workspace_id) VALUES ('legacy|string-owner','migration@test.invalid','unused-test-hash','Migration',%s)", (wid,))
                conn.execute("INSERT INTO auth_sessions(token_hash,user_id,workspace_id,expires_at) VALUES (%s,'legacy|string-owner',%s,now()+interval '1 day')", ('a'*64,wid))
                conn.execute("INSERT INTO documents(id,workspace_id,title,source_type) VALUES (%s,%s,'Legacy note','note')", (doc,wid))
                conn.execute("INSERT INTO document_versions(id,workspace_id,document_id,version_number,content_hash,parser_version,state) VALUES (%s,%s,%s,1,%s,'manual-note-v1','processing')", (version,wid,doc,'b'*64))
                conn.execute("INSERT INTO chunks(id,workspace_id,document_version_id,ordinal,content,locator) VALUES (%s,%s,%s,0,'Saved evidence','{}')", (chunk,wid,version))
                conn.execute("UPDATE document_versions SET state='ready' WHERE id=%s", (version,))
                conn.execute('UPDATE documents SET current_version_id=%s WHERE id=%s', (version,doc))
                legacy=uuid4()
                conn.execute("INSERT INTO insights(id,workspace_id,title,summary,body,model,prompt_version) VALUES(%s,%s,'Legacy','Legacy','Legacy','old','old')", (legacy,wid))
                conn.execute('INSERT INTO insight_sources(workspace_id,insight_id,chunk_id) VALUES(%s,%s,%s)',(wid,legacy,chunk))
                conn.execute('SET LOCAL ROLE flare_app')
                conn.execute("SELECT set_config('app.workspace_id',%s,true),set_config('app.user_id','legacy|string-owner',true)",(str(wid),))
                parent=conn.execute("SELECT public.enqueue_analysis_job(%s,'historical',3)",([chunk],)).fetchone()[0]
                conn.execute('RESET ROLE')
                conn.execute('SET LOCAL ROLE flare_worker')
                claim=conn.execute('SELECT job_id,lease_token FROM public.claim_analysis_job(%s,120)',(uuid4(),)).fetchone()
                conn.execute("SELECT public.finish_analysis_job(%s,%s,'{\"observations\":[]}','{}',NULL,NULL)",claim)
                conn.execute('RESET ROLE')
                before = snapshot(conn)
            run(migrate + ['0006'], env=env)
            run(migrate + ['0006'], env=env)
            with psycopg.connect(dsn) as conn:
                after = snapshot(conn)
                # New nullable columns on legacy insights/sources are additive.
                for old_rows,new_rows in zip(before,after):
                    assert len(old_rows)==len(new_rows)
                    for (old,),(new,) in zip(old_rows,new_rows):
                        assert all(new[k]==v for k,v in old.items())
                assert conn.execute('SELECT version_num FROM alembic_version').fetchone() == ('0006',)
                executor = 'flare_owner' if args.provider == 'yandex' else 'flare_job_executor'
                owners = conn.execute("""SELECT DISTINCT pg_get_userbyid(proowner)
                    FROM pg_proc WHERE pronamespace='public'::regnamespace
                    AND proname LIKE '%flare_generation%'""").fetchall()
                assert owners == [(executor,)]
                if args.provider == 'yandex':
                    assert conn.execute("SELECT count(*) FROM pg_roles WHERE rolname='flare_job_executor'").fetchone() == (0,)

                conn.execute('SET LOCAL ROLE flare_app')
                conn.execute("SELECT set_config('app.workspace_id',%s,true),set_config('app.user_id','legacy|string-owner',true)", (str(wid),))
                assert conn.execute('SELECT content FROM chunks').fetchall() == [('Saved evidence',)]
                job = conn.execute("SELECT public.enqueue_analysis_job(%s,'upgrade-test',3)", ([chunk],)).fetchone()[0]
                conn.execute("SELECT set_config('app.user_id','foreign-user',true)")
                assert conn.execute('SELECT * FROM analysis_jobs').fetchall() == []
                assert conn.execute('SELECT * FROM chunks').fetchall() == []
                conn.execute('RESET ROLE')
                conn.execute('SET LOCAL ROLE flare_worker')
                claim = conn.execute('SELECT job_id FROM public.claim_analysis_job(%s,120)', (uuid4(),)).fetchone()
                assert claim == (job,)
                run_id=conn.execute("SELECT public.enqueue_flare_generation(%s,'upgrade-test',3)",(parent,)).fetchone()[0]
                assert conn.execute("SELECT public.enqueue_flare_generation(%s,'upgrade-test',3)",(parent,)).fetchone()==(run_id,)
                token=conn.execute('SELECT lease_token FROM public.claim_analysis_job(%s,120)',(uuid4(),)).fetchone()
                # Previous claim already owns the fresh job; use its token as admin for the handoff check.
                conn.execute('RESET ROLE')
                token=conn.execute('SELECT lease_token FROM analysis_jobs WHERE id=%s',(job,)).fetchone()[0]
                conn.execute('SET LOCAL ROLE flare_worker')
                conn.execute("SELECT public.finish_analysis_job(%s,%s,'{\"observations\":[]}','{}',NULL,NULL)",(job,token))
                conn.execute('RESET ROLE')
                assert conn.execute('SELECT count(*) FROM flare_generation_runs WHERE analysis_job_id=%s',(job,)).fetchone()==(1,)
            if verify_analysis_runs:
                tables += ('flare_generation_runs',)
                with psycopg.connect(dsn) as conn:
                    preserved = snapshot(conn)
                run(migrate + ['0007'], env=env)
                run(migrate + ['0007'], env=env)
                with psycopg.connect(dsn) as conn:
                    assert snapshot(conn) == preserved
                    assert conn.execute('SELECT version_num FROM alembic_version').fetchone() == ('0007',)
                    assert conn.execute('SELECT count(*) FROM analysis_runs').fetchone() == (0,)
                    owners = conn.execute("SELECT DISTINCT pg_get_userbyid(proowner) FROM pg_proc WHERE proname IN ('start_analysis_run','read_analysis_run')").fetchall()
                    assert owners == [(executor,)]
                    assert not conn.execute("SELECT has_table_privilege('flare_worker','analysis_runs','SELECT')").fetchone()[0]
                print(f'PASS ({args.provider}): 0006 -> 0007; all existing data preserved; repeat upgrade; capability ownership; worker isolation')
                tables += ('analysis_runs',)
                with psycopg.connect(dsn) as conn:
                    preserved = snapshot(conn)
                run(migrate + ['head'], env=env)
                run(migrate + ['head'], env=env)
                with psycopg.connect(dsn) as conn:
                    assert snapshot(conn) == preserved
                    assert conn.execute('SELECT version_num FROM alembic_version').fetchone() == ('0009',)
                    assert conn.execute('SELECT count(*) FROM github_connection_states').fetchone() == (0,)
                    assert conn.execute('SELECT count(*) FROM github_connections').fetchone() == (0,)
                    protected = conn.execute("""SELECT count(*) FROM pg_class
                        WHERE relname IN ('github_connection_states','github_connections')
                        AND relrowsecurity AND relforcerowsecurity""").fetchone()
                    assert protected == (2,)
                    assert not conn.execute(
                        "SELECT has_table_privilege('flare_worker','github_connections','SELECT')"
                    ).fetchone()[0]
                print(f'PASS ({args.provider}): 0007 -> 0009; all existing data preserved; repeat upgrade; email backfill; GitHub RLS; worker isolation')
            print(f'PASS ({args.provider}): 0005 -> 0006; eleven tables preserved; historical ordinals preserved; repeat startup; legacy identity/RLS; old-parent enqueue; atomic handoff')
        finally:
            run([binary('pg_ctl'), '-D', data, '-m', 'fast', '-w', 'stop'])


if __name__ == '__main__':
    main()
