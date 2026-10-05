"""Sandbox webhook authentication and bounded subscription entitlement rules.

Browser checkout events never grant access. Only verified Paddle snapshots,
bound to a server-issued checkout intent in PostgreSQL, enter this service.
"""

from datetime import datetime, timezone
from hashlib import sha256
import hmac
import json
import re
import time


SUBSCRIPTION_EVENTS = frozenset({
    "subscription.created", "subscription.updated", "subscription.trialing",
    "subscription.activated", "subscription.past_due", "subscription.paused",
    "subscription.resumed", "subscription.canceled",
})
STATUSES = frozenset({"trialing", "active", "past_due", "paused", "canceled"})
MAX_WEBHOOK_BYTES = 256 * 1024


class InvalidWebhook(ValueError):
    """A generic error that never includes raw customer data or credentials."""


def verify_signature(raw_body: bytes, header: str | None, secret: str,
                     now: float | None = None) -> None:
    """Authenticate exactly ts:raw_body, including all JSON whitespace."""
    if not secret or not header or len(header) > 2048:
        raise InvalidWebhook("Invalid webhook signature")
    timestamp = None
    signatures = []
    for part in header.split(";"):
        key, separator, value = part.strip().partition("=")
        if not separator:
            raise InvalidWebhook("Invalid webhook signature")
        if key == "ts" and timestamp is None and re.fullmatch(r"[0-9]{1,12}", value):
            timestamp = value
        elif key == "h1" and re.fullmatch(r"[0-9a-fA-F]{64}", value):
            signatures.append(value.lower())
        else:
            raise InvalidWebhook("Invalid webhook signature")
    if timestamp is None or not 1 <= len(signatures) <= 8:
        raise InvalidWebhook("Invalid webhook signature")
    current = time.time() if now is None else now
    if abs(current - int(timestamp)) > 5:
        raise InvalidWebhook("Invalid webhook signature")
    expected = hmac.new(secret.encode(), timestamp.encode() + b":" + raw_body,
                        sha256).hexdigest()
    if not any(hmac.compare_digest(expected, candidate) for candidate in signatures):
        raise InvalidWebhook("Invalid webhook signature")


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidWebhook("Invalid webhook payload")
        result[key] = value
    return result


def _invalid_constant(_value):
    raise InvalidWebhook("Invalid webhook payload")


def _id(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(prefix + r"_[a-z0-9]{26}", value):
        raise InvalidWebhook("Invalid webhook payload")
    return value


def _date(value, *, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise InvalidWebhook("Invalid webhook payload")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise InvalidWebhook("Invalid webhook payload") from None


def _period(value):
    if value is None:
        return None, None
    if not isinstance(value, dict):
        raise InvalidWebhook("Invalid webhook payload")
    start = _date(value.get("starts_at"), required=True)
    end = _date(value.get("ends_at"), required=True)
    if end <= start:
        raise InvalidWebhook("Invalid webhook payload")
    return start, end


def normalize_event(raw_body: bytes) -> dict | None:
    """Keep only the minimal billing fields; discard payment/address/email data."""
    if len(raw_body) > MAX_WEBHOOK_BYTES:
        raise InvalidWebhook("Invalid webhook payload")
    try:
        event = json.loads(raw_body, object_pairs_hook=_object,
                           parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidWebhook("Invalid webhook payload") from None
    if not isinstance(event, dict):
        raise InvalidWebhook("Invalid webhook payload")
    event_id = _id(event.get("event_id"), "evt")
    occurred_at = _date(event.get("occurred_at"), required=True)
    event_type = event.get("event_type")
    if not isinstance(event_type, str) or not re.fullmatch(r"[a-z_]+\.[a-z_]+", event_type):
        raise InvalidWebhook("Invalid webhook payload")
    if event_type not in SUBSCRIPTION_EVENTS:
        return None
    data = event.get("data")
    if not isinstance(data, dict):
        raise InvalidWebhook("Invalid webhook payload")
    status = data.get("status")
    if not isinstance(status, str) or not 1 <= len(status) <= 50:
        raise InvalidWebhook("Invalid webhook payload")
    if status not in STATUSES:
        status = "unknown"
    items = data.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 100:
        raise InvalidWebhook("Invalid webhook payload")
    item = items[0]
    if not isinstance(item, dict) or not isinstance(item.get("price"), dict):
        raise InvalidWebhook("Invalid webhook payload")
    quantity = item.get("quantity")
    if type(quantity) is not int or quantity < 1:
        raise InvalidWebhook("Invalid webhook payload")
    if len(items) != 1 or quantity != 1:
        quantity = 0  # Unsupported items/quantities revoke a previous Pro grant.
    if item.get("recurring") is False:
        status = "unknown"
    trial_start, trial_end = _period(item.get("trial_dates"))
    period_start, period_end = _period(data.get("current_billing_period"))
    scheduled = data.get("scheduled_change")
    action, effective_at = None, None
    if scheduled is not None:
        if not isinstance(scheduled, dict) or scheduled.get("action") not in {"cancel", "pause", "resume"}:
            raise InvalidWebhook("Invalid webhook payload")
        action = scheduled["action"]
        effective_at = _date(scheduled.get("effective_at"), required=True)
    custom = data.get("custom_data")
    token = custom.get("checkoutIntent") if isinstance(custom, dict) else None
    intent_hash = (sha256(token.encode()).hexdigest() if isinstance(token, str)
                   and re.fullmatch(r"[A-Za-z0-9_-]{43}", token) else None)
    return {
        "event_id": event_id, "event_type": event_type, "occurred_at": occurred_at,
        "payload_hash": sha256(raw_body).hexdigest(),
        "subscription_id": _id(data.get("id"), "sub"),
        "customer_id": _id(data.get("customer_id"), "ctm"),
        "status": status, "price_id": _id(item["price"].get("id"), "pri"),
        "product_id": _id(item["price"].get("product_id"), "pro"),
        "quantity": quantity, "trial_starts_at": trial_start, "trial_ends_at": trial_end,
        "current_period_starts_at": period_start, "current_period_ends_at": period_end,
        "next_billed_at": _date(data.get("next_billed_at")),
        "scheduled_action": action, "scheduled_effective_at": effective_at,
        "intent_hash": intent_hash,
    }


def _iso(value):
    return value.astimezone(timezone.utc).isoformat() if value is not None else None


def workspace_entitlement(subscriptions: list[dict], price_id: str | None,
                          now: datetime | None = None) -> dict:
    """Compute from persisted subscriptions on every request, never a sticky plan.

    Trial/period boundaries fail closed even if a cancellation webhook is delayed.
    An old canceled subscription cannot override another valid subscription.
    """
    current = now or datetime.now(timezone.utc)
    eligible = []
    for row in subscriptions:
        if row.get("environment", "sandbox") != "sandbox" or row.get("watermark_conflict"):
            continue
        if row["price_id"] != price_id or type(row["quantity"]) is not int or row["quantity"] != 1:
            continue
        status = row["status"]
        if status not in {"trialing", "active"}:
            continue
        start = row.get("trial_starts_at") if status == "trialing" else row.get("current_period_starts_at")
        end = row.get("trial_ends_at") if status == "trialing" else row.get("current_period_ends_at")
        # Paddle supplies trial_dates on its subscription item. Do not invent
        # another 30 days locally or grant unbounded access from missing dates.
        if start is None or end is None or not start <= current < end:
            continue
        if row.get("scheduled_action") in {"cancel", "pause"}:
            effective = row.get("scheduled_effective_at")
            if effective is None or effective <= current:
                continue
            end = min(end, effective)
        eligible.append((end, row))
    if eligible:
        access_until, selected = max(eligible, key=lambda pair: pair[0])
        plan = "pro"
    else:
        selected = max(subscriptions, key=lambda row: row["occurred_at"], default=None)
        access_until, plan = None, "free"
    return {
        "plan": plan, "status": selected["status"] if selected else None,
        "accessUntil": _iso(access_until),
        "trialEndsAt": _iso(selected.get("trial_ends_at")) if selected else None,
        "currentPeriodEndsAt": _iso(selected.get("current_period_ends_at")) if selected else None,
        "scheduledChange": ({"action": selected["scheduled_action"],
                             "effectiveAt": _iso(selected["scheduled_effective_at"])}
                            if selected and selected.get("scheduled_action") else None),
    }
