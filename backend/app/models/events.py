"""User interaction events used for product analytics and feature adoption."""

from datetime import datetime
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class EventSummary:
    event_type: str
    count: int


@dataclass(frozen=True)
class ActivityEvent:
    id: UUID
    workspace_id: UUID
    actor_id: str
    event_type: str
    target_type: str | None
    target_id: UUID | None
    metadata: dict[str, Any]
    created_at: datetime


class ActivityEventRepository:
    """Write-only analytics sink for important business actions."""

    _INSERT_SQL = """
        INSERT INTO public.activity_events
            (workspace_id, actor_id, event_type, target_type, target_id, metadata)
        VALUES (%s, %s, %s, %s, %s, %s::jsonb)
    """

    _SUMMARY_SQL = """
        SELECT event_type, count(*)::int AS count
        FROM public.activity_events
        WHERE workspace_id = %s
          AND created_at >= %s
        GROUP BY event_type
        ORDER BY event_type
    """

    def __init__(self, connection):
        self._connection = connection

    def insert(
        self,
        *,
        workspace_id: UUID,
        actor_id: str,
        event_type: str,
        target_type: str | None,
        target_id: UUID | None,
        metadata: dict[str, Any],
    ) -> None:
        self._connection.execute(
            self._INSERT_SQL,
            (workspace_id, actor_id, event_type, target_type, target_id, Jsonb(metadata)),
        )

    def client_target_exists(
        self,
        *,
        workspace_id: UUID,
        event_type: str,
        target_id: UUID,
        source_type: str | None,
    ) -> bool:
        if event_type in {"capture_submitted", "item_viewed"}:
            row = self._connection.execute(
                """SELECT EXISTS(
                       SELECT 1 FROM public.documents
                        WHERE workspace_id=%s AND id=%s AND deleted_at IS NULL
                          AND source_type=%s
                   ) AS value""",
                (workspace_id, target_id, source_type),
            ).fetchone()
        elif event_type == "flare_viewed":
            row = self._connection.execute(
                """SELECT EXISTS(
                       SELECT 1 FROM public.insights
                        WHERE workspace_id=%s AND id=%s
                   ) AS value""",
                (workspace_id, target_id),
            ).fetchone()
        else:
            return True
        return bool(row and row["value"])

    def reserve_client_event_slot(
        self,
        *,
        workspace_id: UUID,
        actor_id: str,
        max_events_per_hour: int,
    ) -> bool:
        # Serialize only this actor's small telemetry budget. The lock and
        # count share the insertion transaction, so concurrent browser tabs
        # cannot race past the bound.
        lock_key = f"{workspace_id}:{actor_id}:client-activity-events"
        self._connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
            (lock_key,),
        )
        row = self._connection.execute(
            """SELECT count(*)::int AS value
                 FROM public.activity_events
                WHERE workspace_id=%s AND actor_id=%s
                  AND created_at>=clock_timestamp()-interval '1 hour'""",
            (workspace_id, actor_id),
        ).fetchone()
        return bool(row and row["value"] < max_events_per_hour)

    def event_summary(self, workspace_id: UUID, since: datetime) -> list[EventSummary]:
        rows = self._connection.execute(
            self._SUMMARY_SQL,
            (workspace_id, since),
        ).fetchall()
        return [EventSummary(event_type=row["event_type"], count=row["count"]) for row in rows]
