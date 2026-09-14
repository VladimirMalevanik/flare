"""Fast schedule, DST, orchestration and migration-contract checks."""

import asyncio
from dataclasses import replace
from datetime import date, datetime, time, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from uuid import uuid4

import pytest

from app.ai_engine.flare_config import FlareSettings
from app.config import AISettings
from app.models.analysis_schedules import AnalysisScheduleRecord, RefreshClaim
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
    assert default["nextRunAt"] is None

    updated = service.put(enabled=True, timezone_name="Europe/Moscow", local_time_value="18:45")
    assert repository.put_args == {
        "enabled": True,
        "timezone_name": "Europe/Moscow",
        "local_time": time(18, 45),
    }
    assert updated["leadMinutes"] == 30
    assert updated["nextRunAt"] == datetime(2026, 1, 1, 15, 45, tzinfo=UTC)


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


class FakeWorkerSchedules:
    def __init__(self, *, candidates=None):
        self.claim = RefreshClaim(uuid4(), uuid4(), "user", uuid4(), datetime(2026, 1, 1, 1, tzinfo=UTC), 1)
        self.loaded = {"candidates": candidates or []}
        self.finished = []
        self.enqueued = []

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
        return []


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
    assert sql.count("FORCE ROW LEVEL SECURITY") == 3
    assert "GRANT SELECT ON public.analysis_cycles, public.analysis_cycle_sources TO flare_app" in sql
    assert "GRANT EXECUTE ON FUNCTION public.claim_analysis_cycle_refresh" in sql
    assert "TO flare_worker" in sql
    assert "GRANT SELECT" not in sql.split("TO flare_worker")[0][-200:]
    assert "CREATE OR REPLACE FUNCTION public.start_analysis_run" in sql
    assert "public.start_daily_analysis_run" in sql
    assert "c.scheduled_for-make_interval(mins=>30)>=" in sql
