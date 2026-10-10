"""Manual mail permission and delivery regressions, without live SMTP or DB."""
import asyncio
import json
import smtplib
import threading
import time
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api.auth import current_user
from app.api.ops import router
from app.api import developer_mail as api
from app.config import Settings
from app.main import create_app
from app.services.auth_service import AuthenticatedUser
from app.services.developer_mail import account_grants, configured_sender, send_copies


@pytest.fixture
def developer(monkeypatch):
    user = AuthenticatedUser(f"auth:{uuid4()}", uuid4(), "dev@example.invalid",
                             "Developer", "viewer", "Demo", True, True)
    monkeypatch.setenv("DEVELOPER_MAIL_ACCOUNTS", json.dumps({user.user_id: user.email}))
    return user


def client_for(user=None):
    application = FastAPI()
    application.state.settings = SimpleNamespace(
        dev_mode=False, session_cookie_name="flare_session", email_verification_required=False,
        smtp_url=None, email_from="sender@flare.example",
    )
    application.include_router(router)
    if user is not None:
        application.dependency_overrides[current_user] = lambda: user
    return TestClient(application)


PAYLOAD = {"recipients": ["recipient@example.invalid"], "subject": "Hello", "body": "A manual message.\nSecond line."}


@pytest.mark.parametrize("path,method", [("capability", "get"), ("send", "post")])
def test_anonymous_cannot_access_mail(path, method):
    with client_for() as client:
        response = getattr(client, method)(f"/ops/mail/{path}", **({"json": PAYLOAD} if method == "post" else {}))
    assert response.status_code == 401


@pytest.mark.parametrize("change", [
    {"user_id": "auth:00000000-0000-0000-0000-000000000001", "role": "owner"},
    {"email": "someone@example.invalid", "role": "owner"},
    {"email_verified": False}, {"legal_accepted": False},
])
def test_matching_email_or_customer_owner_is_not_a_developer_grant(developer, change):
    with client_for(replace(developer, **change)) as client:
        capability = client.get("/ops/mail/capability")
        if capability.status_code == 200:
            assert capability.json() == {"allowed": False}
        else:
            assert capability.status_code == 403
        assert client.post("/ops/mail/send", json=PAYLOAD).status_code == 403


def test_developer_viewer_has_mail_but_never_queue_owner_access(developer):
    with client_for(developer) as client:
        response = client.get("/ops/mail/capability")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {"allowed": True, "ready": False, "sender": None, "maxRecipients": 20}
        assert developer.email not in response.text
        assert client.get("/ops/queue").status_code == 403
        unavailable = client.post("/ops/mail/send", json=PAYLOAD)
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"]["code"] == "developer_mail_unavailable"


@pytest.mark.parametrize("raw", ["", "[]", "bad-json", '{"user":"dev@example.invalid"}',
    '{"auth:00000000-0000-0000-0000-000000000001":42}',
    json.dumps({f"auth:{uuid4()}": "dev@example.invalid" for _ in range(7)})])
def test_absent_or_malformed_grants_fail_closed(monkeypatch, raw):
    monkeypatch.setenv("DEVELOPER_MAIL_ACCOUNTS", raw)
    assert account_grants() == {}


def test_empty_grants_and_renamed_account_fail_closed(developer, monkeypatch):
    monkeypatch.delenv("DEVELOPER_MAIL_ACCOUNTS")
    with client_for(developer) as client:
        assert client.get("/ops/mail/capability").json() == {"allowed": False}
        assert client.post("/ops/mail/send", json=PAYLOAD).status_code == 403


@pytest.mark.parametrize("changes", [
    {"recipients": []}, {"recipients": ["a@example.invalid"] * 21},
    {"recipients": ["a@example.invalid", "A@EXAMPLE.INVALID"]},
    {"recipients": ["a@example.invalid\r\nBcc: b@example.invalid"]},
    {"recipients": ["Name <a@example.invalid>"]}, {"recipients": ["a..b@example.invalid"]},
    {"recipients": ["missing@domain"]}, {"recipients": [1]},
    {"subject": "\nBcc: injected@example.invalid"}, {"subject": " "},
    {"subject": "x" * 201}, {"body": " "}, {"body": "x" * 20001},
    {"body": "message\x00"}, {"from": "spoof@example.invalid"},
])
def test_invalid_or_spoofed_payload_never_sends(developer, monkeypatch, changes):
    def forbidden(_):
        raise AssertionError("Sender must not be selected for invalid input")
    monkeypatch.setattr(api, "configured_sender", forbidden)
    with client_for(developer) as client:
        response = client.post("/ops/mail/send", json={**PAYLOAD, **changes})
        assert response.status_code == 422


class Sender:
    def __init__(self):
        self.messages = []
        self.lock = threading.Lock()

    def send(self, **message):
        with self.lock:
            self.messages.append(message)
        if message["to"].startswith("rejected"):
            raise smtplib.SMTPRecipientsRefused({message["to"]: (550, b"private provider detail")})
        if message["to"].startswith("uncertain"):
            raise TimeoutError("smtp://secret:credential@private-host")


def test_separate_copies_truthful_outcomes_and_no_provider_details(developer, monkeypatch):
    sender = Sender()
    monkeypatch.setattr(api, "configured_sender", lambda _: (sender, "sender@flare.example"))
    addresses = ["accepted@example.invalid", "rejected@example.invalid", "uncertain@example.invalid"]
    with client_for(developer) as client:
        response = client.post("/ops/mail/send", json={**PAYLOAD, "recipients": addresses})
    assert response.status_code == 200
    assert response.json() == [{"recipient": to, "status": status} for to, status in zip(addresses, ["accepted", "failed", "unknown"])]
    assert len(sender.messages) == 3
    assert {m["to"] for m in sender.messages} == set(addresses)
    assert all(m["text"] == PAYLOAD["body"] and m["subject"] == PAYLOAD["subject"] for m in sender.messages)
    assert "credential" not in response.text and "private" not in response.text


def test_real_application_keeps_origin_guard_and_mail_router(developer, monkeypatch):
    sender = Sender()
    monkeypatch.setattr(api, "configured_sender", lambda _: (sender, "sender@flare.example"))
    application = create_app(Settings(database_url=None, environment="test", cors_origins=["http://testserver"]))
    application.dependency_overrides[current_user] = lambda: developer
    # No DB/lifespan needed: only the existing middleware and real route wiring.
    client = TestClient(application)
    for headers in ({}, {"Origin": "https://foreign.example"}):
        assert client.post("/ops/mail/send", json=PAYLOAD, headers=headers).status_code == 403
    assert sender.messages == []
    response = client.post("/ops/mail/send", json=PAYLOAD, headers={"Origin": "http://testserver"})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == [{"recipient": PAYLOAD["recipients"][0], "status": "accepted"}]


def test_smtp_required_even_if_application_has_a_logging_sender():
    settings = SimpleNamespace(smtp_url=None, email_from="sender@flare.example")
    assert configured_sender(settings) == (None, None)
    for url, address in [("smtp://", "sender@flare.example"), ("smtp://mail.example", "From\r\nBcc: x@y.z")]:
        assert configured_sender(SimpleNamespace(smtp_url=url, email_from=address)) == (None, None)


def test_concurrency_is_bounded_and_order_retained():
    class BlockingSender:
        active = 0
        maximum = 0
        lock = threading.Lock()
        def send(self, **_):
            with self.lock:
                self.active += 1
                self.maximum = max(self.maximum, self.active)
            time.sleep(.02)
            with self.lock:
                self.active -= 1
    sender = BlockingSender()
    recipients = [f"recipient{i}@example.invalid" for i in range(20)]
    results = asyncio.run(send_copies(sender, recipients, "Subject", "Message"))
    assert 1 < sender.maximum <= 4
    assert [item.recipient for item in results] == recipients
    assert all(item.status == "accepted" for item in results)
