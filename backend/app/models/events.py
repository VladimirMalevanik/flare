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

    def event_summary(self, workspace_id: UUID, since: datetime) -> list[EventSummary]:
        rows = self._connection.execute(
            self._SUMMARY_SQL,
            (workspace_id, since),
        ).fetchall()
        return [EventSummary(event_type=row["event_type"], count=row["count"]) for row in rows]
