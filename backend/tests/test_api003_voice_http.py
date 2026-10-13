"""Voice HTTP authorization and persistence with cookie auth and PostgreSQL."""

from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from app.ai_engine.voice import AudioInput, Transcript
from app.ai_engine.voice_config import VoiceSettings
from app.api import voice
from app.config import Settings
from app.main import create_app
from test_items_api import ApiEnvironment, _required_urls


pytestmark = pytest.mark.integration
ORIGIN = "http://testserver"
AUDIO = b"\x1aE\xdf\xa3test"
WORDS = "An authenticated voice memo persisted through the HTTP endpoint."


@pytest.fixture
def authenticated_client():
    runtime_url, admin_url = _required_urls()
    environment = ApiEnvironment(runtime_url, admin_url)
    email = f"{uuid4()}@api003-voice.invalid"
    configured = Settings(
        database_url=runtime_url,
        environment="test",
        cors_origins=[ORIGIN],
        dev_mode=False,
        email_verification_required=False,
    )
    try:
        with TestClient(create_app(configured), headers={"Origin": ORIGIN}) as client:
            response = client.post("/auth/register", json={
                "email": email,
                "password": "synthetic-api003-voice-password",
                "name": "Voice HTTP regression",
                "termsAccepted": True,
                "privacyAccepted": True,
            })
            assert response.status_code == 201, response.text
            assert client.cookies.get(configured.session_cookie_name)
            response = client.get("/auth/me")
            assert response.status_code == 200, response.text
            identity = response.json()
            workspace_id = UUID(identity["workspace"]["id"])
            user_id = identity["user"]["id"]
            yield client, environment, workspace_id, user_id
    finally:
        # Collect this fixture's account even if setup failed after registration.
        with psycopg.connect(admin_url) as connection:
            row = connection.execute(
                "SELECT id,initial_workspace_id FROM public.auth_users WHERE email=%s",
                (email,),
            ).fetchone()
        if row:
            environment.user_ids.add(row[0])
            environment.workspace_ids.add(row[1])
        environment.cleanup()


@dataclass
class VoiceBoundary:
    inspected: list[AudioInput] = field(default_factory=list)
    transcribed: list[AudioInput] = field(default_factory=list)
    during_transcription: Callable[[], None] | None = None


@pytest.fixture
def voice_boundary(monkeypatch):
    boundary = VoiceBoundary()
    monkeypatch.setattr(voice, "load_voice_settings", lambda: VoiceSettings(api_key="test-only-key"))

    class Inspector:
        def __init__(self, **settings):
            pass

        async def duration_seconds(self, audio):
            boundary.inspected.append(audio)
            assert audio.content == AUDIO
            return 1

    class Transcriber:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def transcribe(self, audio):
            boundary.transcribed.append(audio)
            if boundary.during_transcription:
                boundary.during_transcription()
            return Transcript(WORDS)

    monkeypatch.setattr(voice, "FfprobeMediaInspector", Inspector)
    monkeypatch.setattr(voice, "create_voice_transcriber", Transcriber)
    return boundary


def _set_role(environment, workspace_id, user_id, role):
    environment.execute_admin(
        "UPDATE public.workspace_members SET role=%s WHERE workspace_id=%s AND user_id=%s",
        (role, workspace_id, user_id),
    )


def _post_audio(client):
    return client.post(
        "/voice/transcribe", content=AUDIO, headers={"Content-Type": "audio/webm;codecs=opus"}
    )


def _assert_no_capture(environment, workspace_id):
    counts = environment.fetchone_admin(
        """SELECT (SELECT count(*) FROM public.documents WHERE workspace_id=%s),
                  (SELECT count(*) FROM public.document_versions WHERE workspace_id=%s),
                  (SELECT count(*) FROM public.chunks WHERE workspace_id=%s),
                  (SELECT count(*) FROM public.activity_events
                    WHERE workspace_id=%s AND event_type='item_created')""",
        (workspace_id, workspace_id, workspace_id, workspace_id),
    )
    assert counts == (0, 0, 0, 0)


@pytest.mark.parametrize("role", ["owner", "editor"])
def test_cookie_authenticated_writer_persists_voice_transcript(authenticated_client, voice_boundary, role):
    client, environment, workspace_id, user_id = authenticated_client
    _set_role(environment, workspace_id, user_id, role)
    assert client.get("/auth/me").json()["workspace"]["role"] == role

    response = _post_audio(client)
    assert response.status_code == 200, response.text
    item = response.json()
    assert item["type"] == "audio" and item["status"] == "ready"
    assert item["content"] == WORDS
    assert item["fileName"] == "voice-memo.webm" and item["fileSize"] == len(AUDIO)
    assert item["fileType"] == "audio/webm"
    assert response.headers["cache-control"] == "no-store"
    assert len(voice_boundary.inspected) == len(voice_boundary.transcribed) == 1
    assert client.get(f"/items/{item['id']}").json()["content"] == WORDS

    stored = environment.fetchone_admin(
        """SELECT d.source_type, v.state, v.parser_version, c.content,
                  d.metadata, v.snapshot_metadata,
                  (SELECT count(*) FROM public.activity_events e
                    WHERE e.workspace_id=d.workspace_id AND e.target_id=d.id
                      AND e.event_type='item_created')
             FROM public.documents d
             JOIN public.document_versions v ON v.id=d.current_version_id
             JOIN public.chunks c ON c.document_version_id=v.id
            WHERE d.workspace_id=%s AND d.id=%s""",
        (workspace_id, UUID(item["id"])),
    )
    assert stored[:4] == ("audio", "ready", "ingest-audio-v1", WORDS)
    assert stored[4] == stored[5] == {
        "sourceType": "audio", "fileName": "voice-memo.webm",
        "fileSize": len(AUDIO), "fileType": "audio/webm",
    }
    assert stored[6] == 1


def test_cookie_authenticated_viewer_cannot_reach_inspection_or_provider(authenticated_client, voice_boundary):
    client, environment, workspace_id, user_id = authenticated_client
    _set_role(environment, workspace_id, user_id, "viewer")
    assert client.get("/auth/me").json()["workspace"]["role"] == "viewer"

    response = _post_audio(client)
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": "Workspace write permission is required"}
    assert voice_boundary.inspected == voice_boundary.transcribed == []
    _assert_no_capture(environment, workspace_id)


@pytest.mark.parametrize("revocation,detail", [
    ("viewer", "Workspace write permission is required"),
    ("removed", "Workspace membership is required"),
])
def test_cookie_membership_revoked_during_transcription_returns_403_without_capture(
    authenticated_client, voice_boundary, revocation, detail
):
    client, environment, workspace_id, user_id = authenticated_client
    _set_role(environment, workspace_id, user_id, "editor")
    assert client.get("/auth/me").json()["workspace"]["role"] == "editor"

    def revoke_membership():
        if revocation == "viewer":
            _set_role(environment, workspace_id, user_id, "viewer")
        else:
            environment.execute_admin(
                "DELETE FROM public.workspace_members WHERE workspace_id=%s AND user_id=%s",
                (workspace_id, user_id),
            )

    voice_boundary.during_transcription = revoke_membership
    response = _post_audio(client)
    assert response.status_code == 403, response.text
    assert response.json() == {"detail": detail}
    assert len(voice_boundary.inspected) == len(voice_boundary.transcribed) == 1
    _assert_no_capture(environment, workspace_id)
