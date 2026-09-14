"""Fast schedule, DST, orchestration and migration-contract checks."""

import asyncio
from dataclasses import replace
from datetime import date, datetime, time, timezone
from importlib.util import module_from_spec, spec_from_file_location
import inspect
from pathlib import Path
from uuid import uuid4

import pytest

from app.ai_engine.flare_config import FlareSettings
from app.config import AISettings
from app.models.analysis_schedules import AnalysisScheduleRecord, RefreshClaim
from app.models import database as database_module
from app.services.analysis_schedule import (
    AnalysisScheduleService,
    InvalidSchedule,
    next_schedule_window,
    parse_local_time,
)
from app.workers.config import WorkerSettings
from app.workers.scheduler import DailyScheduleProcessor


UTC = timezone.utc


@pytest.mark.parametrize("value", ["9:00", "09:0", "24:00", "10:60", "xx:yy"])
def test_local_time_is_strict(value):
    with pytest.raises(InvalidSchedule):
        parse_local_time(value)


def test_next_window_uses_iana_timezone_and_fixed_lead():
    window = next_schedule_window(
        now=datetime(2026, 1, 10, 15, 0, tzinfo=UTC),
        timezone_name="America/New_York",
        local_time=time(12, 0),
    )
    assert window.run_at == datetime(2026, 1, 10, 17, 0, tzinfo=UTC)
    assert window.refresh_at == datetime(2026, 1, 10, 16, 30, tzinfo=UTC)


def test_schedule_saved_inside_lead_window_starts_tomorrow():
    window = next_schedule_window(
        now=datetime(2026, 1, 10, 16, 45, tzinfo=UTC),
        timezone_name="America/New_York",
        local_time=time(12, 0),
    )
    assert window.run_at == datetime(2026, 1, 11, 17, 0, tzinfo=UTC)
    assert window.refresh_at == datetime(2026, 1, 11, 16, 30, tzinfo=UTC)


def test_schedule_saved_exactly_at_lead_boundary_starts_tomorrow():
    window = next_schedule_window(
        now=datetime(2026, 1, 10, 16, 30, tzinfo=UTC),
        timezone_name="America/New_York",
        local_time=time(12, 0),
    )
    assert window.run_at == datetime(2026, 1, 11, 17, 0, tzinfo=UTC)
    assert window.refresh_at == datetime(2026, 1, 11, 16, 30, tzinfo=UTC)


def test_quota_floor_allows_a_slot_exactly_twenty_hours_later():
    window = next_schedule_window(
        now=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
        timezone_name="UTC",
        local_time=time(20, 0),
        not_before=datetime(2026, 1, 1, 20, 0, tzinfo=UTC),
    )
    assert window.run_at == datetime(2026, 1, 1, 20, 0, tzinfo=UTC)


def test_quota_floor_skips_a_slot_even_one_second_inside_twenty_hours():
    window = next_schedule_window(
        now=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
        timezone_name="UTC",
        local_time=time(20, 0),
        not_before=datetime(2026, 1, 1, 20, 0, 1, tzinfo=UTC),
    )
    assert window.run_at == datetime(2026, 1, 2, 20, 0, tzinfo=UTC)


def test_spring_dst_gap_moves_forward_to_first_real_wall_time():
    window = next_schedule_window(
        now=datetime(2026, 3, 8, 5, 0, tzinfo=UTC),
        timezone_name="America/New_York",
        local_time=time(2, 30),
    )
    # PostgreSQL maps the missing 02:30 wall time forward to 03:30.
    assert window.run_at == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)


def test_fall_dst_overlap_matches_postgres_standard_time_occurrence():
    window = next_schedule_window(
        now=datetime(2026, 11, 1, 4, 0, tzinfo=UTC),
        timezone_name="America/New_York",
        local_time=time(1, 30),
    )
    assert window.run_at == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)


def test_fall_overlap_compares_real_instants_not_repeated_wall_clock():
    window = next_schedule_window(
        now=datetime(2026, 11, 1, 5, 45, tzinfo=UTC),
        timezone_name="America/New_York",
        local_time=time(1, 30),
    )
    assert window.run_at == datetime(2026, 11, 1, 6, 30, tzinfo=UTC)


def test_invalid_iana_timezone_fails_closed():
    with pytest.raises(InvalidSchedule, match="invalid_timezone"):
        next_schedule_window(
            now=datetime.now(UTC), timezone_name="Mars/Olympus", local_time=time(10)
        )


class FakeRepository:
    def __init__(self, schedule=None, cycle=None, github=False):
        self.schedule = schedule
        self.cycle = cycle
        self.github = github
        self.put_args = None

    def get(self):
        return self.schedule

    def put(self, **values):
        self.put_args = values
        self.schedule = AnalysisScheduleRecord(
            enabled=values["enabled"],
            timezone=values["timezone_name"],
            local_time=values["local_time"],
            lead_minutes=30,
            updated_at=datetime(2026, 1, 1, tzinfo=UTC),
            email_notifications_enabled=values["email_notifications_enabled"],
        )
        return self.schedule

    def daily_cycle(self, local_date):
        self.requested_day = local_date
        return self.cycle

    def github_connected(self):
        return self.github


def test_default_schedule_is_disabled_and_put_exposes_next_window():
    repository = FakeRepository()
    clock = lambda: datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    service = AnalysisScheduleService(repository, clock=clock)
    default = service.get()
    assert default["enabled"] is False
    assert default["timezone"] == "UTC"
    assert default["localTime"] == "19:00"
    assert default["emailNotificationsEnabled"] is True
    assert default["nextRunAt"] is None

    updated = service.put(enabled=True, timezone_name="Europe/Moscow", local_time_value="18:45")
    assert repository.put_args == {
        "enabled": True,
        "timezone_name": "Europe/Moscow",
        "local_time": time(18, 45),
        "email_notifications_enabled": True,
    }
    assert updated["leadMinutes"] == 30
    assert updated["nextRunAt"] == datetime(2026, 1, 1, 15, 45, tzinfo=UTC)


def test_schedule_preview_keeps_the_already_materialized_current_cycle():
    repository = FakeRepository(
        schedule=AnalysisScheduleRecord(
            True, "UTC", time(19), 30, datetime(2026, 1, 1, 12, tzinfo=UTC)
        ),
        cycle={
            "mode": "scheduled",
            "refresh_status": "ready",
            "created_at": datetime(2026, 1, 1, 18, 30, tzinfo=UTC),
            "refresh_due_at": datetime(2026, 1, 1, 18, 30, tzinfo=UTC),
            "scheduled_for": datetime(2026, 1, 1, 19, 0, tzinfo=UTC),
        },
    )
    result = AnalysisScheduleService(
        repository, clock=lambda: datetime(2026, 1, 1, 18, 45, tzinfo=UTC)
    ).get()
    assert result["nextRefreshAt"] == datetime(2026, 1, 1, 18, 30, tzinfo=UTC)
    assert result["nextRunAt"] == datetime(2026, 1, 1, 19, 0, tzinfo=UTC)


def test_schedule_preview_skips_a_slot_inside_recent_cycle_guard():
    repository = FakeRepository(
        schedule=AnalysisScheduleRecord(
            True, "UTC", time(1), 30, datetime(2026, 1, 1, 12, tzinfo=UTC)
        ),
        cycle={
            "mode": "manual",
            "refresh_status": "ready",
            "created_at": datetime(2026, 1, 1, 23, 0, tzinfo=UTC),
            "refresh_due_at": datetime(2026, 1, 1, 23, 0, tzinfo=UTC),
            "scheduled_for": datetime(2026, 1, 1, 23, 0, tzinfo=UTC),
        },
    )
    result = AnalysisScheduleService(
        repository, clock=lambda: datetime(2026, 1, 1, 23, 0, tzinfo=UTC)
    ).get()
    assert result["nextRunAt"] == datetime(2026, 1, 3, 1, 0, tzinfo=UTC)
    assert result["nextRefreshAt"] == datetime(2026, 1, 3, 0, 30, tzinfo=UTC)


def test_schedule_preview_does_not_reuse_the_same_local_date_at_twenty_hour_boundary():
    repository = FakeRepository(
        schedule=AnalysisScheduleRecord(
            True, "UTC", time(20), 30, datetime(2025, 12, 31, tzinfo=UTC)
        ),
        cycle={
            "mode": "manual",
            "refresh_status": "ready",
            "refresh_due_at": datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            "scheduled_for": datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            "local_date_consumed": True,
        },
    )
    result = AnalysisScheduleService(
        repository, clock=lambda: datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
    ).get()
    assert result["nextRunAt"] == datetime(2026, 1, 2, 20, 0, tzinfo=UTC)


def test_daily_status_reports_github_as_connected_but_not_ingested():
    repository = FakeRepository(
        schedule=AnalysisScheduleRecord(True, "UTC", time(19), 30, datetime(2026, 1, 1, tzinfo=UTC)),
        github=True,
    )
    status = AnalysisScheduleService(
        repository, clock=lambda: datetime(2026, 1, 2, 10, tzinfo=UTC)
    ).daily_status()
    assert status["state"] == "available"
    assert status["canRequestToday"] is True
    assert status["sync"]["github"] == {
        "connected": True,
        "ingestionSupported": False,
        "status": "not_ingested",
    }


def test_daily_status_terminal_failure_keeps_slot_consumed():
    repository = FakeRepository(
        schedule=AnalysisScheduleRecord(True, "UTC", time(19), 30, datetime(2026, 1, 1, tzinfo=UTC)),
        cycle={
            "cycle_id": uuid4(), "run_id": None, "mode": "scheduled",
            "scheduled_for": datetime(2026, 1, 2, 19, tzinfo=UTC),
            "refresh_due_at": datetime(2026, 1, 2, 18, 30, tzinfo=UTC),
            "refresh_status": "failed", "snapshot_chunk_count": 0,
            "last_error_code": "no_eligible_context", "run_status": None,
            "run_stage": None,
        },
    )
    status = AnalysisScheduleService(
        repository, clock=lambda: datetime(2026, 1, 2, 20, tzinfo=UTC)
    ).daily_status()
    assert status["state"] == "failed"
    assert status["reason"] == "no_eligible_context"
    assert status["canRequestToday"] is False


def test_daily_status_quota_tombstone_keeps_slot_consumed_after_run_retention():
    repository = FakeRepository(
        schedule=AnalysisScheduleRecord(
            True, "America/New_York", time(0, 30), 30,
            datetime(2026, 10, 31, tzinfo=UTC),
        ),
        cycle={
            "cycle_id": None, "run_id": None, "mode": "manual",
            "scheduled_for": datetime(2026, 11, 1, 4, 30, tzinfo=UTC),
            "refresh_due_at": datetime(2026, 11, 1, 4, 0, tzinfo=UTC),
            "refresh_status": "ready", "snapshot_chunk_count": 0,
            "last_error_code": None, "run_status": None, "run_stage": None,
            "quota_only": True, "local_date_consumed": True,
        },
    )
    status = AnalysisScheduleService(
        # New York's 2026-11-01 local day is 25 hours long.  The quota is
        # still consumed after more than 24 absolute hours.
        repository, clock=lambda: datetime(2026, 11, 2, 4, 45, tzinfo=UTC)
    ).daily_status()
    assert status["state"] == "consumed"
    assert status["sync"]["status"] == "unknown"
    assert status["canRequestToday"] is False
    assert status["reason"] == "daily_limit"


class FakeWorkerSchedules:
    def __init__(self, *, candidates=None, outcomes=None):
        self.claim = RefreshClaim(uuid4(), uuid4(), "user", uuid4(), datetime(2026, 1, 1, 1, tzinfo=UTC), 1)
        self.loaded = {"candidates": candidates or []}
        self.finished = []
        self.enqueued = []
        self.outcomes = outcomes or []

    def materialize(self, now):
        return 1

    def claim_refresh(self, owner, lease_seconds):
        claim, self.claim = self.claim, None
        return claim

    def candidates(self, claim, max_sources, max_bytes):
        return self.loaded

    def finish_refresh(self, claim, **values):
        self.finished.append(values)
        return "ready" if values.get("chunks") else "failed"

    def enqueue_due(self, **values):
        self.enqueued.append(values)
        return self.outcomes


def test_scheduler_freezes_selected_ids_without_logging_content(caplog):
    source_id = uuid4()
    stores = FakeWorkerSchedules(candidates=[{
        "id": str(source_id),
        "content": "PRIVATE roadmap decision and deadline",
    }])
    lease_token = stores.claim.lease_token
    processor = DailyScheduleProcessor(
        stores,
        replace(AISettings(), max_sources=1),
        FlareSettings(),
        WorkerSettings(),
        owner=uuid4(),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )
    with caplog.at_level("INFO"):
        assert asyncio.run(processor.process_one()) == "refresh_ready"
    assert stores.finished == [{"chunks": (source_id,)}]
    assert "PRIVATE" not in caplog.text
    assert str(lease_token) not in caplog.text


def test_scheduler_no_context_fails_closed_and_does_not_enqueue():
    stores = FakeWorkerSchedules()
    processor = DailyScheduleProcessor(
        stores, AISettings(), FlareSettings(), WorkerSettings(),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert asyncio.run(processor.process_one()) == "refresh_failed"
    assert stores.finished == [{"error": "no_eligible_context"}]
    assert stores.enqueued == []


def test_scheduler_logs_each_safe_scheduled_failure_without_payload(caplog):
    cycle_id = uuid4()
    stores = FakeWorkerSchedules(outcomes=[{
        "cycle_id": str(cycle_id),
        "status": "failed",
        "error_code": "source_invalid",
        "content": "PRIVATE customer payload",
    }])
    stores.claim = None
    processor = DailyScheduleProcessor(
        stores, AISettings(), FlareSettings(), WorkerSettings(),
        clock=lambda: datetime(2026, 1, 1, tzinfo=UTC),
    )
    with caplog.at_level("WARNING"):
        assert asyncio.run(processor.process_one()) == "scheduled_failed"
    assert str(cycle_id) in caplog.text
    assert "error_code=source_invalid" in caplog.text
    assert "PRIVATE" not in caplog.text


def test_migration_enforces_daily_uniqueness_rls_and_execute_only_worker(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "migrations/versions/0015_daily_analysis_schedule.py"
    spec = spec_from_file_location("daily_migration", path)
    migration = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)

    class Operation:
        def __init__(self): self.statements = []
        def execute(self, statement): self.statements.append(str(statement))

    operation = Operation()
    monkeypatch.setattr(migration, "op", operation)
    monkeypatch.setenv("FLARE_DATABASE_PROVIDER", "self-managed")
    migration.upgrade()
    sql = "\n".join(operation.statements)
    assert "analysis_cycles_workspace_local_date_key UNIQUE (workspace_id, local_date)" in sql
    assert "analysis_run_id uuid UNIQUE REFERENCES public.analysis_runs(id) ON DELETE CASCADE" in sql
    assert "LIMIT LEAST(p_max_sources * 4, 400)" in sql
    assert sql.count("FORCE ROW LEVEL SECURITY") == 4
    assert "CREATE TABLE public.analysis_daily_quotas" in sql
    assert "(r.created_at AT TIME ZONE 'UTC')::date" in sql
    assert "ON CONFLICT (workspace_id, local_date) DO NOTHING" in sql
    assert "CREATE TRIGGER analysis_cycle_quota_guard" in sql
    assert "GRANT SELECT ON public.analysis_cycles, public.analysis_cycle_sources TO flare_app" in sql
    assert "GRANT EXECUTE ON FUNCTION public.claim_analysis_cycle_refresh" in sql
    assert "TO flare_worker" in sql
    assert "GRANT SELECT" not in sql.split("TO flare_worker")[0][-200:]
    assert "CREATE OR REPLACE FUNCTION public.start_analysis_run" in sql
    assert "public.start_daily_analysis_run" in sql
    assert "c.scheduled_for-make_interval(mins=>30)>c.schedule_updated_at" in sql
    assert sql.count("Scheduler clock is outside tolerance") == 2
    assert "CREATE FUNCTION public.set_analysis_schedule" in sql
    assert "GRANT EXECUTE ON FUNCTION public.set_analysis_schedule" in sql
    assert "REVOKE INSERT,UPDATE,DELETE ON public.analysis_schedules FROM flare_app" in sql
    assert "REVOKE EXECUTE ON FUNCTION public.enqueue_analysis_job(uuid[],text,integer)" in sql
    assert "UPDATE public.analysis_jobs j" in sql
    assert "NOT EXISTS(SELECT 1 FROM public.analysis_runs r" in sql
    assert "UPDATE public.flare_generation_runs g" in sql
    assert "CREATE FUNCTION public.analysis_cycle_maintenance" in sql
    assert "CREATE FUNCTION public.activity_event_maintenance" in sql
    assert "GRANT SELECT,INSERT,DELETE ON public.activity_events" in sql
    assert "activity_events_workspace_actor_created_idx" in sql
    activity_maintenance = sql.index("CREATE FUNCTION public.activity_event_maintenance")
    assert sql.index("LIMIT p_max_rows", activity_maintenance) < sql.index(
        "CREATE FUNCTION public.queue_operational_health", activity_maintenance
    )
    assert "CREATE FUNCTION public.queue_operational_health" in sql
    assert "current_version.state='ready'" in sql
    assert "ORDER BY d.updated_at DESC,d.id DESC LIMIT 200" in sql
    assert "existing.scheduled_for>candidate.scheduled_for-interval '20 hours'" in sql
    assert "SELECT 1 FROM public.analysis_daily_quotas q" in sql
    assert "VALUES(cycle.workspace_id,cycle.requested_by_user_id,'analysis_requested'" in sql
    assert "'analysis_run',run_id,jsonb_build_object('mode','scheduled')" in sql
    assert "'screen_opened'" in sql

    materializer = sql.index("CREATE FUNCTION public.materialize_analysis_cycles")
    anti_conflict = sql.index("AND NOT EXISTS(SELECT 1 FROM public.analysis_daily_quotas existing", materializer)
    limited = sql.index("ORDER BY c.scheduled_for,c.workspace_id LIMIT p_limit", materializer)
    assert anti_conflict < limited

    for function, protected_query in (
        ("CREATE FUNCTION public.load_analysis_cycle_candidates", "SELECT 1 FROM public.auth_users"),
        ("CREATE FUNCTION public.finish_analysis_cycle_refresh", "PERFORM d.id FROM public.documents"),
        ("CREATE FUNCTION public.enqueue_due_analysis_cycles", "SELECT 1 FROM public.auth_users"),
    ):
        start = sql.index(function)
        context = sql.index("PERFORM set_config('app.workspace_id'", start)
        query = sql.index(protected_query, start)
        assert context < query


def test_daily_quota_table_is_part_of_runtime_readiness_fence():
    assert "analysis_daily_quotas" in database_module.TENANT_TABLES
    assert "UNION ALL SELECT 1 FROM public.analysis_daily_quotas" in inspect.getsource(
        database_module._connection_is_ready
    )
