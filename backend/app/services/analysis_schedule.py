"""Daily analysis schedule calculations and workspace-facing status."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.models.analysis_schedules import AnalysisScheduleRecord, AnalysisScheduleRepository


DEFAULT_TIMEZONE = "UTC"
DEFAULT_LOCAL_TIME = time(19, 0)
LEAD_MINUTES = 30


class InvalidSchedule(ValueError):
    pass


@dataclass(frozen=True)
class ScheduleWindow:
    run_at: datetime
    refresh_at: datetime


def validate_timezone(name: str) -> ZoneInfo:
    if not isinstance(name, str) or not name or len(name) > 80:
        raise InvalidSchedule("invalid_timezone")
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise InvalidSchedule("invalid_timezone") from None


def parse_local_time(value: str) -> time:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        raise InvalidSchedule("invalid_local_time")
    try:
        hour, minute = (int(part) for part in value.split(":"))
        return time(hour, minute)
    except (TypeError, ValueError):
        raise InvalidSchedule("invalid_local_time") from None


def _resolve_wall_time(day: date, wall_time: time, zone: ZoneInfo) -> datetime:
    """Match PostgreSQL AT TIME ZONE for DST gaps and overlaps."""
    naive = datetime.combine(day, wall_time)
    first = naive.replace(tzinfo=zone, fold=0)
    second = naive.replace(tzinfo=zone, fold=1)
    first_roundtrip = first.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
    second_roundtrip = second.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)
    if first_roundtrip == naive and second_roundtrip == naive and first.utcoffset() != second.utcoffset():
        # PostgreSQL selects the standard-time occurrence in an overlap.
        return second
    # For a gap PostgreSQL applies the pre-transition offset, which maps the
    # requested wall time forward by the size of the gap.
    return first


def next_schedule_window(
    *,
    now: datetime,
    timezone_name: str,
    local_time: time,
    not_before: datetime | None = None,
) -> ScheduleWindow:
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    if not_before is not None and not_before.tzinfo is None:
        raise ValueError("not_before must be timezone-aware")
    zone = validate_timezone(timezone_name)
    local_now = now.astimezone(zone)
    run_day = local_now.date()
    run_at = _resolve_wall_time(run_day, local_time, zone)
    now_utc = now.astimezone(timezone.utc)
    run_utc = run_at.astimezone(timezone.utc)
    if run_utc <= now_utc or run_utc - timedelta(minutes=LEAD_MINUTES) <= now_utc:
        run_day += timedelta(days=1)
        run_utc = _resolve_wall_time(run_day, local_time, zone).astimezone(timezone.utc)
    earliest = not_before.astimezone(timezone.utc) if not_before is not None else None
    while earliest is not None and run_utc < earliest:
        run_day += timedelta(days=1)
        run_utc = _resolve_wall_time(run_day, local_time, zone).astimezone(timezone.utc)
    return ScheduleWindow(run_at=run_utc, refresh_at=run_utc - timedelta(minutes=LEAD_MINUTES))


def local_day(now: datetime, timezone_name: str) -> date:
    return now.astimezone(validate_timezone(timezone_name)).date()


class AnalysisScheduleService:
    def __init__(self, repository: AnalysisScheduleRepository, *, clock=None):
        self._repository = repository
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def get(self) -> dict:
        record = self._repository.get()
        if record is None:
            record = AnalysisScheduleRecord(
                enabled=False,
                timezone=DEFAULT_TIMEZONE,
                local_time=DEFAULT_LOCAL_TIME,
                lead_minutes=LEAD_MINUTES,
                email_notifications_enabled=True,
                updated_at=self._clock(),
            )
        return self._schedule_response(record)

    def put(
        self,
        *,
        enabled: bool,
        timezone_name: str,
        local_time_value: str,
        email_notifications_enabled: bool = True,
    ) -> dict:
        validate_timezone(timezone_name)
        parsed = parse_local_time(local_time_value)
        record = self._repository.put(
            enabled=enabled,
            timezone_name=timezone_name,
            local_time=parsed,
            email_notifications_enabled=email_notifications_enabled,
        )
        return self._schedule_response(record)

    def daily_status(self) -> dict:
        now = self._clock()
        schedule = self._repository.get()
        timezone_name = schedule.timezone if schedule else DEFAULT_TIMEZONE
        day = local_day(now, timezone_name)
        cycle = self._repository.daily_cycle(day)
        connected = self._repository.github_connected()
        github = {
            "connected": connected,
            "ingestionSupported": False,
            "status": "not_ingested" if connected else "not_connected",
        }
        if cycle is None:
            return {
                "localDate": day.isoformat(),
                "timezone": timezone_name,
                "state": "available",
                "cycleId": None,
                "runId": None,
                "mode": None,
                "scheduledFor": None,
                "refreshDueAt": None,
                "sourceSnapshotCount": 0,
                "canRequestToday": True,
                "reason": None,
                "sync": {"status": "not_started", "github": github},
            }
        state, reason = _cycle_state(cycle)
        sync_status = (
            "unknown"
            if cycle.get("quota_only", False)
            else _sync_status(cycle["refresh_status"])
        )
        return {
            "localDate": day.isoformat(),
            "timezone": timezone_name,
            "state": state,
            "cycleId": cycle["cycle_id"],
            "runId": cycle["run_id"],
            "mode": cycle["mode"],
            "scheduledFor": cycle["scheduled_for"],
            "refreshDueAt": cycle["refresh_due_at"],
            "sourceSnapshotCount": cycle["snapshot_chunk_count"],
            "canRequestToday": False,
            "reason": reason,
            "sync": {"status": sync_status, "github": github},
        }

    def _schedule_response(self, record: AnalysisScheduleRecord) -> dict:
        now = self._clock()
        next_refresh_at = None
        next_run_at = None
        if record.enabled:
            cycle = self._repository.daily_cycle(local_day(now, record.timezone))
            if (
                cycle is not None
                and not cycle.get("quota_only", False)
                and cycle["mode"] == "scheduled"
                and cycle["refresh_status"] != "failed"
                and cycle["scheduled_for"] > now
            ):
                # Once T-30 has materialized the durable cycle, expose that
                # exact promise instead of previewing tomorrow's wall time.
                next_refresh_at = cycle["refresh_due_at"]
                next_run_at = cycle["scheduled_for"]
            else:
                not_before = None
                if cycle is not None:
                    not_before = cycle["scheduled_for"] + timedelta(hours=20)
                    if cycle.get("local_date_consumed", False):
                        zone = validate_timezone(record.timezone)
                        next_day_start = _resolve_wall_time(
                            local_day(now, record.timezone) + timedelta(days=1),
                            time.min,
                            zone,
                        ).astimezone(timezone.utc)
                        not_before = max(not_before, next_day_start)
                window = next_schedule_window(
                    now=now,
                    timezone_name=record.timezone,
                    local_time=record.local_time,
                    not_before=not_before,
                )
                next_refresh_at = window.refresh_at
                next_run_at = window.run_at
        return {
            "enabled": record.enabled,
            "timezone": record.timezone,
            "localTime": record.local_time.strftime("%H:%M"),
            "leadMinutes": LEAD_MINUTES,
            "emailNotificationsEnabled": record.email_notifications_enabled,
            "nextRefreshAt": next_refresh_at,
            "nextRunAt": next_run_at,
            "updatedAt": record.updated_at,
        }


def _sync_status(refresh_status: str) -> str:
    return {
        "scheduled": "not_started",
        "refreshing": "running",
        "ready": "succeeded",
        "failed": "failed",
    }[refresh_status]


def _cycle_state(cycle: dict) -> tuple[str, str | None]:
    if cycle.get("quota_only", False):
        # Detailed queue/run history may have reached retention, while the
        # durable daily quota tombstone still keeps this local day consumed.
        return "consumed", "daily_limit"
    refresh = cycle["refresh_status"]
    if refresh == "failed":
        error = cycle.get("last_error_code")
        reason = "no_eligible_context" if error == "no_eligible_context" else "sync_failed"
        return "failed", reason
    if refresh == "scheduled":
        return "scheduled", "daily_limit"
    if refresh == "refreshing":
        return "refreshing", "daily_limit"
    if cycle.get("run_id") is None:
        return "ready", "daily_limit"
    run = cycle.get("run_status")
    if run == "failed":
        return "failed", "sync_failed"
    if run == "completed":
        return "completed", "daily_limit"
    if run == "processing":
        return "processing", "daily_limit"
    return "queued", "daily_limit"
