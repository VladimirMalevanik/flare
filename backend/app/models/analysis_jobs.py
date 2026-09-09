"""Small queue capabilities; every worker operation commits and closes its connection."""
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.models.database import Database, WorkspaceIdentity


class JobUnavailable(Exception):
    """No source identifiers, credentials or database details in public errors."""


class AnalysisJobs:
    def __init__(self, database: Database):
        self.database = database

    def enqueue(self, identity: WorkspaceIdentity, chunks: tuple[UUID, ...],
                pipeline_revision: str, max_attempts: int = 3) -> UUID:
        try:
            with self.database.workspace_transaction(identity, write=True) as conn:
                return conn.execute('SELECT public.enqueue_analysis_job(%s,%s,%s) AS id',
                                    (list(chunks), pipeline_revision, max_attempts)).fetchone()['id']
        except (psycopg.IntegrityError, psycopg.errors.InsufficientPrivilege,
                psycopg.errors.InvalidParameterValue):
            raise JobUnavailable('Analysis sources unavailable') from None


@dataclass(frozen=True)
class Claim:
    job_id: UUID
    workspace_id: UUID
    requested_by_user_id: str
    pipeline_revision: str
    lease_token: UUID
    lease_expires_at: datetime
    attempts: int
    max_attempts: int


class WorkerJobs:
    def __init__(self, database_url: str):
        self._database_url = database_url

    def _call(self, sql: str, params: tuple):
        # No connection pool/transaction can escape this method. Lock waits are
        # bounded too; a DB failure leaves the lease recoverable after expiry.
        with psycopg.connect(self._database_url, connect_timeout=3, row_factory=dict_row,
                             application_name='flare-analysis-worker',
                             options='-c statement_timeout=10000 -c lock_timeout=5000') as conn:
            safe = conn.execute("SELECT current_user='flare_worker' AND NOT rolsuper AND NOT rolbypassrls AS safe FROM pg_roles WHERE rolname=current_user").fetchone()
            if not safe or not safe['safe']:
                raise JobUnavailable('Worker requires restricted flare_worker role')
            return conn.execute(sql, params).fetchone()

    def claim(self, owner: UUID, lease_seconds: int) -> Claim | None:
        row = self._call('SELECT * FROM public.claim_analysis_job(%s,%s)', (owner, lease_seconds))
        return Claim(**row) if row else None

    def evidence(self, claim: Claim, max_sources: int, max_bytes: int) -> dict:
        return self._call('SELECT public.load_analysis_evidence(%s,%s,%s,%s) AS value',
                          (claim.job_id, claim.lease_token, max_sources, max_bytes))['value']

    def finish(self, claim: Claim, *, result: dict | None = None, metadata: dict | None = None,
               error: str | None = None, retry_seconds: float | None = None) -> str:
        from app.ai_engine.flare_config import load_flare_settings
        from app.config import load_ai_settings
        revision = load_flare_settings().revision(load_ai_settings())
        return self._call("WITH config AS MATERIALIZED (SELECT set_config('app.flare_generation_revision',%s,true)) "
                          'SELECT public.finish_analysis_job(%s,%s,%s,%s,%s,%s) AS value FROM config',
                          (revision, claim.job_id, claim.lease_token, Jsonb(result) if result is not None else None,
                           Jsonb(metadata) if metadata is not None else None, error, retry_seconds))['value']
