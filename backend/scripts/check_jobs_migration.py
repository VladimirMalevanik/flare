"""Verify 0004 -> 0005 using a fresh temporary PostgreSQL cluster (requires pgvector).

From backend/: python scripts/check_jobs_migration.py --pg-bin /path/to/postgresql/bin
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-bin', default='', help='Directory containing initdb, pg_ctl and psql')
    parser.add_argument('--provider', choices=('self-managed', 'yandex'), default='self-managed')
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[1]
    def binary(name):
        return str(Path(args.pg_bin) / name) if args.pg_bin else name
    def run(command, **kwargs):
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, **kwargs)
    with tempfile.TemporaryDirectory(prefix='flare-jobs-upgrade-', dir='/tmp') as root:
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
            run(migrate + ['0004'], env=env)
            wid, doc, version, chunk = [uuid4() for _ in range(4)]
            tables = ('workspaces','workspace_members','documents','document_versions','chunks','auth_users','auth_sessions')
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
                before = snapshot(conn)
            run(migrate + ['0005'], env=env)
            run(migrate + ['0005'], env=env)
            with psycopg.connect(dsn) as conn:
                assert snapshot(conn) == before
                assert conn.execute('SELECT version_num FROM alembic_version').fetchone() == ('0005',)
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
            print(f'PASS ({args.provider}): 0004 -> 0005; seven tables unchanged; repeat upgrade; legacy identity/RLS; enqueue + worker claim')
        finally:
            run([binary('pg_ctl'), '-D', data, '-m', 'fast', '-w', 'stop'])


if __name__ == '__main__':
    main()
