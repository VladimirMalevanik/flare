"""Persist an already validated transcript while keeping source audio transient."""

from __future__ import annotations

from app.ai_engine.voice import Transcript
from app.models.database import Database, WorkspaceIdentity
from app.models.tables import ItemRecord
from app.services.analytics_service import AnalyticsService, track_event_best_effort
from app.services.item_service import ItemService


class VoiceTranscriptService:
    """The DB half of voice capture; this class never receives or stores audio."""

    def __init__(
        self,
        database: Database,
        identity: WorkspaceIdentity,
        *,
        item_service: ItemService | None = None,
        analytics: AnalyticsService | None = None,
        max_upload_bytes: int = 10 * 1024 * 1024,
    ):
        self._item_service = item_service or ItemService(database, identity)
        self._analytics = analytics or AnalyticsService(database, identity)
        self._max_upload_bytes = max_upload_bytes

    def persist(
        self,
        transcript: Transcript,
        *,
        media_type: str,
        upload_size: int,
    ) -> ItemRecord:
        if not isinstance(transcript, Transcript):
            raise TypeError("A validated transcript is required")
        if media_type not in {
            "audio/webm",
            "audio/wav",
            "audio/mpeg",
            "audio/mp4",
            "audio/ogg",
        }:
            raise ValueError("Unsupported audio type")
        if (
            type(upload_size) is not int
            or upload_size <= 0
            or upload_size > self._max_upload_bytes
        ):
            raise ValueError("Invalid upload size")

        extension = {
            "audio/webm": "webm",
            "audio/wav": "wav",
            "audio/mpeg": "mp3",
            "audio/mp4": "m4a",
            "audio/ogg": "ogg",
        }[media_type]
        item = self._item_service.create_item(
            item_type="audio",
            title=None,
            content=transcript.text,
            source_url=None,
            file_name=f"voice-memo.{extension}",
            file_size=upload_size,
            file_type=media_type,
        )
        track_event_best_effort(
            self._analytics,
            event_type="item_created",
            target_type="item",
            target_id=str(item.id),
            metadata={"item_type": "audio"},
        )
        return item
