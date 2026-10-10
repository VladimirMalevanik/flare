"""Offline HTTP regressions for voice authorization and async persistence."""

import asyncio
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from threading import Event, get_ident
from types import SimpleNamespace
from uuid import UUID

from fastapi import FastAPI
import httpx
import pytest

from app.ai_engine.voice import Transcript
from app.ai_engine.voice_config import VoiceSettings
from app.api import voice
from app.api.auth import verified_user
from app.models.database import Database
from app.models.tables import ItemRecord
from app.services import analytics_service, item_service
from app.services.auth_service import AuthenticatedUser


AUDIO = b"\x1aE\xdf\xa3test"
WORDS = "A validated voice transcript."
OWNER = AuthenticatedUser(
    user_id="auth:api003-voice",
    workspace_id=UUID("00000000-0000-4000-8000-000000000003"),
    email="voice@example.invalid",
    name="Voice test",
    role="owner",
    workspace_name="Voice workspace",
)


class OfflineStore:
    """Replace SQL storage while retaining Database's actual membership checks."""

    def __init__(self):
        self.role = "owner"
        self.document = None
        self.version = None
        self.chunk = None
        self.events = []
        self.provider_calls = []
        self.revoked_role = "unchanged"
        self.block_phase = None
        self.started = Event()
        self.release = Event()
        self.finished = Event()
        self.released_while_blocked = False
        self.thread_ids = {}

    def pause(self, phase):
        self.thread_ids[phase] = get_ident()
        if self.block_phase == phase:
            self.started.set()
            self.released_while_blocked = self.release.wait(timeout=1)
            self.finished.set()


class OfflineConnection:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def transaction(self):
        yield

    def execute(self, statement, parameters=None):
        membership = "SELECT role FROM public.workspace_members" in statement
        row = {"role": self.store.role} if membership and self.store.role is not None else None
        return SimpleNamespace(fetchone=lambda: row)


class OfflinePool:
    def __init__(self, store):
        self.store = store

    @contextmanager
    def connection(self):
        yield OfflineConnection(self.store)


class RecordingItems:
    def __init__(self, connection):
        self.store = connection.store

    def insert_document(self, **values):
        self.store.pause("item")
        self.store.document = values

    def insert_version(self, **values):
        self.store.version = values

    def insert_chunk(self, **values):
        self.store.chunk = values

    def publish_version(self, **values):
        assert values["version_id"] == self.store.version["version_id"]

    def get_active(self, item_id):
        document, version = self.store.document, self.store.version
        assert item_id == document["item_id"]
        now = datetime.now(timezone.utc)
        return ItemRecord(
            id=item_id,
            item_type=document["item_type"],
            title=document["title"],
            content=self.store.chunk["content"],
            source_url=document["source_url"],
            metadata=document["metadata"],
            state="ready",
            parser_version=version["parser_version"],
            current_version_id=version["version_id"],
            version_number=1,
            created_at=now,
            updated_at=now,
        )


class RecordingEvents:
    def __init__(self, connection):
        self.store = connection.store

    def insert(self, **event):
        self.store.pause("analytics")
        self.store.events.append(event)


@pytest.fixture
def harness(monkeypatch):
    store = OfflineStore()
    database = Database.__new__(Database)
    database._pool = OfflinePool(store)
    monkeypatch.setattr(item_service, "ItemRepository", RecordingItems)
    monkeypatch.setattr(analytics_service, "ActivityEventRepository", RecordingEvents)
    monkeypatch.setattr(voice, "load_voice_settings", lambda: VoiceSettings(api_key="test-only-key"))

    class Inspector:
        def __init__(self, **settings):
            pass

        async def duration_seconds(self, audio):
            assert audio.content == AUDIO
            return 1

    class Transcriber:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def transcribe(self, audio):
            store.provider_calls.append(audio)
            if store.revoked_role != "unchanged":
                store.role = store.revoked_role
            return Transcript(WORDS)

    monkeypatch.setattr(voice, "FfprobeMediaInspector", Inspector)
    monkeypatch.setattr(voice, "create_voice_transcriber", Transcriber)

    def app_for(user):
        app = FastAPI()
        app.state.database = database
        app.include_router(voice.router)
        app.dependency_overrides[verified_user] = lambda: user
        return app

    return store, app_for


async def post_audio(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.post(
            "/voice/transcribe", content=AUDIO, headers={"Content-Type": "audio/webm;codecs=opus"}
        )


@pytest.mark.parametrize("role", ["viewer", "unknown", ""])
def test_nonwriters_rejected_before_settings_upload_inspection_or_provider(harness, monkeypatch, role):
    store, app_for = harness

    def forbidden(*args, **kwargs):
        pytest.fail("A nonwriter reached voice processing")

    for name in (
        "load_voice_settings", "_read_bounded_audio", "FfprobeMediaInspector",
        "create_voice_transcriber", "VoiceTranscriptService",
    ):
        monkeypatch.setattr(voice, name, forbidden)

    response = asyncio.run(post_audio(app_for(replace(OWNER, role=role))))
    assert response.status_code == 403
    assert response.json() == {"detail": "Workspace write permission is required"}
    assert store.document is None and store.events == [] and store.provider_calls == []


@pytest.mark.parametrize("role", ["owner", "editor"])
def test_writers_receive_durable_transcript_and_safe_analytics(harness, role):
    store, app_for = harness
    store.role = role
    response = asyncio.run(post_audio(app_for(replace(OWNER, role=role))))

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "audio" and body["status"] == "ready"
    assert body["content"] == WORDS and body["fileSize"] == len(AUDIO)
    assert body["fileName"] == "voice-memo.webm" and body["fileType"] == "audio/webm"
    assert store.document["workspace_id"] == OWNER.workspace_id
    assert store.version["parser_version"] == "ingest-audio-v1"
    assert len(store.provider_calls) == 1
    assert len(store.events) == 1
    assert store.events[0]["event_type"] == "item_created"
    assert store.events[0]["metadata"] == {"item_type": "audio"}
    assert repr(AUDIO) not in repr((store.document, store.version, store.chunk, store.events))


@pytest.mark.parametrize("revoked_role,detail", [
    (None, "Workspace membership is required"),
    ("viewer", "Workspace write permission is required"),
])
def test_permission_revoked_during_transcription_is_403_without_item_write(harness, revoked_role, detail):
    store, app_for = harness
    store.revoked_role = revoked_role
    response = asyncio.run(post_audio(app_for(OWNER)))

    assert response.status_code == 403
    assert response.json() == {"detail": detail}
    assert len(store.provider_calls) == 1
    assert store.document is None and store.version is None and store.chunk is None
    assert store.events == []


@pytest.mark.parametrize("phase", ["item", "analytics"])
def test_async_heartbeat_runs_while_synchronous_persistence_is_blocked(harness, phase):
    store, app_for = harness
    store.block_phase = phase

    async def exercise():
        loop_thread = get_ident()
        request = asyncio.create_task(post_audio(app_for(OWNER)))
        heartbeats_during_block = 0
        try:
            while not request.done():
                if store.started.is_set() and not store.finished.is_set():
                    heartbeats_during_block += 1
                    if heartbeats_during_block >= 3:
                        store.release.set()
                await asyncio.sleep(0.001)
            response = await request
        finally:
            store.release.set()
        assert response.status_code == 200
        assert store.released_while_blocked
        assert heartbeats_during_block >= 3
        assert store.thread_ids["item"] != loop_thread
        assert store.thread_ids["analytics"] != loop_thread
        assert len(store.events) == 1

    asyncio.run(exercise())
