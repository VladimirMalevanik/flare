"""Offline security and access-policy checks for Paddle Sandbox billing."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json

import pytest

from app.services.paddle_billing import (
    InvalidWebhook,
    normalize_event,
    verify_signature,
    workspace_entitlement,
)


NOW = datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)
SECRET = "pdl_ntfset_unit_test_secret_only"
PRICE_ID = "pri_01m3y1nvmgw2avt60bz87161c2"
PRODUCT_ID = "pro_" + "a" * 26
SUBSCRIPTION_ID = "sub_" + "b" * 26
CUSTOMER_ID = "ctm_" + "c" * 26
EVENT_ID = "evt_" + "d" * 26
INTENT_TOKEN = "i" * 43


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


def event_payload():
    """A recurring trial snapshot, shaped like the actual Paddle webhook."""
    return {
        "event_id": EVENT_ID,
        "event_type": "subscription.created",
        "occurred_at": iso(NOW),
        "notification_id": "ntf_" + "e" * 26,
        "data": {
            "id": SUBSCRIPTION_ID,
            "customer_id": CUSTOMER_ID,
            "status": "trialing",
            "items": [{
                "quantity": 1,
                "recurring": True,
                "price": {"id": PRICE_ID, "product_id": PRODUCT_ID},
                "trial_dates": {
                    "starts_at": iso(NOW - timedelta(hours=1)),
                    "ends_at": iso(NOW + timedelta(days=30)),
                },
            }],
            "current_billing_period": {
                "starts_at": iso(NOW - timedelta(hours=1)),
                "ends_at": iso(NOW + timedelta(days=30)),
            },
            "next_billed_at": iso(NOW + timedelta(days=30)),
            "scheduled_change": None,
            "custom_data": {
                "userId": "not-authoritative-browser-user",
                "checkoutIntent": INTENT_TOKEN,
            },
        },
    }


def raw_event(payload=None):
    return json.dumps(payload if payload is not None else event_payload()).encode("utf-8")


def signed_header(body, timestamp=None, secret=SECRET):
    timestamp = int(NOW.timestamp()) if timestamp is None else timestamp
    signed = str(timestamp).encode("ascii") + b":" + body
    digest = hmac.new(secret.encode("utf-8"), signed, sha256).hexdigest()
    return f"ts={timestamp};h1={digest}"


def subscription(**changes):
    snapshot = {
        "subscription_id": SUBSCRIPTION_ID,
        "customer_id": CUSTOMER_ID,
        "occurred_at": NOW,
        "status": "active",
        "price_id": PRICE_ID,
        "product_id": PRODUCT_ID,
        "quantity": 1,
        "trial_starts_at": None,
        "trial_ends_at": None,
        "current_period_starts_at": NOW - timedelta(days=1),
        "current_period_ends_at": NOW + timedelta(days=29),
        "next_billed_at": NOW + timedelta(days=29),
        "scheduled_action": None,
        "scheduled_effective_at": None,
    }
    snapshot.update(changes)
    return snapshot


def test_signature_authenticates_original_bytes_before_parsing():
    body = b'{ "message": "caf\xc3\xa9", "amount": 1 }\n'
    header = signed_header(body)
    assert verify_signature(body, header, SECRET, now=NOW.timestamp()) is None
    # The same JSON value with different spacing is not the signed payload.
    transformed = json.dumps(json.loads(body)).encode("utf-8")
    with pytest.raises(InvalidWebhook):
        verify_signature(transformed, header, SECRET, now=NOW.timestamp())


def test_signature_does_not_authenticate_another_destination_secret():
    body = raw_event()
    with pytest.raises(InvalidWebhook):
        verify_signature(body, signed_header(body), "another-destination", now=NOW.timestamp())


def test_signature_accepts_any_matching_h1_during_rotation():
    body = raw_event()
    header = signed_header(body)
    invalid = "0" * 64
    assert verify_signature(body, header + ";h1=" + invalid, SECRET, now=NOW.timestamp()) is None
    timestamp, valid = header.split(";")
    assert verify_signature(body, f"{timestamp};h1={invalid};{valid}", SECRET, now=NOW.timestamp()) is None


@pytest.mark.parametrize("offset", [-5, 0, 5])
def test_signature_freshness_boundary_accepts_five_seconds(offset):
    body = raw_event()
    timestamp = int(NOW.timestamp()) + offset
    verify_signature(body, signed_header(body, timestamp), SECRET, now=NOW.timestamp())


@pytest.mark.parametrize("offset", [-6, 6, -3600, 3600])
def test_signature_rejects_replay_and_future_timestamp(offset):
    body = raw_event()
    with pytest.raises(InvalidWebhook):
        verify_signature(body, signed_header(body, int(NOW.timestamp()) + offset), SECRET, now=NOW.timestamp())


@pytest.mark.parametrize("header", [
    None, "", "h1=" + "0" * 64,
    "ts=not-a-time;h1=" + "0" * 64,
    "ts=-1;h1=" + "0" * 64,
    "ts=1791050400;h1=not-hex",
    "ts=1791050400;h1=" + "0" * 63,
    "ts=1791050400;h1=" + "g" * 64,
    "ts=1791050400;h2=" + "0" * 64,
])
def test_signature_rejects_malformed_or_unsupported_header(header):
    with pytest.raises(InvalidWebhook):
        verify_signature(raw_event(), header, SECRET, now=NOW.timestamp())


def test_duplicate_timestamp_is_not_ambiguous():
    body = raw_event()
    with pytest.raises(InvalidWebhook):
        verify_signature(body, signed_header(body) + f";ts={int(NOW.timestamp())}", SECRET, now=NOW.timestamp())


def test_empty_secret_never_authenticates():
    body = raw_event()
    with pytest.raises(InvalidWebhook):
        verify_signature(body, signed_header(body, secret=""), "", now=NOW.timestamp())


def test_normalized_snapshot_keeps_subscription_facts_without_raw_identity_or_token():
    body = raw_event()
    event = normalize_event(body)
    assert event["event_id"] == EVENT_ID
    assert event["event_type"] == "subscription.created"
    assert event["occurred_at"] == NOW
    assert event["payload_hash"] == sha256(body).hexdigest()
    assert event["subscription_id"] == SUBSCRIPTION_ID
    assert event["customer_id"] == CUSTOMER_ID
    assert event["price_id"] == PRICE_ID
    assert event["product_id"] == PRODUCT_ID
    assert event["quantity"] == 1
    assert event["status"] == "trialing"
    assert event["trial_starts_at"] == NOW - timedelta(hours=1)
    assert event["trial_ends_at"] == NOW + timedelta(days=30)
    assert event["current_period_ends_at"] == NOW + timedelta(days=30)
    assert event["intent_hash"] == sha256(INTENT_TOKEN.encode()).hexdigest()
    assert INTENT_TOKEN not in repr(event)
    assert "not-authoritative-browser-user" not in repr(event)


def test_browser_user_id_cannot_change_authoritative_normalized_binding():
    first = event_payload()
    second = deepcopy(first)
    second["data"]["custom_data"]["userId"] = "somebody-elses-account"
    one, two = normalize_event(raw_event(first)), normalize_event(raw_event(second))
    # Only the audit hash changes; identity never enters the persisted snapshot.
    one.pop("payload_hash")
    two.pop("payload_hash")
    assert one == two


@pytest.mark.parametrize("token", [None, 123, {}, "", "bad token with spaces"])
def test_missing_or_invalid_intent_is_unlinked_not_browser_identity_fallback(token):
    payload = event_payload()
    payload["data"]["custom_data"]["checkoutIntent"] = token
    assert normalize_event(raw_event(payload))["intent_hash"] is None


def test_lifecycle_update_without_custom_data_can_use_existing_subscription_binding():
    payload = event_payload()
    payload["event_type"] = "subscription.canceled"
    payload["data"]["status"] = "canceled"
    payload["data"]["custom_data"] = None
    event = normalize_event(raw_event(payload))
    assert event["subscription_id"] == SUBSCRIPTION_ID
    assert event["status"] == "canceled"
    assert event["intent_hash"] is None


@pytest.mark.parametrize("event_type", ["transaction.completed", "customer.updated", "unrecognized.event"])
def test_non_subscription_events_are_ignored(event_type):
    payload = event_payload()
    payload["event_type"] = event_type
    assert normalize_event(raw_event(payload)) is None


@pytest.mark.parametrize("body", [
    b"not-json", b"[]", b"null", b"42", b'{"event_type":"subscription.updated"}',
    b'{"event_id":"one","event_id":"two"}',
])
def test_invalid_envelope_and_duplicate_keys_are_rejected(body):
    with pytest.raises(InvalidWebhook):
        normalize_event(body)


def test_nested_duplicate_subscription_status_is_rejected():
    body = raw_event().replace(b'"status": "trialing"', b'"status": "active", "status": "trialing"')
    with pytest.raises(InvalidWebhook):
        normalize_event(body)


@pytest.mark.parametrize("field,value", [
    ("id", "sub_bad"), ("id", "sub_" + "B" * 26),
    ("customer_id", "ctm_bad"), ("customer_id", None),
])
def test_invalid_entity_identity_is_rejected(field, value):
    payload = event_payload()
    payload["data"][field] = value
    with pytest.raises(InvalidWebhook):
        normalize_event(raw_event(payload))


@pytest.mark.parametrize("value", ["not-a-date", "2026-10-03T18:00:00", None])
def test_event_time_requires_timezone_aware_timestamp(value):
    payload = event_payload()
    payload["occurred_at"] = value
    with pytest.raises(InvalidWebhook):
        normalize_event(raw_event(payload))


@pytest.mark.parametrize("change", ["extra-item", "non-recurring", "zero-quantity", "boolean-quantity"])
def test_unexpected_subscription_items_cannot_produce_pro_entitlement(change):
    payload = event_payload()
    item = payload["data"]["items"][0]
    if change == "extra-item":
        payload["data"]["items"].append(deepcopy(item))
    elif change == "non-recurring":
        item["recurring"] = False
    elif change == "zero-quantity":
        item["quantity"] = 0
    else:
        item["quantity"] = True
    if change in {"zero-quantity", "boolean-quantity"}:
        with pytest.raises(InvalidWebhook):
            normalize_event(raw_event(payload))
    else:
        event = normalize_event(raw_event(payload))
        assert workspace_entitlement([event], PRICE_ID, now=NOW)["plan"] == "free"


def test_unknown_subscription_status_is_preserved_but_has_no_paid_access():
    payload = event_payload()
    payload["data"]["status"] = "future_status"
    event = normalize_event(raw_event(payload))
    assert event["status"] == "unknown"
    assert workspace_entitlement([event], PRICE_ID, now=NOW)["plan"] == "free"


def test_large_signed_quantity_is_persistable_but_revokes_pro_access():
    payload = event_payload()
    payload["event_type"] = "subscription.updated"
    payload["data"]["items"][0]["quantity"] = 1001
    event = normalize_event(raw_event(payload))
    # Unsupported quantities still reach the durable snapshot handler, instead
    # of leaving an older Pro grant behind after a database constraint failure.
    assert event["quantity"] == 0
    assert workspace_entitlement([event], PRICE_ID, now=NOW)["plan"] == "free"


@pytest.mark.parametrize("status", ["canceled", "paused", "past_due", "future_status"])
def test_non_eligible_status_does_not_grant_pro(status):
    assert workspace_entitlement([subscription(status=status)], PRICE_ID, now=NOW)["plan"] == "free"


def test_active_pro_is_bounded_by_server_subscription_period():
    result = workspace_entitlement([subscription()], PRICE_ID, now=NOW)
    assert result["plan"] == "pro"
    assert result["status"] == "active"
    assert datetime.fromisoformat(result["accessUntil"].replace("Z", "+00:00")) == NOW + timedelta(days=29)


def test_trial_grants_pro_until_paddle_trial_end():
    result = workspace_entitlement([subscription(
        status="trialing", trial_starts_at=NOW - timedelta(hours=1),
        trial_ends_at=NOW + timedelta(days=30),
        current_period_ends_at=NOW + timedelta(days=30),
    )], PRICE_ID, now=NOW)
    assert result["plan"] == "pro"
    assert result["status"] == "trialing"
    assert datetime.fromisoformat(result["trialEndsAt"].replace("Z", "+00:00")) == NOW + timedelta(days=30)


@pytest.mark.parametrize("changes", [
    {"price_id": "pri_" + "f" * 26}, {"price_id": None},
    {"quantity": 2}, {"quantity": 0}, {"quantity": True},
    {"current_period_ends_at": None}, {"current_period_ends_at": NOW},
    {"current_period_ends_at": NOW - timedelta(seconds=1)},
    {"current_period_starts_at": NOW + timedelta(days=1)},
    {"status": "trialing", "trial_ends_at": NOW},
])
def test_invalid_price_quantity_or_access_dates_fail_closed(changes):
    assert workspace_entitlement([subscription(**changes)], PRICE_ID, now=NOW)["plan"] == "free"


@pytest.mark.parametrize("action", ["cancel", "pause"])
def test_scheduled_change_is_enforced_without_waiting_for_next_webhook(action):
    row = subscription(scheduled_action=action, scheduled_effective_at=NOW + timedelta(hours=1))
    before = workspace_entitlement([row], PRICE_ID, now=NOW)
    assert before["plan"] == "pro"
    assert datetime.fromisoformat(before["accessUntil"].replace("Z", "+00:00")) == NOW + timedelta(hours=1)
    assert workspace_entitlement([row], PRICE_ID, now=NOW + timedelta(hours=1))["plan"] == "free"


def test_cleared_scheduled_change_restores_period_deadline():
    cleared = subscription(scheduled_action=None, scheduled_effective_at=None)
    assert workspace_entitlement([cleared], PRICE_ID, now=NOW + timedelta(hours=2))["plan"] == "pro"


def test_cancelled_old_subscription_does_not_override_new_active_subscription():
    old = subscription(status="canceled", subscription_id="sub_" + "0" * 26)
    current = subscription()
    for rows in ([old, current], [current, old]):
        assert workspace_entitlement(rows, PRICE_ID, now=NOW)["plan"] == "pro"


def test_empty_workspace_has_free_access():
    result = workspace_entitlement([], PRICE_ID, now=NOW)
    assert result["plan"] == "free"
    assert result["accessUntil"] is None
