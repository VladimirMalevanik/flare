"""Operational observability for queues and async job backlog."""

from dataclasses import dataclass
from typing import TypedDict
from datetime import datetime, timezone
from uuid import UUID

from app.models.database import Database, WorkspaceIdentity


@dataclass(frozen=True)
class QueueHealthRow:
    pending: int
    processing: int
    completed: int
    failed: int
    due: int
    stale_processing: int
    oldest_pending_seconds: float | None
    oldest_processing_seconds: float | None

    @classmethod
    def from_row(cls, row: dict) -> "QueueHealthRow":
        return cls(
            pending=row["pending"],
            processing=row["processing"],
            completed=row["completed"],
            failed=row["failed"],
            due=row["due"],
            stale_processing=row["stale_processing"],
            oldest_pending_seconds=row["oldest_pending_seconds"],
            oldest_processing_seconds=row["oldest_processing_seconds"],
        )


@dataclass(frozen=True)
class QueueHealth:
    as_of: datetime
    analysis: QueueHealthRow
    flares: QueueHealthRow
    alerts: tuple[str, ...]


class _QueueMaintenanceDict(TypedDict):
    analysis_jobs: dict[str, int]
    flare_generation_runs: dict[str, int]
    recovered_stale_analysis_jobs: int
    recovered_stale_flare_runs: int


@dataclass(frozen=True)
class QueueMaintenance:
    before: QueueHealth
    after: QueueHealth
    dry_run: bool
    applied: bool
    recovered_stale_analysis_jobs: int
    recovered_stale_flare_runs: int
    analysis_jobs_candidates: int
    analysis_jobs_deleted: int
    flare_generation_runs_candidates: int
    flare_generation_runs_deleted: int

    @property
    def alerts(self) -> tuple[str, ...]:
        return self.before.alerts


class QueueService:
    _ANALYSIS_SQL = """
        SELECT
            COUNT(*) FILTER (WHERE status='pending')::int AS pending,
            COUNT(*) FILTER (WHERE status='processing')::int AS processing,
            COUNT(*) FILTER (WHERE status='completed')::int AS completed,
            COUNT(*) FILTER (WHERE status='failed')::int AS failed,
            COUNT(*) FILTER (WHERE status='pending' AND available_at <= clock_timestamp())::int AS due,
            COUNT(*) FILTER (WHERE status='processing' AND lease_expires_at <= clock_timestamp())::int AS stale_processing,
            EXTRACT(EPOCH FROM (clock_timestamp() - MIN(created_at) FILTER (WHERE status='pending'))) AS oldest_pending_seconds,
            EXTRACT(EPOCH FROM (clock_timestamp() - MIN(created_at) FILTER (WHERE status='processing'))) AS oldest_processing_seconds
        FROM public.analysis_jobs
    """

    _FLARE_SQL = """
        SELECT
            COUNT(*) FILTER (WHERE status='pending')::int AS pending,
            COUNT(*) FILTER (WHERE status='processing')::int AS processing,
            COUNT(*) FILTER (WHERE status='completed')::int AS completed,
            COUNT(*) FILTER (WHERE status='failed')::int AS failed,
            COUNT(*) FILTER (WHERE status='pending' AND available_at <= clock_timestamp())::int AS due,
            COUNT(*) FILTER (WHERE status='processing' AND lease_expires_at <= clock_timestamp())::int AS stale_processing,
            EXTRACT(EPOCH FROM (clock_timestamp() - MIN(created_at) FILTER (WHERE status='pending'))) AS oldest_pending_seconds,
            EXTRACT(EPOCH FROM (clock_timestamp() - MIN(created_at) FILTER (WHERE status='processing'))) AS oldest_processing_seconds
        FROM public.flare_generation_runs
    """

    _INSPECT_SQL = """
        WITH bad_jobs AS (
            SELECT COUNT(*) AS stale_processing
            FROM public.analysis_jobs
            WHERE status='processing' AND lease_expires_at <= clock_timestamp()
        ), pending_due AS (
            SELECT COUNT(*) AS due_pending
            FROM public.analysis_jobs
            WHERE status='pending' AND available_at <= clock_timestamp()
        )
        SELECT
            (SELECT stale_processing FROM bad_jobs) AS stale_processing,
            (SELECT due_pending FROM pending_due) AS due_pending
    """

    def __init__(self, database: Database, identity: WorkspaceIdentity):
        self._database = database
        self._identity = identity

    def queue_health(self) -> QueueHealth:
        with self._database.workspace_transaction(self._identity) as connection:
            analysis_row = connection.execute(self._ANALYSIS_SQL).fetchone()
            flare_row = connection.execute(self._FLARE_SQL).fetchone()
            inspect = connection.execute(self._INSPECT_SQL).fetchone()

        analysis = QueueHealthRow.from_row(analysis_row)
        flares = QueueHealthRow.from_row(flare_row)
        alerts = self._alerts(analysis, flares, inspect)

        # Keep all timestamps stable in UTC for machine parsing in observability systems.
        return QueueHealth(
            as_of=datetime.now(tz=timezone.utc),
            analysis=analysis,
            flares=flares,
            alerts=tuple(alerts),
        )

    def queue_maintenance(
        self,
        *,
        dry_run: bool,
        recover_stale: bool,
        max_rows: int,
        analysis_completed_retention_days: int,
        analysis_failed_retention_days: int,
        flare_completed_retention_days: int,
        flare_failed_retention_days: int,
    ) -> QueueMaintenance:
        before = self.queue_health()
        with self._database.workspace_transaction(self._identity, write=True) as connection:
            maintenance = connection.execute(
                """
                SELECT public.queue_maintenance(
                    %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    dry_run,
                    recover_stale,
                    analysis_completed_retention_days,
                    analysis_failed_retention_days,
                    flare_completed_retention_days,
                    flare_failed_retention_days,
                    max_rows,
                ),
            ).fetchone()

        data: _QueueMaintenanceDict = maintenance["queue_maintenance"]
        after = self.queue_health()
        return QueueMaintenance(
            before=before,
            after=after,
            dry_run=dry_run,
            applied=not dry_run,
            recovered_stale_analysis_jobs=data["recovered_stale_analysis_jobs"],
            recovered_stale_flare_runs=data["recovered_stale_flare_runs"],
            analysis_jobs_candidates=data["analysis_jobs"]["candidates"],
            analysis_jobs_deleted=data["analysis_jobs"]["deleted"],
            flare_generation_runs_candidates=data["flare_generation_runs"]["candidates"],
            flare_generation_runs_deleted=data["flare_generation_runs"]["deleted"],
        )

    def _alerts(self, analysis: QueueHealthRow, flares: QueueHealthRow, inspect: dict) -> tuple[str, ...]:
        alerts: list[str] = []

        if analysis.due > 0 and analysis.processing == 0:
            alerts.append("analysis_pending_without_processing_worker")
        if flares.due > 0 and flares.processing == 0:
            alerts.append("flares_pending_without_processing_worker")
        if inspect["stale_processing"] > 0:
            alerts.append("analysis_stale_lease_detected")
        if flares.stale_processing > 0:
            alerts.append("flare_stale_lease_detected")
        if analysis.failed > analysis.completed and analysis.failed >= 3:
            alerts.append("high_analysis_failure_ratio")
        if flares.failed > flares.completed and flares.failed >= 3:
            alerts.append("high_flare_failure_ratio")
        if inspect["due_pending"] > 0 and not alerts:
            alerts.append("analysis_due_backlog_detected")

        return tuple(alerts)
