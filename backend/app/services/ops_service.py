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
class AnalysisCycleHealthRow:
    scheduled: int
    refreshing: int
    ready: int
    failed: int
    due_refresh: int
    due_run: int
    stale_refreshing: int
    overdue: int
    oldest_refresh_due_seconds: float | None
    oldest_run_due_seconds: float | None

    @classmethod
    def from_row(cls, row: dict) -> "AnalysisCycleHealthRow":
        return cls(
            scheduled=row["scheduled"],
            refreshing=row["refreshing"],
            ready=row["ready"],
            failed=row["failed"],
            due_refresh=row["due_refresh"],
            due_run=row["due_run"],
            stale_refreshing=row["stale_refreshing"],
            overdue=row["overdue"],
            oldest_refresh_due_seconds=row["oldest_refresh_due_seconds"],
            oldest_run_due_seconds=row["oldest_run_due_seconds"],
        )


@dataclass(frozen=True)
class QueueHealth:
    as_of: datetime
    analysis: QueueHealthRow
    flares: QueueHealthRow
    cycles: AnalysisCycleHealthRow
    alerts: tuple[str, ...]


class _QueueMaintenanceDict(TypedDict):
    analysis_jobs: dict[str, int]
    flare_generation_runs: dict[str, int]
    recovered_stale_analysis_jobs: int
    recovered_stale_flare_runs: int


class _CycleMaintenanceDict(TypedDict):
    stale_refreshing: int
    overdue: int
    recovered_stale_refreshes: int
    failed_stale_cycles: int
    failed_retention_candidates: int
    failed_deleted: int


class _ActivityEventMaintenanceDict(TypedDict):
    candidates: int
    deleted: int


@dataclass(frozen=True)
class QueueMaintenance:
    before: QueueHealth
    after: QueueHealth
    dry_run: bool
    applied: bool
    recovered_stale_analysis_jobs: int
    recovered_stale_flare_runs: int
    recovered_stale_analysis_cycle_refreshes: int
    failed_stale_analysis_cycles: int
    analysis_jobs_candidates: int
    analysis_jobs_deleted: int
    flare_generation_runs_candidates: int
    flare_generation_runs_deleted: int
    analysis_cycles_candidates: int
    analysis_cycles_deleted: int
    activity_events_candidates: int
    activity_events_deleted: int

    @property
    def alerts(self) -> tuple[str, ...]:
        return self.before.alerts


class QueueService:
    def __init__(self, database: Database, identity: WorkspaceIdentity):
        self._database = database
        self._identity = identity

    def queue_health(self) -> QueueHealth:
        with self._database.workspace_transaction(self._identity) as connection:
            row = connection.execute(
                "SELECT public.queue_operational_health() AS value"
            ).fetchone()

        data = row["value"]
        analysis = QueueHealthRow.from_row(data["analysis"])
        flares = QueueHealthRow.from_row(data["flares"])
        cycles = AnalysisCycleHealthRow.from_row(data["cycles"])
        alerts = self._alerts(analysis, flares, cycles)

        # Keep all timestamps stable in UTC for machine parsing in observability systems.
        return QueueHealth(
            as_of=datetime.now(tz=timezone.utc),
            analysis=analysis,
            flares=flares,
            cycles=cycles,
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
        cycle_failed_retention_days: int,
        activity_event_retention_days: int,
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
            cycle_maintenance = connection.execute(
                """
                SELECT public.analysis_cycle_maintenance(%s, %s, %s, %s)
                """,
                (
                    dry_run,
                    recover_stale,
                    cycle_failed_retention_days,
                    max_rows,
                ),
            ).fetchone()
            activity_maintenance = connection.execute(
                """
                SELECT public.activity_event_maintenance(%s, %s, %s)
                """,
                (dry_run, activity_event_retention_days, max_rows),
            ).fetchone()

        data: _QueueMaintenanceDict = maintenance["queue_maintenance"]
        cycle_data: _CycleMaintenanceDict = cycle_maintenance["analysis_cycle_maintenance"]
        activity_data: _ActivityEventMaintenanceDict = activity_maintenance[
            "activity_event_maintenance"
        ]
        after = self.queue_health()
        return QueueMaintenance(
            before=before,
            after=after,
            dry_run=dry_run,
            applied=not dry_run,
            recovered_stale_analysis_jobs=data["recovered_stale_analysis_jobs"],
            recovered_stale_flare_runs=data["recovered_stale_flare_runs"],
            recovered_stale_analysis_cycle_refreshes=cycle_data["recovered_stale_refreshes"],
            failed_stale_analysis_cycles=cycle_data["failed_stale_cycles"],
            analysis_jobs_candidates=data["analysis_jobs"]["candidates"],
            analysis_jobs_deleted=data["analysis_jobs"]["deleted"],
            flare_generation_runs_candidates=data["flare_generation_runs"]["candidates"],
            flare_generation_runs_deleted=data["flare_generation_runs"]["deleted"],
            analysis_cycles_candidates=cycle_data["failed_retention_candidates"],
            analysis_cycles_deleted=cycle_data["failed_deleted"],
            activity_events_candidates=activity_data["candidates"],
            activity_events_deleted=activity_data["deleted"],
        )

    def _alerts(
        self,
        analysis: QueueHealthRow,
        flares: QueueHealthRow,
        cycles: AnalysisCycleHealthRow,
    ) -> tuple[str, ...]:
        alerts: list[str] = []

        if analysis.due > 0 and analysis.processing == 0:
            alerts.append("analysis_pending_without_processing_worker")
        if flares.due > 0 and flares.processing == 0:
            alerts.append("flares_pending_without_processing_worker")
        if analysis.stale_processing > 0:
            alerts.append("analysis_stale_lease_detected")
        if flares.stale_processing > 0:
            alerts.append("flare_stale_lease_detected")
        if analysis.failed > analysis.completed and analysis.failed >= 3:
            alerts.append("high_analysis_failure_ratio")
        if flares.failed > flares.completed and flares.failed >= 3:
            alerts.append("high_flare_failure_ratio")
        if cycles.due_refresh > 0:
            alerts.append("analysis_cycle_refresh_backlog_detected")
        if cycles.due_run > 0:
            alerts.append("analysis_cycle_run_backlog_detected")
        if cycles.stale_refreshing > 0:
            alerts.append("analysis_cycle_stale_lease_detected")
        if cycles.overdue > 0:
            alerts.append("analysis_cycle_overdue")
        if cycles.failed > 0:
            alerts.append("analysis_cycle_failed")
        if analysis.due > 0 and not alerts:
            alerts.append("analysis_due_backlog_detected")

        return tuple(alerts)
