"""Persistence contracts for daily workspace analysis scheduling."""

from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any
from uuid import UUID

from app.models.analysis_jobs import WorkerJobs
from app.models.database import Database, WorkspaceIdentity


@dataclass(frozen=True)
class AnalysisScheduleRecord:
    enabled: bool
    timezone: str
    local_time: time
    lead_minutes: int
    updated_at: datetime


class AnalysisScheduleRepository:
    def __init__(self, database: Database, identity: WorkspaceIdentity):
        self._database = database
        self._identity = identity

    def get(self) -> AnalysisScheduleRecord | None:
        with self._database.workspace_transaction(self._identity) as connection:
            row = connection.execute(
                """SELECT enabled,timezone,local_time,lead_minutes,updated_at
                   FROM public.analysis_schedules WHERE workspace_id=%s""",
                (self._identity.workspace_id,),
            ).fetchone()
            return AnalysisScheduleRecord(**row) if row else None

    def put(self, *, enabled: bool, timezone_name: str, local_time: time) -> AnalysisScheduleRecord:
        with self._database.workspace_transaction(self._identity, write=True) as connection:
            row = connection.execute(
                """INSERT INTO public.analysis_schedules
                       (workspace_id,enabled,timezone,local_time,lead_minutes,updated_by_user_id)
                   VALUES(%s,%s,%s,%s,30,%s)
                   ON CONFLICT(workspace_id) DO UPDATE SET
                       enabled=excluded.enabled,timezone=excluded.timezone,
                       local_time=excluded.local_time,lead_minutes=30,
                       updated_by_user_id=excluded.updated_by_user_id,updated_at=clock_timestamp()
                   RETURNING enabled,timezone,local_time,lead_minutes,updated_at""",
                (
                    self._identity.workspace_id,
                    enabled,
                    timezone_name,
                    local_time,
                    self._identity.user_id,
                ),
            ).fetchone()
            return AnalysisScheduleRecord(**row)

    def daily_cycle(self, local_date: date) -> dict[str, Any] | None:
        with self._database.workspace_transaction(self._identity) as connection:
            return connection.execute(
                """SELECT c.id AS cycle_id,c.mode,c.scheduled_for,c.refresh_due_at,
                          c.refresh_status,c.snapshot_chunk_count,c.analysis_run_id AS run_id,
                          c.last_error_code,run.value->>'status' AS run_status,
                          run.value->>'stage' AS run_stage
                   FROM public.analysis_cycles c
                   LEFT JOIN LATERAL (
                       SELECT public.read_analysis_run(c.analysis_run_id) AS value
                   ) run ON c.analysis_run_id IS NOT NULL
                   WHERE c.workspace_id=%s AND c.local_date=%s""",
                (self._identity.workspace_id, local_date),
            ).fetchone()

    def github_connected(self) -> bool:
        with self._database.workspace_transaction(self._identity) as connection:
            row = connection.execute(
                """SELECT EXISTS(SELECT 1 FROM public.github_connections
                                  WHERE workspace_id=%s AND status='connected'
                                    AND repository_id IS NOT NULL) AS connected""",
                (self._identity.workspace_id,),
            ).fetchone()
            return bool(row and row["connected"])


@dataclass(frozen=True)
class RefreshClaim:
    cycle_id: UUID
    workspace_id: UUID
    requested_by_user_id: str
    lease_token: UUID
    lease_expires_at: datetime
    attempts: int


class WorkerAnalysisSchedules(WorkerJobs):
    """EXECUTE-only worker facade; customer rows stay behind DB capabilities."""

    def materialize(self, now: datetime, limit: int = 100) -> int:
        row = self._call("SELECT public.materialize_analysis_cycles(%s,%s) AS value", (now, limit))
        return int(row["value"])

    def claim_refresh(self, owner: UUID, lease_seconds: int) -> RefreshClaim | None:
        row = self._call(
            "SELECT * FROM public.claim_analysis_cycle_refresh(%s,%s)",
            (owner, lease_seconds),
        )
        return RefreshClaim(**row) if row else None

    def candidates(self, claim: RefreshClaim, max_sources: int, max_bytes: int) -> dict[str, Any]:
        row = self._call(
            "SELECT public.load_analysis_cycle_candidates(%s,%s,%s,%s) AS value",
            (claim.cycle_id, claim.lease_token, max_sources, max_bytes),
        )
        return row["value"]

    def finish_refresh(
        self,
        claim: RefreshClaim,
        *,
        chunks: tuple[UUID, ...] | None = None,
        error: str | None = None,
        retry_seconds: float | None = None,
    ) -> str:
        row = self._call(
            "SELECT public.finish_analysis_cycle_refresh(%s,%s,%s,%s,%s) AS value",
            (claim.cycle_id, claim.lease_token, list(chunks) if chunks else None, error, retry_seconds),
        )
        return row["value"]

    def enqueue_due(
        self,
        *,
        pipeline_revision: str,
        generation_revision: str,
        max_attempts: int,
        now: datetime,
        limit: int = 20,
    ) -> list[dict[str, str]]:
        row = self._call(
            "SELECT public.enqueue_due_analysis_cycles(%s,%s,%s,%s,%s) AS value",
            (pipeline_revision, generation_revision, max_attempts, now, limit),
        )
        value = row["value"]
        return value if isinstance(value, list) else []
