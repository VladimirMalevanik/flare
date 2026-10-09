"""OPS-005 bounded Azure operator. No raw errors, data, DSNs or tokens output.

Run only in the authenticated Azure Cloud Shell, from the pinned public checkout.
check performs read-only preflight. migrate applies only the tested 0021->0022.
"""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

SHA = '7365f5342e08561567206de38c224620dcc00d6e'
SUB = '30b50e44-d024-4f28-973f-2d805a3499b1'
TENANT = 'c4cd2b31-2f91-48f4-8d0b-839d1eafa9c6'
HOST = 'flare-dev-pg-vm-260914.postgres.database.azure.com'
TABLES = ('import_packages', 'import_objects', 'import_publications')


def connection_info(raw):
    assert isinstance(raw, str) and raw.startswith(('postgresql+psycopg://', 'postgresql://'))
    info = conninfo_to_dict(raw.replace('postgresql+psycopg://','postgresql://',1))
    # Reject service/passfile/hostaddr overrides instead of silently forwarding
    # alternate routing or reading unrelated credential files in Cloud Shell.
    allowed = {'host','port','dbname','user','password','sslmode','sslrootcert','connect_timeout','options'}
    assert not set(info).difference(allowed)
    assert info['host']==HOST and info['dbname']=='flare' and int(info.get('port',5432))==5432
    assert info.get('user') and info.get('password') and info['user'] not in ('flare_app','flare_worker','flare_onboarding')
    assert not any(os.getenv(name) for name in ('PGHOSTADDR','PGSERVICE','PGSERVICEFILE','PGPASSFILE'))
    info.update(port='5432',sslmode='verify-full',sslrootcert='system',connect_timeout='8',
                options='-c default_transaction_read_only=on -c statement_timeout=10000 -c lock_timeout=2000')
    return info


def authority(c):
    executor = c.execute("""SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,rolinherit,rolbypassrls
        FROM pg_roles WHERE rolname='flare_job_executor'""").fetchone()
    safe = executor == (False,False,False,False,False,False)
    safe = safe and c.execute("SELECT NOT EXISTS(SELECT 1 FROM pg_auth_members WHERE member='flare_job_executor'::regrole)").fetchone()[0]
    safe = safe and c.execute("""SELECT NOT EXISTS(SELECT 1 FROM pg_auth_members
        WHERE roleid='flare_job_executor'::regrole AND member<>current_user::regrole)
        AND NOT has_schema_privilege('flare_job_executor','public','CREATE')""").fetchone()[0]
    permissions = c.execute("""SELECT
        has_schema_privilege(current_user,'public','CREATE'),
        bool_and((SELECT rolsuper FROM pg_roles WHERE rolname=current_user)
          OR pg_has_role(current_user,c.relowner,'USAGE')),
        ((SELECT rolsuper FROM pg_roles WHERE rolname=current_user)
          OR (pg_has_role(current_user,'flare_job_executor','SET') AND pg_has_role(current_user,'flare_job_executor','USAGE'))
          OR (EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid='flare_job_executor'::regrole
                AND member=current_user::regrole AND admin_option)
              AND NOT EXISTS(SELECT 1 FROM pg_auth_members WHERE roleid='flare_job_executor'::regrole
                AND member=current_user::regrole AND grantor=current_user::regrole)))
        FROM pg_class c WHERE c.oid IN ('public.import_objects'::regclass,'public.import_packages'::regclass,'public.alembic_version'::regclass)""").fetchone()
    return {'executorSafe':safe,'schemaCreate':permissions[0],
            'existingTableOwnership':permissions[1],'executorTransferAuthority':permissions[2]}, executor


def az(args):
    p = subprocess.run(['az', *args, '--only-show-errors', '-o', 'json'],
                       capture_output=True, timeout=45)
    if p.returncode or len(p.stdout) > 65536:
        raise RuntimeError('azure_read_failed')
    return json.loads(p.stdout)


def baseline(c):
    revision = c.execute('SELECT version_num FROM public.alembic_version').fetchone()[0]
    assert revision in ('0021', '0022')
    assert int(c.execute('SHOW server_version_num').fetchone()[0])//10000 == 17
    assert c.execute("SELECT current_user IN ('flare_app','flare_worker','flare_onboarding')").fetchone() == (False,)
    role = c.execute('SELECT rolname,rolsuper,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=current_user').fetchone()
    counts = {t:c.execute('SELECT count(*) FROM public.' + t).fetchone()[0] for t in TABLES}
    functions = c.execute("""SELECT oid::regprocedure::text,md5(pg_get_functiondef(oid))
        FROM pg_proc WHERE pronamespace='public'::regnamespace
        AND NOT EXISTS(SELECT 1 FROM pg_depend WHERE objid=pg_proc.oid AND deptype='e')
        ORDER BY oid::regprocedure::text""").fetchall()
    memberships = c.execute("""SELECT roleid,member,grantor,admin_option,inherit_option,set_option
        FROM pg_auth_members WHERE roleid IN (SELECT oid FROM pg_roles WHERE rolname LIKE 'flare_%')
        OR member IN (SELECT oid FROM pg_roles WHERE rolname LIKE 'flare_%') ORDER BY roleid,member,grantor""").fetchall()
    permissions, executor = authority(c)
    return {'revision':revision,'role':role,'executor':executor,'authority':permissions,
            'counts':counts,'functions':dict(functions),'memberships':memberships}


def verify(c, module):
    assert c.execute('SELECT version_num FROM public.alembic_version').fetchone() == ('0022',)
    for table in ('import_staging_blocks','import_staging_health'):
        assert c.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass',
                         ('public.'+table,)).fetchone() == (True, True)
        assert c.execute("SELECT count(*) FROM pg_class r CROSS JOIN LATERAL aclexplode(coalesce(r.relacl,acldefault('r',r.relowner))) a WHERE r.oid=%s::regclass AND a.grantee=0",('public.'+table,)).fetchone() == (0,)
        assert c.execute("SELECT count(*) FROM pg_attribute r CROSS JOIN LATERAL aclexplode(r.attacl) a WHERE r.attrelid=%s::regclass AND a.grantee=0",('public.'+table,)).fetchone() == (0,)
        for role in ('flare_app','flare_worker'):
            assert c.execute("SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')",
                             (role,'public.'+table)).fetchone() == (False,)
            assert c.execute("SELECT has_any_column_privilege(%s,%s,'SELECT,INSERT,UPDATE,REFERENCES')",(role,'public.'+table)).fetchone() == (False,)
    for signature, roles in module.FUNCTIONS.items():
        owner, secure, settings = c.execute("SELECT proowner::regrole::text,prosecdef,proconfig FROM pg_proc WHERE oid=%s::regprocedure",
                                            ('public.'+signature,)).fetchone()
        assert owner == 'flare_job_executor' and secure
        assert 'search_path=pg_catalog, public, pg_temp' in settings
        assert 'statement_timeout=5s' in settings and 'lock_timeout=2s' in settings
        assert c.execute("SELECT count(*) FROM pg_proc p CROSS JOIN LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a WHERE p.oid=%s::regprocedure AND a.grantee=0",('public.'+signature,)).fetchone() == (0,)
        for role in ('flare_app','flare_worker'):
            assert c.execute('SELECT has_function_privilege(%s,%s,%s)',
                             (role,'public.'+signature,'EXECUTE')).fetchone() == (role in roles,)
    for role in ('flare_app','flare_worker'):
        assert c.execute('SELECT rolsuper,rolcreatedb,rolcreaterole,rolbypassrls FROM pg_roles WHERE rolname=%s',
                         (role,)).fetchone() == (False,False,False,False)
        assert c.execute('SELECT count(*) FROM pg_auth_members WHERE member=%s::regrole',(role,)).fetchone() == (0,)


def main():
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('check','migrate'));args=p.parse_args()
    repo=Path(subprocess.run(['git','rev-parse','--show-toplevel'],capture_output=True,text=True,
                            timeout=10,check=True).stdout.strip()).resolve()
    actual=subprocess.run(['git','rev-parse','HEAD'],capture_output=True,text=True,timeout=10,check=True).stdout.strip()
    assert actual == SHA
    subprocess.run(['git','diff','--quiet','HEAD','--'],cwd=repo,capture_output=True,timeout=10,check=True)
    account=az(['account','show']); assert account['id']==SUB and account['tenantId']==TENANT
    raw=az(['keyvault','secret','show','--vault-name','flare-dev-kv-260914',
            '--name','migration-database-url','--query','value'])
    info=connection_info(raw)
    with psycopg.connect(make_conninfo(**info)) as c:
        before=baseline(c)
    spec=importlib.util.spec_from_file_location('ops005_migration',repo/'backend/migrations/versions/0022_postgres_import_staging.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    if args.mode=='migrate' and before['revision']=='0021':
        assert all(before['authority'].values())
        from sqlalchemy.engine import URL
        from alembic import command
        from alembic.config import Config
        query={k:str(v) for k,v in info.items() if k not in ('user','password','host','port','dbname','options')}
        query['options']='-c statement_timeout=30000 -c lock_timeout=2000'
        url=URL.create('postgresql+psycopg',username=info.get('user'),password=info.get('password'),
                       host=info['host'],port=int(info.get('port',5432)),database=info['dbname'],query=query)
        os.environ.update(MIGRATION_DATABASE_URL=url.render_as_string(hide_password=False),
                          PYTHON_DOTENV_DISABLED='1',FLARE_ENV='production',FLARE_PROCESS_ROLE='migration',
                          FLARE_DATABASE_PROVIDER='self-managed')
        sys.path.insert(0,str(repo/'backend'))
        try:
            config=Config(str(repo/'backend/alembic.ini'))
            config.set_main_option('script_location',str(repo/'backend/migrations'))
            command.upgrade(config,'0022')
        finally:
            os.environ.pop('MIGRATION_DATABASE_URL',None)
    with psycopg.connect(make_conninfo(**info)) as c:
        after=baseline(c)
        assert after['role']==before['role'] and after['executor']==before['executor'] and after['memberships']==before['memberships']
        # Workers may legitimately finish unrelated imports while preflight runs.
        # Original function definitions and role authority must remain identical.
        assert all(after['functions'].get(k)==v for k,v in before['functions'].items())
        if after['revision']=='0022':verify(c,module)
    print(json.dumps({'sourceSha':SHA,'mode':args.mode,'beforeSchema':before['revision'],
                      'afterSchema':after['revision'],'tlsVerifyFull':True,'authorityPreserved':True,
                      'originalFunctionsPreserved':True,'privateStagingVerified':after['revision']=='0022',
                      'migrationAuthority':before['authority'],
                      'importCountsBefore':before['counts'],'importCountsAfter':after['counts'],
                      'passed':True}))


if __name__=='__main__':
    try:main()
    except BaseException as e:
        print(json.dumps({'passed':False,'errorType':type(e).__name__,'rawErrorWithheld':True}))
        raise SystemExit(1)
