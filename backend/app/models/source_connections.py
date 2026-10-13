"""Caller-bound source API queries and worker-only lease capabilities."""
from uuid import UUID
import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb
from app.models.database import Database, WorkspaceIdentity, _source_storage_is_safe


class SourceStateError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def result_or_error(value):
    if isinstance(value, dict) and value.get('error'):
        raise SourceStateError(value['error'])
    return value


class SourceConnectionRepository:
    def __init__(self, database: Database, identity: WorkspaceIdentity):
        self.database, self.identity = database, identity

    def ready(self) -> bool:
        try:
            with self.database.workspace_transaction(self.identity) as connection:
                with connection.cursor(row_factory=tuple_row) as cursor:
                    exists=cursor.execute("SELECT to_regprocedure('public.source_api(text,uuid,jsonb)') IS NOT NULL").fetchone()[0]
                    return exists and _source_storage_is_safe(cursor)
        except psycopg.Error:
            return False

    def action(self, action: str, connection_id: UUID | None = None, payload: dict | None = None):
        try:
            with self.database.workspace_transaction(self.identity) as connection:
                result = connection.execute('SELECT public.source_api(%s,%s,%s) AS value',
                                            (action, connection_id, Jsonb(payload or {}))).fetchone()['value']
            return result_or_error(result)
        except psycopg.errors.UndefinedFunction:
            raise SourceStateError('source_not_enabled') from None

    def list(self) -> list[dict]:
        return self.action('list')

    def health(self) -> dict:
        return self.action('health')


class SourceJobs:
    def __init__(self, database_url: str):
        self.database_url = database_url

    def call(self, statement: str, arguments: tuple):
        # Only the restricted worker role can execute claim/step. No app URL fallback.
        with psycopg.connect(self.database_url, autocommit=True, row_factory=dict_row,
                             connect_timeout=3, options='-c statement_timeout=15000 -c lock_timeout=2000') as connection:
            role = connection.execute("SELECT current_user='flare_worker' AND NOT rolsuper AND NOT rolbypassrls AND NOT rolcreatedb AND NOT rolcreaterole AND NOT EXISTS(SELECT 1 FROM pg_auth_members WHERE member=pg_roles.oid) AS safe FROM pg_roles WHERE rolname=current_user").fetchone()
            if not role or not role['safe']:
                raise SourceStateError('unsafe_worker_role')
            try:
                value = connection.execute(statement, arguments).fetchone()['value']
                return result_or_error(value)
            except psycopg.errors.ProgramLimitExceeded:
                raise SourceStateError('workspace_storage_limit') from None

    def claim(self, providers: list[str], concurrency: int = 1) -> dict | None:
        return self.call('SELECT public.claim_source_job(%s,%s) AS value', (providers, concurrency))

    def step(self, job: dict, action: str, payload: dict):
        return self.call('SELECT public.source_worker_step(%s,%s,%s,%s,%s) AS value',
                         (job['id'], job['lease_token'], job['generation'], action, Jsonb(payload)))
