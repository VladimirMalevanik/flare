"""Deliver one privacy-minimal email for a completed scheduled Flare run."""

import asyncio
import math
from uuid import UUID, uuid4

from app.models.scheduled_notifications import ScheduledNotificationJobs
from app.services.email import EmailSender, scheduled_flares_message
from app.workers.config import WorkerSettings


class ScheduledNotificationProcessor:
    def __init__(
        self,
        jobs: ScheduledNotificationJobs,
        sender: EmailSender | None,
        app_public_url: str | None,
        settings: WorkerSettings,
        *,
        owner: UUID | None = None,
    ):
        self.jobs = jobs
        self.sender = sender
        self.app_public_url = app_public_url.rstrip("/") if app_public_url else None
        self.settings = settings
        self.owner = owner or uuid4()

    async def process_one(self) -> str | None:
        claim = await asyncio.to_thread(
            self.jobs.claim, self.owner, self.settings.lease_seconds
        )
        if claim is None:
            return None
        loaded = await asyncio.to_thread(self.jobs.load, claim)
        error = loaded.get("error") if isinstance(loaded, dict) else "invalid_payload"
        if error:
            safe_error = error if error in {"invalid_payload", "notifications_disabled"} else "invalid_payload"
            return await asyncio.to_thread(self.jobs.finish, claim, error=safe_error)
        if self.sender is None or self.app_public_url is None:
            return await asyncio.to_thread(
                self.jobs.finish, claim, error="delivery_unavailable"
            )
        try:
            recipient = loaded["recipient"]
            raw_flares = loaded["flares"]
            if not isinstance(recipient, str) or not isinstance(raw_flares, list) or not raw_flares:
                raise ValueError("invalid notification payload")
            flares = tuple((str(item["id"]), str(item["title"])) for item in raw_flares)
            subject, body = scheduled_flares_message(self.app_public_url, flares)
            await asyncio.to_thread(
                self.sender.send,
                to=recipient,
                subject=subject,
                text=body,
            )
        except (KeyError, TypeError, ValueError):
            return await asyncio.to_thread(
                self.jobs.finish, claim, error="invalid_payload"
            )
        except Exception:
            delay = min(
                self.settings.max_backoff_seconds,
                self.settings.backoff_seconds * math.pow(2, claim.attempts - 1),
            )
            return await asyncio.to_thread(
                self.jobs.finish,
                claim,
                error="delivery_failed",
                retry_seconds=delay,
            )
        return await asyncio.to_thread(self.jobs.finish, claim)
