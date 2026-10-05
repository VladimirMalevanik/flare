"""Exercise 0021 with a real PG17 NOSUPERUSER CREATEROLE migration login.

Fresh Unix-socket-only cluster; never uses ambient database URLs or dotenv.
From backend/: python scripts/check_billing_restricted_admin.py --pg-bin /path/to/bin
Add --billing-tests to exercise billing security/lifecycle on this schema.
"""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo


class DatabaseOp:
    def __init__(self, connection, fail_after_owner=False):
        self.connection = connection
        self.fail_after_owner = fail_after_owner

    def execute(self, statement):
        self.connection.execute(statement)
        if self.fail_after_owner and statement.startswith('ALTER FUNCTION') and ' OWNER TO ' in statement:
            raise RuntimeError('Injected failure after ownership transfer')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pg-bin', default='')
    parser.add_argument('--billing-tests', action='store_true')
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('billing_migration', backend/'migrations/versions/0021_paddle_billing.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    checks = 0

    def binary(name):
        return str(Path(args.pg_bin)/name) if args.pg_bin else name

    def run(command, **kwargs):
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, **kwargs)

    with tempfile.TemporaryDirectory(prefix='flare-billing-restricted-', dir='/tmp') as root:
        data = str(Path(root)/'data')
        run([binary('initdb'), '-D', data, '-U', 'fixture_bootstrap', '--auth=trust', '--encoding=UTF8', '--no-locale'])
        run([binary('pg_ctl'), '-D', data, '-l', str(Path(root)/'server.log'), '-o', f"-h '' -k {root}", '-w', 'start'])
        try:
            bootstrap = make_conninfo(host=root, dbname='postgres', user='fixture_bootstrap')
            admin = make_conninfo(host=root, dbname='postgres', user='flare_admin')
            env = {**os.environ, 'PYTHONPATH': str(backend), 'PYTHON_DOTENV_DISABLED': '1',
                'FLARE_ENV': 'test', 'FLARE_PROCESS_ROLE': 'migration', 'FLARE_DATABASE_PROVIDER': 'self-managed',
                'APP_PASSWORD': 'disposable-test-only',
                'MIGRATION_DATABASE_URL': f'postgresql+psycopg://fixture_bootstrap@/postgres?host={root}'}
            env.pop('FLARE_DOTENV_PATH', None)
            # Bootstrap prepares only the existing0018 baseline. All new
            # migration DDL uses an actual restricted login connection.
            run([binary('psql'), bootstrap, '-v', 'ON_ERROR_STOP=1', '-f', str(backend/'db/init-role.sql')], env=env)
            migrate = [sys.executable, '-m', 'alembic', '-c', str(backend/'alembic.ini'), 'upgrade']
            run(migrate+['0018'], env=env, cwd=backend)
            with psycopg.connect(bootstrap) as connection:
                assert int(connection.execute('SHOW server_version_num').fetchone()[0])//10000 == 17
                connection.execute('CREATE ROLE flare_admin LOGIN NOSUPERUSER NOCREATEDB CREATEROLE INHERIT NOBYPASSRLS')
                connection.execute('GRANT USAGE,CREATE ON SCHEMA public TO flare_admin WITH GRANT OPTION')
                # Models existing administrative rights over the legacy executor,
                # not a grant to runtime users. Azure also has provider-specific
                # administrator capabilities which this vanilla fixture lacks.
                connection.execute('GRANT flare_job_executor TO flare_admin WITH ADMIN TRUE,INHERIT TRUE,SET TRUE')
                for name, kind in connection.execute("SELECT relname,relkind FROM pg_class WHERE relnamespace='public'::regnamespace AND relkind IN('r','S')").fetchall():
                    connection.execute(sql.SQL('ALTER {} {} OWNER TO flare_admin').format(
                        sql.SQL('SEQUENCE' if kind == 'S' else 'TABLE'), sql.Identifier('public', name)))
                for (signature,) in connection.execute("""SELECT oid::regprocedure::text FROM pg_proc
                    WHERE pronamespace='public'::regnamespace AND proowner='fixture_bootstrap'::regrole
                    AND NOT EXISTS(SELECT 1 FROM pg_depend WHERE objid=pg_proc.oid AND deptype='e')""").fetchall():
                    connection.execute(sql.SQL('ALTER FUNCTION {} OWNER TO flare_admin').format(sql.SQL(signature)))
            env['MIGRATION_DATABASE_URL'] = f'postgresql+psycopg://flare_admin@/postgres?host={root}'
            run(migrate+['0020'], env=env, cwd=backend)
            os.environ['FLARE_DATABASE_PROVIDER'] = 'self-managed'

            def no_billing():
                with psycopg.connect(bootstrap) as connection:
                    assert connection.execute('SELECT version_num FROM alembic_version').fetchone() == ('0020',)
                    assert all(connection.execute('SELECT to_regclass(%s)', ('public.'+table,)).fetchone() == (None,) for table in migration.TABLES)
                    assert connection.execute("SELECT count(*) FROM pg_proc WHERE proname IN('create_billing_checkout_intent','apply_paddle_billing_event','_apply_paddle_billing_event')").fetchone() == (0,)

            def safe_result(connection, *, expected_bypass=False):
                nonlocal checks
                assert connection.execute("SELECT rolsuper,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone() == (False,True,expected_bypass)
                assert connection.execute('SELECT '+migration.SAFE_EXECUTOR).fetchone() == (True,)
                assert connection.execute("SELECT pg_has_role(current_user,'flare_billing_executor','SET'),pg_has_role(current_user,'flare_billing_executor','USAGE')").fetchone() == (False,False)
                assert connection.execute("""SELECT grantor,admin_option,inherit_option,set_option FROM pg_auth_members
                    WHERE roleid='flare_billing_executor'::regrole""").fetchall() == [(10,True,False,False)]
                assert connection.execute("SELECT has_schema_privilege('flare_billing_executor','public','CREATE')").fetchone() == (False,)
                assert connection.execute("""SELECT count(*) FROM pg_proc WHERE oid IN(
                    'public.create_billing_checkout_intent(text,text,integer)'::regprocedure,
                    'public.apply_paddle_billing_event(jsonb)'::regprocedure,
                    'public._apply_paddle_billing_event(jsonb)'::regprocedure)
                    AND proowner='flare_billing_executor'::regrole AND prosecdef""").fetchone() == (3,)
                checks += 1

            for setting in ('', 'set', 'inherit', 'set,inherit'):
                with psycopg.connect(admin) as connection:
                    connection.execute("SELECT set_config('createrole_self_grant',%s,true)", (setting,))
                    migration.op = DatabaseOp(connection)
                    migration.upgrade()
                    safe_result(connection)
                    assert connection.execute('SHOW createrole_self_grant').fetchone() == (setting,)
                    connection.rollback()
                no_billing()

            with psycopg.connect(admin) as connection:
                migration.op = DatabaseOp(connection, fail_after_owner=True)
                try:
                    migration.upgrade()
                except RuntimeError as error:
                    assert 'Injected failure' in str(error)
                    connection.rollback()
                else:
                    raise AssertionError('Injected owner-transfer failure was not raised')
            no_billing()
            with psycopg.connect(bootstrap) as connection:
                assert connection.execute("SELECT to_regrole('flare_billing_executor')").fetchone() == (None,)
            checks += 1

            # Reuse a role genuinely created by this restricted administrator.
            # Its automatic ADMIN-only parent must survive success and rollback.
            with psycopg.connect(admin) as connection:
                connection.execute('CREATE ROLE flare_billing_executor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS')
            with psycopg.connect(admin) as connection:
                migration.op = DatabaseOp(connection)
                migration.upgrade()
                safe_result(connection)
                connection.rollback()
            with psycopg.connect(admin) as connection:
                migration.op = DatabaseOp(connection, fail_after_owner=True)
                try:
                    migration.upgrade()
                except RuntimeError:
                    connection.rollback()
                else:
                    raise AssertionError('Existing-role failure not injected')
            no_billing()
            with psycopg.connect(admin) as connection:
                assert connection.execute("SELECT grantor,admin_option,inherit_option,set_option FROM pg_auth_members WHERE roleid='flare_billing_executor'::regrole").fetchall() == [(10,True,False,False)]
                assert connection.execute("SELECT pg_has_role(current_user,'flare_billing_executor','SET'),pg_has_role(current_user,'flare_billing_executor','USAGE')").fetchone() == (False,False)
                connection.execute('DROP ROLE flare_billing_executor')
            checks += 1

            unsafe = [
                ('memberless existing executor', []),
                *[(flag, [f'ALTER ROLE flare_billing_executor {flag}']) for flag in
                    ('LOGIN','SUPERUSER','CREATEDB','CREATEROLE','INHERIT','BYPASSRLS')],
                ('outgoing membership', ['CREATE ROLE foreign_role', 'GRANT foreign_role TO flare_billing_executor']),
                ('runtime incoming membership', ['GRANT flare_billing_executor TO flare_app']),
                ('foreign inert incoming edge', ['CREATE ROLE foreign_role', 'GRANT flare_billing_executor TO foreign_role WITH ADMIN TRUE,INHERIT FALSE,SET FALSE']),
                ('effective bootstrap creator edge', ['GRANT flare_billing_executor TO flare_admin WITH ADMIN TRUE,INHERIT TRUE,SET TRUE']),
                ('non-admin bootstrap creator edge', ['GRANT flare_billing_executor TO flare_admin WITH ADMIN FALSE,INHERIT FALSE,SET FALSE']),
            ]
            unsafe = [(label, statements, False, []) for label, statements in unsafe] + [
                ('creator plus foreign member', ['CREATE ROLE foreign_role', 'GRANT flare_billing_executor TO foreign_role WITH ADMIN TRUE,INHERIT FALSE,SET FALSE'], True, []),
                ('creator plus self-granted inert edge', [], True, ['GRANT flare_billing_executor TO flare_admin WITH ADMIN FALSE,INHERIT FALSE,SET FALSE GRANTED BY flare_admin']),
                ('creator plus self-granted effective edge', [], True, ['GRANT flare_billing_executor TO flare_admin WITH ADMIN FALSE,INHERIT TRUE,SET TRUE GRANTED BY flare_admin']),
            ]
            for label, statements, created_by_admin, own_grants in unsafe:
                with psycopg.connect(admin if created_by_admin else bootstrap) as connection:
                    connection.execute('CREATE ROLE flare_billing_executor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS')
                    for statement in own_grants:
                        connection.execute(statement)
                with psycopg.connect(bootstrap) as connection:
                    for statement in statements:
                        connection.execute(statement)
                    before = connection.execute("SELECT to_jsonb(r) FROM pg_roles r WHERE rolname='flare_billing_executor'").fetchone()
                    members = connection.execute("SELECT to_jsonb(m) FROM pg_auth_members m WHERE roleid='flare_billing_executor'::regrole OR member='flare_billing_executor'::regrole ORDER BY to_jsonb(m)::text").fetchall()
                with psycopg.connect(admin) as connection:
                    migration.op = DatabaseOp(connection)
                    try:
                        migration.upgrade()
                    except psycopg.Error as error:
                        assert 'Unsafe billing executor role' in str(error) or 'requires executor administrative authority' in str(error), (label, str(error))
                        connection.rollback()
                    else:
                        raise AssertionError(f'Unsafe role accepted: {label}')
                no_billing()
                with psycopg.connect(bootstrap) as connection:
                    assert connection.execute("SELECT to_jsonb(r) FROM pg_roles r WHERE rolname='flare_billing_executor'").fetchone() == before
                    assert connection.execute("SELECT to_jsonb(m) FROM pg_auth_members m WHERE roleid='flare_billing_executor'::regrole OR member='flare_billing_executor'::regrole ORDER BY to_jsonb(m)::text").fetchall() == members
                    connection.execute('DROP ROLE flare_billing_executor')
                    connection.execute('DROP ROLE IF EXISTS foreign_role')
                checks += 1

            # Runtime/registration principals stay forbidden even after
            # accidental LOGIN and CREATEROLE elevation in this fixture.
            for role in ('flare_app', 'flare_worker', 'flare_onboarding'):
                with psycopg.connect(bootstrap) as connection:
                    connection.execute(sql.SQL('ALTER ROLE {} LOGIN CREATEROLE').format(sql.Identifier(role)))
                with psycopg.connect(make_conninfo(host=root, dbname='postgres', user=role)) as connection:
                    migration.op = DatabaseOp(connection)
                    try:
                        migration.upgrade()
                    except psycopg.Error as error:
                        assert 'Runtime roles cannot migrate billing' in str(error)
                        connection.rollback()
                    else:
                        raise AssertionError('Runtime migration accepted')
                no_billing()
                with psycopg.connect(bootstrap) as connection:
                    connection.execute(sql.SQL('ALTER ROLE {} {} NOCREATEROLE').format(
                        sql.Identifier(role), sql.SQL('NOLOGIN' if role == 'flare_onboarding' else 'LOGIN')))
                    assert connection.execute("SELECT to_regrole('flare_billing_executor')").fetchone() == (None,)
                checks += 1

            # Actual Azure administrators may already have BYPASSRLS. Preserve
            # that existing trusted authority; never copy it to the executor.
            with psycopg.connect(bootstrap) as connection:
                connection.execute('ALTER ROLE flare_admin BYPASSRLS')
            with psycopg.connect(admin) as connection:
                migration.op = DatabaseOp(connection)
                migration.upgrade()
                safe_result(connection, expected_bypass=True)
                connection.rollback()
            with psycopg.connect(bootstrap) as connection:
                connection.execute('ALTER ROLE flare_admin NOBYPASSRLS')

            run(migrate+['head'], env=env, cwd=backend)
            run(migrate+['head'], env=env, cwd=backend)
            with psycopg.connect(admin) as connection:
                safe_result(connection)
                assert connection.execute('SELECT version_num FROM alembic_version').fetchone() == ('0021',)
            with psycopg.connect(bootstrap) as connection:
                for table in migration.TABLES:
                    assert connection.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass', ('public.'+table,)).fetchone() == (True,True)
                assert connection.execute("SELECT has_table_privilege('flare_app','billing_webhook_events','SELECT,INSERT,UPDATE,DELETE')").fetchone() == (False,)
                assert connection.execute("SELECT has_function_privilege('flare_app','public._apply_paddle_billing_event(jsonb)','EXECUTE')").fetchone() == (False,)
                for role in ('flare_app','flare_worker','flare_onboarding'):
                    assert connection.execute("SELECT pg_has_role(%s,'flare_billing_executor','SET'),pg_has_role(%s,'flare_billing_executor','USAGE')", (role,role)).fetchone() == (False,False)
            checks += 1
            print(f'PASS: {checks} PG17 restricted-admin migration/cleanup/rejection/rollback cases;0018→0021 and repeat upgrade; no runtime role expansion', flush=True)
            if args.billing_tests:
                env.update(DATABASE_URL=f'postgresql://flare_app@/postgres?host={root}',
                    TEST_DATABASE_URL=f'postgresql://fixture_bootstrap@/postgres?host={root}',
                    WORKER_DATABASE_URL=f'postgresql://flare_worker@/postgres?host={root}')
                subprocess.run([sys.executable, '-m', 'pytest', '-q', 'tests/test_billing_database.py'], env=env, cwd=backend, check=True)
        finally:
            run([binary('pg_ctl'), '-D', data, '-m', 'immediate', '-w', 'stop'])


if __name__ == '__main__':
    main()
