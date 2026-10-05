"""Billing HTTP boundary tests with real middleware and an offline repository."""

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import logging
import os
import time
from uuid import UUID, uuid4

from fastapi import Depends
from fastapi.testclient import TestClient
import pytest

from app.api import billing
from app.api.auth import verified_user
from app.config import Settings
from app.main import create_app
from app.services.auth_service import AuthenticatedUser
from test_paddle_billing import PRICE_ID, SECRET, event_payload, raw_event, subscription


ORIGIN = "http://testserver"
WEBHOOK = "/billing/paddle/webhook"
OWNER = AuthenticatedUser(
    user_id="auth:billing-test-owner",
    workspace_id=UUID("00000000-0000-4000-8000-000000000001"),
    email="owner@billing-test.invalid",
    name="Billing Owner",
    role="owner",
    workspace_name="Billing workspace",
)


class FakeDatabase:
    def open(self):
        pass

    def close(self):
        pass


class RecordingRepository:
    """Record boundary calls, without implementing persistence or RLS in a fake."""
    def __init__(self):
        self.events = []
        self.status_identities = []
        self.intents = []
        self.rows = []
        self.outcome = "applied"
        self.failure = None

    def apply_event(self, snapshot):
        if self.failure:
            raise self.failure
        self.events.append(snapshot)
        return self.outcome

    def subscriptions(self, identity):
        if self.failure:
            raise self.failure
        self.status_identities.append(identity)
        return self.rows

    def create_intent(self, identity, token_hash, price_id, ttl_seconds):
        if self.failure:
            raise self.failure
        self.intents.append((identity, token_hash, price_id, ttl_seconds))
        return datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)


def signature(body, *, timestamp=None, secret=SECRET):
    timestamp = int(time.time()) if timestamp is None else timestamp
    digest = hmac.new(secret.encode(), str(timestamp).encode() + b":" + body, sha256).hexdigest()
    return f"ts={timestamp};h1={digest}"


@pytest.fixture
def repository():
    return RecordingRepository()


@pytest.fixture
def client_factory(monkeypatch, repository):
    monkeypatch.setattr(billing, "BillingRepository", lambda database: repository)

    @contextmanager
    def make_client(*, user=OWNER, configured=True):
        settings = Settings(
            database_url=None,
            cors_origins=[ORIGIN],
            environment="test",
            paddle_environment="sandbox",
            paddle_webhook_secret=SECRET if configured else None,
            paddle_pro_price_id=PRICE_ID if configured else None,
        )
        app = create_app(settings, database=FakeDatabase())
        if user is not None:
            app.dependency_overrides[verified_user] = lambda: user
        with TestClient(app) as client:
            yield client

    return make_client


def post_webhook(client, body=None, **kwargs):
    body = raw_event() if body is None else body
    return client.post(WEBHOOK, content=body, headers={
        "Content-Type": "application/json",
        "Paddle-Signature": signature(body),
    }, **kwargs)


def test_webhook_without_browser_origin_processes_verified_snapshot(client_factory, repository):
    with client_factory(user=None) as client:
        response = post_webhook(client)
    assert response.status_code == 200
    assert response.json() == {"received": True, "outcome": "applied"}
    assert len(repository.events) == 1
    assert repository.events[0]["price_id"] == PRICE_ID
    assert "not-authoritative-browser-user" not in repr(repository.events)


@pytest.mark.parametrize("outcome", ["duplicate", "stale", "unlinked", "conflict"])
def test_handled_repository_outcomes_acknowledge_without_inviting_retries(client_factory, repository, outcome):
    repository.outcome = outcome
    with client_factory(user=None) as client:
        response = post_webhook(client)
    assert response.status_code == 200
    assert response.json()["outcome"] == outcome


def test_unknown_repository_outcome_is_not_acknowledged_as_durable_success(client_factory, repository):
    repository.outcome = "unexpected-partial-write"
    with client_factory(user=None) as client:
        response = post_webhook(client)
    assert response.status_code == 503


def test_signed_non_subscription_event_is_acknowledged_without_database_write(client_factory, repository):
    payload = event_payload()
    payload["event_type"] = "transaction.completed"
    with client_factory(user=None) as client:
        response = post_webhook(client, raw_event(payload))
    assert response.status_code == 200
    assert response.json()["received"] is True
    assert repository.events == []


def test_signed_large_quantity_update_reaches_durable_handler_without_retry_loop(client_factory, repository):
    payload = event_payload()
    payload["event_type"] = "subscription.updated"
    payload["data"]["items"][0]["quantity"] = 1001
    with client_factory(user=None) as client:
        response = post_webhook(client, raw_event(payload))
    assert response.status_code == 200
    assert response.json()["outcome"] == "applied"
    assert repository.events[0]["quantity"] == 0


@pytest.mark.parametrize("headers", [
    {}, {"Paddle-Signature": "ts=1;h1=" + "0" * 64},
    {"Paddle-Signature": "malformed"},
])
def test_unsigned_or_invalid_signature_cannot_reach_repository(client_factory, repository, headers):
    with client_factory(user=None) as client:
        response = client.post(WEBHOOK, content=raw_event(), headers=headers)
    assert response.status_code == 401
    assert repository.events == []


def test_valid_signature_of_another_body_does_not_authenticate_json(client_factory, repository):
    original = raw_event()
    altered = original.replace(b'"trialing"', b'"active"')
    with client_factory(user=None) as client:
        response = client.post(WEBHOOK, content=altered, headers={"Paddle-Signature": signature(original)})
    assert response.status_code == 401
    assert repository.events == []


def test_duplicate_signature_headers_are_rejected(client_factory, repository):
    body = raw_event()
    with client_factory(user=None) as client:
        response = client.post(WEBHOOK, content=body, headers=[
            ("Paddle-Signature", signature(body)),
            ("Paddle-Signature", signature(body)),
        ])
    assert response.status_code == 401
    assert repository.events == []


@pytest.mark.parametrize("offset", [-60, 60])
def test_old_and_future_signed_delivery_is_rejected(client_factory, repository, offset):
    body = raw_event()
    with client_factory(user=None) as client:
        response = client.post(WEBHOOK, content=body, headers={
            "Paddle-Signature": signature(body, timestamp=int(time.time()) + offset),
        })
    assert response.status_code == 401
    assert repository.events == []


@pytest.mark.parametrize("body", [
    b"{not-json", b"[]",
    b'{"event_type":"subscription.updated"}',
    b'{"event_type":"subscription.created","event_type":"subscription.updated"}',
])
def test_signed_invalid_json_and_schema_returns_400_without_writing(client_factory, repository, body):
    with client_factory(user=None) as client:
        response = post_webhook(client, body)
    assert response.status_code == 400
    assert repository.events == []


def test_signed_nested_duplicate_identity_is_rejected(client_factory, repository):
    body = raw_event().replace(b'"customer_id":', b'"customer_id": "ctm_' + b"x" * 26 + b'", "customer_id":')
    with client_factory(user=None) as client:
        response = post_webhook(client, body)
    assert response.status_code == 400
    assert repository.events == []


def test_streamed_body_limit_applies_without_trusting_content_length(client_factory, repository):
    def oversized_stream():
        yield b"x" * (128 * 1024)
        yield b"x" * (128 * 1024 + 1)

    with client_factory(user=None) as client:
        response = client.post(WEBHOOK, content=oversized_stream(), headers={
            "Content-Type": "application/json", "Paddle-Signature": "irrelevant",
        })
    assert response.status_code == 413
    assert repository.events == []


def test_database_failure_invites_retry_and_does_not_echo_exception(client_factory, repository):
    repository.failure = RuntimeError("private database URL password=do-not-disclose")
    with client_factory(user=None) as client:
        response = post_webhook(client)
    assert response.status_code == 503
    assert "do-not-disclose" not in response.text
    assert repository.events == []


def test_signed_webhook_cannot_expose_internal_membership_errors(client_factory, repository):
    repository.failure = RuntimeError("private internal membership state")
    with client_factory(user=None) as client:
        response = post_webhook(client)
    assert response.status_code == 503
    assert "private internal" not in response.text


def test_webhook_and_intent_fail_closed_when_configuration_is_missing(client_factory, repository):
    with client_factory(configured=False) as client:
        webhook = post_webhook(client)
        intent = client.post("/billing/checkout-intents", json={}, headers={"Origin": ORIGIN})
        status = client.get("/billing/status")
    assert webhook.status_code == intent.status_code == 503
    assert status.status_code == 200
    assert status.json()["plan"] == "free"
    assert status.json()["checkoutAvailable"] is False
    assert repository.events == repository.intents == []


def test_origin_exception_is_limited_to_exact_webhook_route(client_factory, repository):
    with client_factory() as client:
        assert client.post("/billing/checkout-intents", json={}).status_code == 403
        assert client.post("/billing/paddle/webhook/extra", content=b"{}").status_code == 403
        assert client.post("/billing/paddle/webhook/", content=b"{}").status_code == 403
        assert client.post("/auth/logout").status_code == 403
        response = client.post("/billing/checkout-intents", json={}, headers={"Origin": "https://evil.invalid"})
    assert response.status_code == 403
    assert repository.intents == []


def test_status_is_scoped_to_session_workspace_and_is_not_cached(client_factory, repository):
    with client_factory() as client:
        response = client.get("/billing/status", headers={
            "X-Workspace-Id": "00000000-0000-4000-8000-000000000999",
            "X-User-Id": "somebody-else",
        })
    assert response.status_code == 200
    data = response.json()
    assert data["plan"] == "free"
    assert data["environment"] == "sandbox"
    assert data["workspaceId"] == str(OWNER.workspace_id)
    assert data["canManageBilling"] is True
    assert data["checkoutAvailable"] is True
    assert repository.status_identities == [OWNER.identity]
    assert response.headers["cache-control"] == "no-store"


def test_owner_intent_is_bound_to_session_and_raw_token_is_not_persisted(client_factory, repository):
    with client_factory() as client:
        response = client.post("/billing/checkout-intents", json={}, headers={
            "Origin": ORIGIN,
            "X-User-Id": "victim",
            "X-Workspace-Id": "victim-workspace",
        })
    assert response.status_code == 201
    data = response.json()
    assert data["environment"] == "sandbox"
    assert data["priceId"] == PRICE_ID
    assert data["quantity"] == 1
    assert data["email"] == OWNER.email
    assert data["customData"]["userId"] == OWNER.user_id
    token = data["customData"]["checkoutIntent"]
    assert isinstance(token, str) and len(token) >= 32
    identity, token_hash, price_id, ttl = repository.intents[0]
    assert identity == OWNER.identity
    assert token_hash == sha256(token.encode()).hexdigest()
    assert price_id == PRICE_ID and ttl > 0
    assert token not in repr(repository.intents)
    assert response.headers["cache-control"] == "no-store"


def test_empty_request_body_can_create_intent(client_factory, repository):
    with client_factory() as client:
        response = client.post("/billing/checkout-intents", headers={"Origin": ORIGIN})
    assert response.status_code == 201
    assert len(repository.intents) == 1


@pytest.mark.parametrize("body", [
    {"userId": "victim"}, {"workspaceId": "victim"},
    {"priceId": "pri_" + "f" * 26}, {"quantity": 20},
    {"email": "victim@example.invalid"}, [], None,
])
def test_intent_endpoint_cannot_accept_client_identity_or_price(client_factory, repository, body):
    with client_factory() as client:
        response = client.post("/billing/checkout-intents", content=json.dumps(body), headers={
            "Origin": ORIGIN, "Content-Type": "application/json",
        })
    assert response.status_code == 400
    assert repository.intents == []


@pytest.mark.parametrize("role", ["viewer", "editor"])
def test_only_workspace_owner_can_purchase_but_members_can_read_plan(client_factory, repository, role):
    member = replace(OWNER, user_id="billing-test|member", role=role)
    now = datetime.now(timezone.utc)
    repository.rows = [subscription(
        current_period_starts_at=now - timedelta(days=1),
        current_period_ends_at=now + timedelta(days=1),
    )]
    with client_factory(user=member) as client:
        status = client.get("/billing/status")
        intent = client.post("/billing/checkout-intents", json={}, headers={"Origin": ORIGIN})
    assert status.status_code == 200
    assert status.json()["plan"] == "pro"
    assert status.json()["canManageBilling"] is False
    assert status.json()["checkoutAvailable"] is False
    assert intent.status_code == 403
    assert repository.status_identities[0] == member.identity
    assert repository.intents == []


def test_existing_pro_subscription_prevents_duplicate_purchase(client_factory, repository):
    now = datetime.now(timezone.utc)
    repository.rows = [subscription(
        current_period_starts_at=now - timedelta(days=1),
        current_period_ends_at=now + timedelta(days=1),
    )]
    with client_factory() as client:
        status = client.get("/billing/status")
        response = client.post("/billing/checkout-intents", json={}, headers={"Origin": ORIGIN})
    assert status.json()["plan"] == "pro"
    assert status.json()["checkoutAvailable"] is False
    assert response.status_code == 409
    assert repository.intents == []


def test_development_identity_cannot_issue_paid_checkout_intent(client_factory, repository):
    development = replace(OWNER, user_id="configured-local-development-user")
    with client_factory(user=development) as client:
        response = client.post("/billing/checkout-intents", json={}, headers={"Origin": ORIGIN})
    assert response.status_code == 403
    assert repository.intents == []


def test_distinct_checkout_attempts_receive_distinct_one_time_tokens(client_factory, repository):
    with client_factory() as client:
        responses = [client.post("/billing/checkout-intents", json={}, headers={"Origin": ORIGIN}) for _ in range(2)]
    assert all(response.status_code == 201 for response in responses)
    tokens = [response.json()["customData"]["checkoutIntent"] for response in responses]
    assert tokens[0] != tokens[1]
    assert repository.intents[0][1] != repository.intents[1][1]


@pytest.mark.parametrize("path,method", [
    ("/billing/status", "get"), ("/billing/checkout-intents", "post"),
])
def test_billing_database_failure_does_not_become_free_or_issued_checkout(client_factory, repository, path, method):
    repository.failure = RuntimeError("private subscription store details")
    with client_factory() as client:
        response = getattr(client, method)(path, headers={"Origin": ORIGIN})
    assert response.status_code == 503
    assert "private subscription" not in response.text
    assert repository.intents == []


def test_anonymous_requests_cannot_read_or_create_billing_identity(client_factory, repository):
    with client_factory(user=None) as client:
        assert client.get("/billing/status").status_code == 401
        assert client.post("/billing/checkout-intents", json={}, headers={"Origin": ORIGIN}).status_code == 401
    assert repository.status_identities == repository.intents == []


def test_error_response_and_http_logs_do_not_contain_payment_body_or_secret(client_factory, caplog):
    payload = event_payload()
    payload["data"]["custom_data"]["private_marker"] = "sensitive-payment-body-marker"
    body = raw_event(payload)
    with caplog.at_level(logging.INFO), client_factory(user=None) as client:
        response = client.post(WEBHOOK, content=body, headers={
            "Paddle-Signature": signature(body, secret="wrong-destination"),
        })
    assert response.status_code == 401
    captured = response.text + caplog.text
    assert SECRET not in captured
    assert "sensitive-payment-body-marker" not in captured
    assert "not-authoritative-browser-user" not in captured


def test_billing_secret_is_excluded_from_configuration_repr():
    settings = Settings(database_url=None, cors_origins=[ORIGIN], environment="test", paddle_webhook_secret=SECRET)
    assert SECRET not in repr(settings)


def test_live_billing_environment_is_rejected():
    settings = Settings(database_url=None, cors_origins=[ORIGIN], environment="test", paddle_environment="live")
    with pytest.raises(RuntimeError):
        settings.validate()


@pytest.mark.integration
def test_signed_webhook_persists_workspace_pro_then_cancellation_revokes_it():
    """Exercise real cookies, owner intents, signature verification, SQL and RLS."""
    import psycopg
    from test_items_api import ApiEnvironment

    runtime_url = os.environ.get("DATABASE_URL")
    admin_url = os.environ.get("TEST_DATABASE_URL")
    if not runtime_url or not admin_url:
        pytest.skip("DATABASE_URL and TEST_DATABASE_URL are required for billing lifecycle HTTP tests")

    class NoDelivery:
        def send(self, *, to, subject, text):
            pass

    environment = ApiEnvironment(runtime_url, admin_url)
    emails = [f"{uuid4()}@billing-http-test.invalid" for _ in range(2)]
    event_ids = ["evt_" + uuid4().hex[:26] for _ in range(2)]
    subscription_id = "sub_" + uuid4().hex[:26]
    customer_id = "ctm_" + uuid4().hex[:26]
    settings = Settings(
        database_url=runtime_url,
        cors_origins=[ORIGIN],
        environment="test",
        email_verification_required=True,
        app_public_url="http://localhost:3000",
        paddle_environment="sandbox",
        paddle_webhook_secret=SECRET,
        paddle_pro_price_id=PRICE_ID,
    )

    def application():
        app = create_app(settings, email_sender=NoDelivery())

        @app.get("/__test__/pro", dependencies=[Depends(billing.require_pro)])
        def protected_resource():
            return {"ok": True}

        return app

    def register_verified(client, email):
        registration = client.post("/auth/register", json={
            "email": email,
            "password": "billing-http-test-password",
            "name": "Billing HTTP Test",
            "termsAccepted": True,
            "privacyAccepted": True,
        })
        assert registration.status_code == 201
        me = client.get("/auth/me")
        assert me.status_code == 200
        identity = me.json()
        environment.workspace_ids.add(UUID(identity["workspace"]["id"]))
        environment.user_ids.add(identity["user"]["id"])
        assert client.get("/billing/status").status_code == 403
        environment.execute_admin(
            "UPDATE public.auth_users SET email_verified_at=now(),verification_provenance='actual' WHERE id=%s",
            (identity["user"]["id"],),
        )
        assert client.get("/auth/me").json()["user"]["emailVerified"] is True
        return identity

    try:
        with (
            TestClient(application(), headers={"Origin": ORIGIN}) as owner,
            TestClient(application(), headers={"Origin": ORIGIN}) as member,
            TestClient(application()) as delivery,
        ):
            owner_identity = register_verified(owner, emails[0])
            member_identity = register_verified(member, emails[1])
            own_workspace = UUID(owner_identity["workspace"]["id"])
            other_workspace = member_identity["workspace"]["id"]
            assert own_workspace != UUID(other_workspace)
            assert owner.get("/billing/status").json()["plan"] == "free"
            assert member.get("/billing/status").json()["plan"] == "free"
            assert owner.get("/__test__/pro").status_code == 403
            assert member.get("/__test__/pro").status_code == 403

            response = owner.post("/billing/checkout-intents", json={})
            assert response.status_code == 201
            intent = response.json()
            assert intent["environment"] == "sandbox"
            assert intent["priceId"] == PRICE_ID
            assert intent["customData"]["userId"] == owner_identity["user"]["id"]
            persisted_intent = environment.fetchone_admin(
                "SELECT workspace_id,user_id,consumed_at FROM public.billing_checkout_intents WHERE token_hash=%s",
                (sha256(intent["customData"]["checkoutIntent"].encode()).hexdigest(),),
            )
            assert persisted_intent == (own_workspace, owner_identity["user"]["id"], None)

            occurred = datetime.now(timezone.utc)
            trial_end = occurred + timedelta(days=30)
            payload = event_payload()
            payload["event_id"] = event_ids[0]
            payload["occurred_at"] = occurred.isoformat()
            payload["data"].update({
                "id": subscription_id,
                "customer_id": customer_id,
                "custom_data": intent["customData"],
                "current_billing_period": None,
                "next_billed_at": trial_end.isoformat(),
            })
            payload["data"]["items"][0]["trial_dates"] = {
                "starts_at": occurred.isoformat(), "ends_at": trial_end.isoformat(),
            }
            created = post_webhook(delivery, raw_event(payload))
            assert created.status_code == 200
            assert created.json()["outcome"] == "applied"

            # A new app/pool and HTTP request must see PostgreSQL state, rather
            # than a client-side checkout event or the first app's memory.
            with TestClient(application()) as refreshed:
                refreshed.cookies.update(owner.cookies)
                status = refreshed.get("/billing/status")
                assert status.status_code == 200
                assert status.json()["plan"] == "pro"
                assert status.json()["status"] == "trialing"
                assert status.json()["workspaceId"] == str(own_workspace)
                assert status.json()["checkoutAvailable"] is False
                assert refreshed.get("/__test__/pro").status_code == 200
            persisted = environment.fetchone_admin(
                "SELECT workspace_id,user_id,customer_id,status FROM public.billing_subscriptions WHERE subscription_id=%s",
                (subscription_id,),
            )
            assert persisted == (own_workspace, owner_identity["user"]["id"], customer_id, "trialing")
            foreign = member.get("/billing/status")
            assert foreign.json()["workspaceId"] == other_workspace
            assert foreign.json()["plan"] == "free"
            assert member.get("/__test__/pro").status_code == 403

            # Select the paid workspace for a real second-account session.
            # The browser cannot forge this through request bodies or headers.
            environment.execute_admin(
                "INSERT INTO public.workspace_members(workspace_id,user_id,role) VALUES(%s,%s,'viewer')",
                (own_workspace, member_identity["user"]["id"]),
            )
            environment.execute_admin(
                "UPDATE public.auth_sessions SET workspace_id=%s WHERE user_id=%s AND revoked_at IS NULL",
                (own_workspace, member_identity["user"]["id"]),
            )
            member_status = member.get("/billing/status")
            assert member_status.status_code == 200
            assert member_status.json()["plan"] == "pro"
            assert member_status.json()["canManageBilling"] is False
            assert member_status.json()["checkoutAvailable"] is False
            assert owner.get("/__test__/pro").status_code == 200
            assert member.get("/__test__/pro").status_code == 200
            assert member.post("/billing/checkout-intents", json={}).status_code == 403

            payload["event_id"] = event_ids[1]
            payload["event_type"] = "subscription.canceled"
            payload["occurred_at"] = (occurred + timedelta(seconds=1)).isoformat()
            payload["data"]["status"] = "canceled"
            payload["data"]["custom_data"] = None
            canceled = post_webhook(delivery, raw_event(payload))
            assert canceled.status_code == 200
            assert canceled.json()["outcome"] == "applied"
            assert owner.get("/billing/status").json()["plan"] == "free"
            assert member.get("/billing/status").json()["plan"] == "free"
            assert owner.get("/__test__/pro").status_code == 403
            assert member.get("/__test__/pro").status_code == 403
            assert environment.fetchone_admin(
                "SELECT status FROM public.billing_subscriptions WHERE subscription_id=%s",
                (subscription_id,),
            ) == ("canceled",)
    finally:
        with psycopg.connect(admin_url) as connection:
            connection.execute("DELETE FROM public.billing_webhook_events WHERE event_id=ANY(%s)", (event_ids,))
            # Also find accounts created before a failed assertion could record
            # their IDs, without touching any unrelated fixture's test tenants.
            accounts = connection.execute(
                "SELECT id,initial_workspace_id FROM public.auth_users WHERE email=ANY(%s)",
                (emails,),
            ).fetchall()
        environment.user_ids.update(account[0] for account in accounts)
        environment.workspace_ids.update(account[1] for account in accounts)
        environment.cleanup()
