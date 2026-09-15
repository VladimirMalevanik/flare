"""Current legal acceptance is exact, durable, and enforced for existing users."""

from hashlib import sha1
import os
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest

from app.config import Settings
from app.legal import (
    CURRENT_PRIVACY_CONTENT_ID,
    CURRENT_PRIVACY_VERSION,
    CURRENT_TERMS_CONTENT_ID,
    CURRENT_TERMS_VERSION,
)
from app.main import create_app
from test_auth_service import auth  # noqa: F401; shared DB fixture

pytestmark = pytest.mark.integration


def _git_blob_id(path: Path) -> str:
    content = path.read_bytes()
    return sha1(f"blob {len(content)}\0".encode() + content).hexdigest()


def _register(client: TestClient) -> dict[str, str | bool]:
    payload: dict[str, str | bool] = {
        "email": f"{uuid4()}@legal-test.invalid",
        "password": "long-secret-password",
        "name": "Legal Test",
        "termsAccepted": True,
        "privacyAccepted": True,
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return payload


def test_legal_content_ids_match_exact_frontend_documents():
    root = Path(__file__).resolve().parents[2]
    assert CURRENT_TERMS_VERSION == "2026-09-15"
    assert CURRENT_PRIVACY_VERSION == "2026-09-15"
    assert _git_blob_id(root / "frontend/src/app/terms/page.tsx") == CURRENT_TERMS_CONTENT_ID
    assert _git_blob_id(root / "frontend/src/app/privacy/page.tsx") == CURRENT_PRIVACY_CONTENT_ID


def test_existing_user_without_current_acceptance_is_gated(auth):
    configured = Settings(
        database_url=os.environ["DATABASE_URL"],
        environment="test",
        cors_origins=["http://testserver"],
    )
    with TestClient(
        create_app(configured), headers={"Origin": "http://testserver"}
    ) as client:
        payload = _register(client)
        me = client.get("/auth/me").json()
        assert me["user"]["legalAccepted"] is True

        with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
            connection.execute(
                "DELETE FROM auth_legal_acceptances WHERE user_id=%s",
                (me["user"]["id"],),
            )

        me = client.get("/auth/me").json()
        assert me["user"]["legalAccepted"] is False
        blocked = client.get("/items")
        assert blocked.status_code == 403
        assert blocked.json()["detail"]["code"] == "legal_acceptance_required"

        acceptance = client.post(
            "/auth/accept-legal",
            json={"termsAccepted": True, "privacyAccepted": True},
        )
        assert acceptance.status_code == 200
        assert client.get("/auth/me").json()["user"]["legalAccepted"] is True
        assert client.get("/items").status_code == 200

        with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
            row = connection.execute(
                """SELECT terms_version::text,privacy_version::text,
                          terms_content_id,privacy_content_id
                   FROM auth_legal_acceptances
                   WHERE user_id=%s""",
                (me["user"]["id"],),
            ).fetchone()
        assert row == (
            CURRENT_TERMS_VERSION,
            CURRENT_PRIVACY_VERSION,
            CURRENT_TERMS_CONTENT_ID,
            CURRENT_PRIVACY_CONTENT_ID,
        )
        assert payload["email"] == me["user"]["email"]


def test_stale_content_identity_does_not_count_as_current_acceptance(auth):
    configured = Settings(
        database_url=os.environ["DATABASE_URL"],
        environment="test",
        cors_origins=["http://testserver"],
    )
    with TestClient(
        create_app(configured), headers={"Origin": "http://testserver"}
    ) as client:
        _register(client)
        me = client.get("/auth/me").json()
        with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
            connection.execute(
                "UPDATE auth_legal_acceptances SET terms_content_id=%s WHERE user_id=%s",
                ("0" * 40, me["user"]["id"]),
            )
        assert client.get("/auth/me").json()["user"]["legalAccepted"] is False
        assert client.get("/items").status_code == 403


@pytest.mark.parametrize("field", ["termsAccepted", "privacyAccepted"])
def test_existing_user_reacceptance_requires_both_explicit_flags(auth, field):
    configured = Settings(
        database_url=os.environ["DATABASE_URL"],
        environment="test",
        cors_origins=["http://testserver"],
    )
    with TestClient(
        create_app(configured), headers={"Origin": "http://testserver"}
    ) as client:
        _register(client)
        me = client.get("/auth/me").json()
        with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
            connection.execute(
                "DELETE FROM auth_legal_acceptances WHERE user_id=%s",
                (me["user"]["id"],),
            )
        payload = {"termsAccepted": True, "privacyAccepted": True}
        payload[field] = False
        assert client.post("/auth/accept-legal", json=payload).status_code == 422
        payload.pop(field)
        assert client.post("/auth/accept-legal", json=payload).status_code == 422
