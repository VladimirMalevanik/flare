"""Short, tenant-bound API transactions and restricted worker capabilities."""
from uuid import UUID
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from app.models.database import Database, WorkspaceIdentity


class ImportPackageError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def checked(result):
    if result and result.get('error'):
        raise ImportPackageError(result['error'])
    return result


PUBLIC_COLUMNS = '''id,source_kind,file_name,file_size,status,phase,entry_count,
prepared_count,skipped_count,published_count,failed_count,chunk_count,error_code,retryable,attempts,
created_at,completed_at,canonical_id'''


class ImportPackages:
    def __init__(self, database: Database, identity: WorkspaceIdentity):
        self.database, self.identity = database, identity

    def action(self, action, package_id=None, payload=None):
        with self.database.workspace_transaction(self.identity, write=True) as connection:
            return checked(connection.execute('SELECT public.import_api(%s,%s,%s) AS result',
                (action, package_id, Jsonb(payload or {}))).fetchone()['result'])

    def get(self, package_id: UUID):
        with self.database.workspace_transaction(self.identity) as connection:
            row = connection.execute(f'SELECT {PUBLIC_COLUMNS} FROM public.import_packages WHERE id=%s', (package_id,)).fetchone()
            if not row:
                raise ImportPackageError('not_found')
            return row

    def list(self):
        with self.database.workspace_transaction(self.identity) as connection:
            return connection.execute(f'SELECT {PUBLIC_COLUMNS} FROM public.import_packages ORDER BY created_at DESC,id DESC LIMIT 50').fetchall()

    def entries(self, package_id, after=-1, limit=50):
        self.get(package_id)
        with self.database.workspace_transaction(self.identity) as connection:
            return connection.execute('''SELECT ordinal,path,file_bytes,skip_reason,status,document_id,version_id
                FROM public.import_package_entries WHERE package_id=%s AND ordinal>%s ORDER BY ordinal LIMIT %s''',
                (package_id, after, min(limit, 100))).fetchall()

    def publications(self, after=0, limit=50):
        with self.database.workspace_transaction(self.identity) as connection:
            return connection.execute('''SELECT id,package_id,requested_by_user_id,source_kind,published_at,source_count,chunk_count
                FROM public.import_publications WHERE id>%s ORDER BY id LIMIT %s''', (after,min(limit,100))).fetchall()


class ImportWorkerJobs:
    def __init__(self, database_url):
        self.url = database_url
        with self.connection() as connection:
            safe = connection.execute('''SELECT rolname='flare_worker' AND NOT rolsuper AND NOT rolbypassrls
              AND NOT rolcreatedb AND NOT rolcreaterole AND NOT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid)
              AS safe FROM pg_roles WHERE rolname=current_user''').fetchone()
            if not safe or not safe['safe']:
                raise ValueError('Import worker requires the restricted flare_worker role')

    def connection(self):
        return psycopg.connect(self.url, row_factory=dict_row, connect_timeout=3)

    def claim(self, global_limit):
        with self.connection() as c:
            return c.execute('SELECT public.claim_import_package(%s) AS result', (global_limit,)).fetchone()['result']

    def step(self, job, action, data=None):
        with self.connection() as c:
            c.execute("SELECT set_config('statement_timeout',%s,true),set_config('lock_timeout',%s,true)",
                (str(job['policy']['file_seconds']*1000),str(job['policy']['lease_seconds']*500)))
            result=c.execute('SELECT public.import_worker_step(%s,%s,%s,%s,%s) AS result',
                (job['id'],job['lease_token'],job['generation'],action,Jsonb(data if data is not None else {}))).fetchone()['result']
        # Reject/revoke transitions must COMMIT before surfacing their error.
        return checked(result)

    def cleanup(self, action='claim', key=None, token=None):
        with self.connection() as c:
            return checked(c.execute('SELECT public.import_cleanup(%s,%s,%s) AS result', (key,token,action)).fetchone()['result'])
