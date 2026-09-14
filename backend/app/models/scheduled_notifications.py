"""Worker-only capabilities for scheduled-analysis notification delivery."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.models.analysis_jobs import WorkerJobs


@dataclass(frozen=True)
class ScheduledNotificationClaim:
    id: UUID
    workspace_id: UUID
    analysis_run_id: UUID
    requested_by_user_id: str
    flare_ids: list[UUID]
    status: str
    attempts: int
    max_attempts: int
    available_at: datetime
    lease_owner: UUID
    lease_token: UUID
    lease_expires_at: datetime
    last_error_code: str | None
    created_at: datetime
    updated_at: datetime
    sent_at: datetime | None


class ScheduledNotificationJobs(WorkerJobs):
    def claim(self, owner: UUID, lease_seconds: int) -> ScheduledNotificationClaim | None:
        row = self._call(
            "SELECT * FROM public.claim_scheduled_flare_notification(%s,%s)",
            (owner, lease_seconds),
        )
        return ScheduledNotificationClaim(**row) if row else None

    def load(self, claim: ScheduledNotificationClaim) -> dict:
        row = self._call(
            "SELECT public.load_scheduled_flare_notification(%s,%s) AS value",
            (claim.id, claim.lease_token),
        )
        return row["value"]

    def finish(
        self,
        claim: ScheduledNotificationClaim,
        *,
        error: str | None = None,
        retry_seconds: float | None = None,
    ) -> str:
        row = self._call(
            "SELECT public.finish_scheduled_flare_notification(%s,%s,%s,%s) AS value",
            (claim.id, claim.lease_token, error, retry_seconds),
        )
        return row["value"]
