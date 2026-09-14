import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.services.email import scheduled_flares_message
from app.services.scheduled_email import ScheduledNotificationProcessor
from app.workers.config import WorkerSettings


class FakeJobs:
    def __init__(self, payload):
        self.claimed = SimpleNamespace(
            id=uuid4(), lease_token=uuid4(), attempts=1
        )
        self.payload = payload
        self.finished = []

    def claim(self, owner, lease_seconds):
        assert owner and lease_seconds == 120
        claim, self.claimed = self.claimed, None
        return claim

    def load(self, claim):
        return self.payload

    def finish(self, claim, *, error=None, retry_seconds=None):
        self.finished.append((error, retry_seconds))
        return "sent" if error is None else "failed"


class CapturingSender:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.sent = []

    def send(self, **message):
        if self.fail:
            raise OSError("SMTP unavailable")
        self.sent.append(message)


def test_message_contains_only_titles_and_links():
    flare_id = str(uuid4())
    subject, body = scheduled_flares_message(
        "https://app.flare.test/", ((flare_id, "  Review   launch risk "),)
    )
    assert subject == "Flare found something worth checking"
    assert "Review launch risk" in body
    assert f"https://app.flare.test/insights?insight={flare_id}" in body
    for private_text in ("private note body", "customer quote", "hidden reasoning", "source transcript"):
        assert private_text not in body


def test_processor_sends_one_email_for_nonempty_payload():
    payload = {
        "recipient": "verified@example.test",
        "flares": [
            {"id": str(uuid4()), "title": "First Flare"},
            {"id": str(uuid4()), "title": "Second Flare"},
        ],
    }
    jobs = FakeJobs(payload)
    sender = CapturingSender()
    processor = ScheduledNotificationProcessor(
        jobs, sender, "https://app.flare.test", WorkerSettings()
    )

    assert asyncio.run(processor.process_one()) == "sent"
    assert len(sender.sent) == 1
    assert sender.sent[0]["to"] == "verified@example.test"
    assert jobs.finished == [(None, None)]


def test_processor_never_sends_disabled_or_invalid_notifications():
    for payload in ({"error": "notifications_disabled"}, {"recipient": "x", "flares": []}):
        jobs = FakeJobs(payload)
        sender = CapturingSender()
        processor = ScheduledNotificationProcessor(
            jobs, sender, "https://app.flare.test", WorkerSettings()
        )
        assert asyncio.run(processor.process_one()) == "failed"
        assert sender.sent == []
        assert jobs.finished[0][0] in {"notifications_disabled", "invalid_payload"}


def test_processor_retries_delivery_failure_without_exposing_payload():
    jobs = FakeJobs({
        "recipient": "verified@example.test",
        "flares": [{"id": str(uuid4()), "title": "Private project title"}],
    })
    processor = ScheduledNotificationProcessor(
        jobs, CapturingSender(fail=True), "https://app.flare.test",
        WorkerSettings(backoff_seconds=5, max_backoff_seconds=30),
    )
    assert asyncio.run(processor.process_one()) == "failed"
    assert jobs.finished == [("delivery_failed", 5.0)]
