"""Materialize daily cycles, freeze fresh sources and enqueue due analysis."""

import asyncio
from datetime import datetime, timezone
import logging
from uuid import UUID, uuid4

from app.ai_engine.flare_config import FlareSettings
from app.config import AISettings
from app.models.analysis_schedules import WorkerAnalysisSchedules
from app.services.context_selection import select_context
from app.workers.config import WorkerSettings, pipeline_revision


logger = logging.getLogger(__name__)


class DailyScheduleProcessor:
    """One bounded scheduler step suitable for the existing single worker loop."""

    def __init__(
        self,
        schedules: WorkerAnalysisSchedules,
        ai: AISettings,
        flare: FlareSettings,
        settings: WorkerSettings,
        *,
        owner: UUID | None = None,
        clock=None,
    ):
        settings.validate(ai)
        flare.validate()
        self.schedules = schedules
        self.ai = ai
        self.flare = flare
        self.settings = settings
        self.owner = owner or uuid4()
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    async def process_one(self) -> str | None:
        now = self._clock()
        materialized = await asyncio.to_thread(self.schedules.materialize, now)
        claim = await asyncio.to_thread(
            self.schedules.claim_refresh,
            self.owner,
            self.settings.lease_seconds,
        )
        if claim is not None:
            logger.info(
                "analysis_refresh status=started cycle_id=%s workspace_id=%s attempt=%s",
                claim.cycle_id,
                claim.workspace_id,
                claim.attempts,
            )
            loaded = await asyncio.to_thread(
                self.schedules.candidates,
                claim,
                min(self.ai.max_sources, 100),
                self.ai.max_input_bytes,
            )
            if loaded.get("error"):
                error = loaded["error"]
                status = await asyncio.to_thread(
                    self.schedules.finish_refresh,
                    claim,
                    error=error if error in {"authorization_revoked", "source_invalid"} else "internal_error",
                    retry_seconds=(5.0 if error not in {"authorization_revoked"} else None),
                )
                logger.warning(
                    "analysis_refresh status=%s cycle_id=%s workspace_id=%s error_code=%s",
                    status,
                    claim.cycle_id,
                    claim.workspace_id,
                    error,
                )
                return "refresh_" + status
            candidates = loaded.get("candidates")
            selected = select_context(candidates if isinstance(candidates, list) else [], self.ai)
            if not selected:
                status = await asyncio.to_thread(
                    self.schedules.finish_refresh,
                    claim,
                    error="no_eligible_context",
                )
                logger.warning(
                    "analysis_refresh status=%s cycle_id=%s workspace_id=%s error_code=no_eligible_context",
                    status,
                    claim.cycle_id,
                    claim.workspace_id,
                )
                return "refresh_" + status
            status = await asyncio.to_thread(
                self.schedules.finish_refresh,
                claim,
                chunks=tuple(UUID(item.source_id) for item in selected),
            )
            logger.info(
                "analysis_refresh status=%s cycle_id=%s workspace_id=%s source_count=%s",
                status,
                claim.cycle_id,
                claim.workspace_id,
                len(selected),
            )
            return "refresh_" + status
        outcomes = await asyncio.to_thread(
            self.schedules.enqueue_due,
            pipeline_revision=pipeline_revision(self.ai),
            generation_revision=self.flare.revision(self.ai),
            max_attempts=self.settings.max_attempts,
            now=now,
        )
        if outcomes:
            queued_count = 0
            for outcome in outcomes:
                if outcome.get("status") == "queued":
                    queued_count += 1
                    logger.info(
                        "analysis_schedule status=queued cycle_id=%s run_id=%s",
                        outcome.get("cycle_id"),
                        outcome.get("run_id"),
                    )
                else:
                    logger.warning(
                        "analysis_schedule status=failed cycle_id=%s error_code=%s",
                        outcome.get("cycle_id"),
                        outcome.get("error_code", "internal_error"),
                    )
            return "scheduled_queued" if queued_count else "scheduled_failed"
        return "cycle_materialized" if materialized else None
