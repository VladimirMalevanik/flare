"""Email verification acceptance tests on the restricted runtime connection."""

import os
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.auth_service import (
    AuthService,
    EmailDeliveryFailed,
    EmailNotVerified,
    RegistrationUnavailable,
    VerificationInvalid,
    token_digest,
)
from test_auth_service import auth  # noqa: F401; shared DB cleanup fixture

pytestmark = pytest.mark.integration


class CapturingSender:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[dict[str, str]] = []

    def send(self, *, to: str, subject: str, text: str) -> None:
        if self.fail:
            raise OSError("test SMTP failure")
        self.sent.append({"to": to, "subject": subject, "text": text})


def message_token(sender: CapturingSender, index: int = -1) -> str:
    link = next(
        line for line in sender.sent[index]["text"].splitlines() if "token=" in line
    )
    return parse_qs(urlsplit(link).query)["token"][0]


def verification_service(auth, sender: CapturingSender, **overrides) -> AuthService:
    return AuthService(
        auth.database,
        email_verification_required=True,
        email_verification_ttl=overrides.get("ttl", 3600),
        email_verification_resend=overrides.get("resend", 60),
        email_sender=sender,
        app_public_url="https://app.flare.test",
    )


def test_registration_uses_digest_and_existing_session_unlocks_after_verification(auth):
    sender = CapturingSender()
    service = verification_service(auth, sender)
    email = f"{uuid4()}@auth-test.invalid"
    session_token = service.register(email, "a-long-test-password", "Unverified")
    verification_token = message_token(sender)
    assert f"https://app.flare.test/verify-email?token={verification_token}" in sender.sent[0]["text"]

    current = service.current(session_token)
    assert current.email == email and current.email_verified is False
    with pytest.raises(EmailNotVerified):
        service.login(email, "a-long-test-password")
    with service.database.connection() as connection:
        stored = connection.execute(
            "SELECT token_hash FROM auth_email_verifications WHERE user_id=%s",
            (current.user_id,),
        ).fetchone()["token_hash"]
    assert stored == token_digest(verification_token)
    assert stored != verification_token

    service.verify_email(verification_token)
    assert service.current(session_token).email_verified is True
    assert service.login(email, "a-long-test-password")
    with pytest.raises(VerificationInvalid):
        service.verify_email(verification_token)


def test_malformed_unknown_expired_and_disabled_tokens_are_rejected(auth):
    sender = CapturingSender()
    service = verification_service(auth, sender)
    email = f"{uuid4()}@auth-test.invalid"
    session_token = service.register(email, "a-long-test-password", "Unverified")
    token = message_token(sender)
    user = service.current(session_token)

    for invalid in ("", "short", "x" * 43):
        with pytest.raises(VerificationInvalid):
            service.verify_email(invalid)

    with service.database.connection() as connection:
        connection.execute(
            "UPDATE auth_email_verifications SET expires_at=now()-interval '1 second' "
            "WHERE token_hash=%s",
            (token_digest(token),),
        )
    with pytest.raises(VerificationInvalid):
        service.verify_email(token)

    service = verification_service(auth, sender, resend=1)
    with service.database.connection() as connection:
        connection.execute(
            "UPDATE auth_email_verifications SET created_at=now()-interval '2 seconds' "
            "WHERE user_id=%s",
            (user.user_id,),
        )
    service.resend_verification(email)
    disabled_token = message_token(sender)
    with service.database.connection() as connection:
        connection.execute(
            "UPDATE auth_users SET disabled=true WHERE id=%s", (user.user_id,)
        )
    with pytest.raises(VerificationInvalid):
        service.verify_email(disabled_token)


def test_resend_cooldown_and_new_token_invalidate_previous(auth):
    sender = CapturingSender()
    service = verification_service(auth, sender, resend=1)
    email = f"{uuid4()}@auth-test.invalid"
    session_token = service.register(email, "a-long-test-password", "Unverified")
    first = message_token(sender)

    service.resend_verification(email)
    assert len(sender.sent) == 1
    with service.database.connection() as connection:
        user_id = service.current(session_token).user_id
        connection.execute(
            "UPDATE auth_email_verifications SET created_at=now()-interval '2 seconds' "
            "WHERE user_id=%s",
            (user_id,),
        )
    service.resend_verification(email)
    second = message_token(sender)
    assert second != first and len(sender.sent) == 2
    with pytest.raises(VerificationInvalid):
        service.verify_email(first)
    service.verify_email(second)


def test_delivery_failure_keeps_account_and_allows_immediate_resend(auth):
    sender = CapturingSender(fail=True)
    service = verification_service(auth, sender)
    email = f"{uuid4()}@auth-test.invalid"
    with pytest.raises(EmailDeliveryFailed):
        service.register(email, "a-long-test-password", "Recoverable")
    with service.database.connection() as connection:
        user = connection.execute(
            "SELECT id,email_verified_at FROM auth_users WHERE email=%s", (email,)
        ).fetchone()
        assert user is not None and user["email_verified_at"] is None
        assert connection.execute(
            "SELECT count(*) AS count FROM auth_email_verifications WHERE user_id=%s",
            (user["id"],),
        ).fetchone()["count"] == 0
        assert connection.execute(
            "SELECT count(*) AS count FROM auth_sessions "
            "WHERE user_id=%s AND revoked_at IS NULL",
            (user["id"],),
        ).fetchone()["count"] == 0
    with pytest.raises(RegistrationUnavailable):
        service.register(email, "a-long-test-password", "Duplicate")

    sender.fail = False
    service.resend_verification(email)
    assert len(sender.sent) == 1
    service.verify_email(message_token(sender))


@pytest.fixture
def email_client(auth):
    sender = CapturingSender()
    configured = Settings(
        database_url=os.environ["DATABASE_URL"],
        environment="test",
        cors_origins=["http://testserver"],
        email_verification_required=True,
        email_verification_ttl_seconds=3600,
        email_verification_resend_seconds=1,
        app_public_url="http://localhost:3000",
    )
    with TestClient(
        create_app(configured, email_sender=sender),
        headers={"Origin": "http://testserver"},
    ) as client:
        yield client, sender


def register(client: TestClient):
    payload = {
        "email": f"{uuid4()}@auth-test.invalid",
        "password": "long-secret-password",
        "name": "Verification User",
    }
    response = client.post("/auth/register", json=payload)
    assert response.status_code == 201, response.text
    return payload, response


def test_http_limited_session_and_machine_readable_login_error(email_client):
    client, sender = email_client
    payload, response = register(client)
    assert response.json()["emailVerificationRequired"] is True
    assert client.get("/auth/me").json()["user"]["emailVerified"] is False
    assert client.post("/auth/resend-verification", json={"email": payload["email"]}).status_code == 202

    denied = [
        client.get("/items"),
        client.get("/flares"),
        client.post(
            "/analyze",
            json={},
            headers={"Idempotency-Key": str(uuid4())},
        ),
        client.get(f"/analysis-runs/{uuid4()}"),
    ]
    assert all(item.status_code == 403 for item in denied)
    assert all(
        item.json()["detail"]["code"] == "email_verification_required"
        for item in denied
    )

    login = client.post(
        "/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    )
    assert login.status_code == 403
    assert login.json()["detail"]["code"] == "email_verification_required"
    assert client.post("/auth/logout").status_code == 204

    # Verification itself is available without a session.
    verified = client.post("/auth/verify-email", json={"token": message_token(sender)})
    assert verified.status_code == 200
    assert client.post(
        "/auth/login",
        json={"email": payload["email"], "password": payload["password"]},
    ).status_code == 200
    assert client.post("/items", json={"type": "note", "content": "Unlocked"}).status_code == 201


def test_http_invalid_tokens_and_resend_are_enumeration_safe(email_client):
    client, sender = email_client
    payload, _ = register(client)
    token = message_token(sender)
    for invalid in ("", "bad", "x" * 43):
        response = client.post("/auth/verify-email", json={"token": invalid})
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "email_verification_invalid"
    client.post("/auth/verify-email", json={"token": token})
    disabled_payload, _ = register(client)
    with psycopg.connect(os.environ["TEST_DATABASE_URL"]) as connection:
        connection.execute(
            "UPDATE auth_users SET disabled=true WHERE email=%s",
            (disabled_payload["email"],),
        )
    bodies = [
        client.post("/auth/resend-verification", json={"email": payload["email"]}),
        client.post(
            "/auth/resend-verification",
            json={"email": f"{uuid4()}@auth-test.invalid"},
        ),
        client.post(
            "/auth/resend-verification",
            json={"email": disabled_payload["email"]},
        ),
    ]
    assert all(response.status_code == 202 for response in bodies)
    assert bodies[0].json() == bodies[1].json()


def test_http_registration_delivery_failure_is_stable_and_recoverable(auth):
    sender = CapturingSender(fail=True)
    configured = Settings(
        database_url=os.environ["DATABASE_URL"],
        environment="test",
        cors_origins=["http://testserver"],
        email_verification_required=True,
        app_public_url="http://localhost:3000",
    )
    payload = {
        "email": f"{uuid4()}@auth-test.invalid",
        "password": "long-secret-password",
        "name": "Delivery Recovery",
    }
    with TestClient(
        create_app(configured, email_sender=sender),
        headers={"Origin": "http://testserver"},
    ) as client:
        failed = client.post("/auth/register", json=payload)
        assert failed.status_code == 503
        assert failed.json()["detail"]["code"] == "email_delivery_failed"
        assert client.post("/auth/register", json=payload).status_code == 409
        sender.fail = False
        resent = client.post(
            "/auth/resend-verification", json={"email": payload["email"]}
        )
        assert resent.status_code == 202 and len(sender.sent) == 1
        assert client.post(
            "/auth/verify-email", json={"token": message_token(sender)}
        ).status_code == 200
