from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.ai_engine.voice import Transcript
from app.models.database import WorkspaceIdentity
from app.models.tables import ItemRecord
from app.services.voice_service import VoiceTranscriptService


def record() -> ItemRecord:
    now = datetime.now(timezone.utc)
    item_id, version_id = uuid4(), uuid4()
    return ItemRecord(
        id=item_id,
        item_type="audio",
        title="Validated words",
        content="Validated words",
        source_url=None,
        metadata={
            "sourceType": "audio",
            "fileName": "voice-memo.webm",
            "fileSize": 8,
            "fileType": "audio/webm",
        },
        state="ready",
        parser_version="ingest-audio-v1",
        current_version_id=version_id,
        version_number=1,
        created_at=now,
        updated_at=now,
    )


class Items:
    def __init__(self):
        self.calls = []

    def create_item(self, **values):
        self.calls.append(values)
        return record()


class Analytics:
    def __init__(self):
        self.events = []

    def track_event(self, **event):
        self.events.append(event)


def service():
    items, analytics = Items(), Analytics()
    instance = VoiceTranscriptService(
        object(),
        WorkspaceIdentity(uuid4(), "voice-test-user"),
        item_service=items,
        analytics=analytics,
    )
    return instance, items, analytics


def test_persists_only_validated_transcript_as_audio_item_and_tracks_safe_outcome():
    instance, items, analytics = service()
    saved = instance.persist(
        Transcript("  Validated words  "),
        media_type="audio/webm",
        upload_size=8,
    )

    assert saved.content == "Validated words"
    assert items.calls == [{
        "item_type": "audio",
        "title": None,
        "content": "Validated words",
        "source_url": None,
        "file_name": "voice-memo.webm",
        "file_size": 8,
        "file_type": "audio/webm",
    }]
    assert analytics.events == [{
        "event_type": "item_created",
        "target_type": "item",
        "target_id": str(saved.id),
        "metadata": {"item_type": "audio"},
    }]
    assert "audio" not in instance.__dict__


@pytest.mark.parametrize(
    "transcript,media_type,upload_size",
    [
        ("raw text", "audio/webm", 8),
        (Transcript("valid"), "video/webm", 8),
        (Transcript("valid"), "audio/webm", 0),
        (Transcript("valid"), "audio/webm", True),
        (Transcript("valid"), "audio/webm", 10 * 1024 * 1024 + 1),
    ],
)
def test_rejects_unvalidated_or_invalid_persistence_metadata(
    transcript, media_type, upload_size
):
    instance, items, analytics = service()
    with pytest.raises((TypeError, ValueError)):
        instance.persist(
            transcript,
            media_type=media_type,
            upload_size=upload_size,
        )
    assert items.calls == []
    assert analytics.events == []
