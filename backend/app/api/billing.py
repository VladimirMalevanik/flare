"""Authenticated workspace billing and the strictly signed Sandbox webhook."""

import asyncio
from hashlib import sha256
import json
import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
import psycopg
from starlette.concurrency import run_in_threadpool

from app.api.auth import verified_user
from app.models.billing import BillingRepository
from app.models.database import MembershipRequiredError, WritePermissionRequiredError
from app.services.auth_service import AuthenticatedUser
from app.services.paddle_billing import (
    InvalidWebhook, MAX_WEBHOOK_BYTES, normalize_event, verify_signature,
    workspace_entitlement,
)


router = APIRouter(prefix="/billing", tags=["billing"])
logger = logging.getLogger("uvicorn.error")
WEBHOOK_PATH = "/billing/paddle/webhook"


def _error(status, code, message):
    return HTTPException(status, {"code": code, "message": message})


def billing_repository(request: Request) -> BillingRepository:
    database = request.app.state.database
    if database is None:
        raise _error(503, "billing_unavailable", "Billing is temporarily unavailable")
    return BillingRepository(database)


def _configured(request):
    configured = request.app.state.settings
    if not configured.paddle_billing_enabled:
        raise _error(503, "billing_not_configured", "Sandbox billing is not configured")
    return configured


async def _read_body(request: Request, maximum: int) -> bytes:
    size = request.headers.get("content-length")
    if size is not None:
        try:
            if int(size) < 0 or int(size) > maximum:
                raise ValueError
        except ValueError:
            raise _error(413, "billing_body_too_large", "Request body is too large") from None
    data = bytearray()
    async def receive():
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > maximum:
                raise _error(413, "billing_body_too_large", "Request body is too large")
        return bytes(data)
    try:
        return await asyncio.wait_for(receive(), timeout=2)
    except asyncio.TimeoutError:
        raise _error(408, "billing_body_timeout", "Request body timed out") from None


@router.get("/status")
def billing_status(request: Request,
                   user: Annotated[AuthenticatedUser, Depends(verified_user)]):
    configured = request.app.state.settings
    try:
        rows = billing_repository(request).subscriptions(user.identity)
        state = workspace_entitlement(rows, configured.paddle_pro_price_id)
    except (psycopg.Error, RuntimeError):
        raise _error(503, "billing_unavailable", "Could not verify subscription") from None
    except MembershipRequiredError:
        raise _error(403, "billing_membership", "Workspace membership is required") from None
    owner = user.role == "owner"
    return {
        "environment": "sandbox", "workspaceId": str(user.workspace_id), **state,
        "canManageBilling": owner,
        "checkoutAvailable": owner and configured.paddle_billing_enabled and state["plan"] == "free",
    }


@router.post("/checkout-intents", status_code=201)
async def create_checkout_intent(request: Request,
                                user: Annotated[AuthenticatedUser, Depends(verified_user)]):
    configured = _configured(request)
    if user.role != "owner":
        raise _error(403, "billing_owner_required", "Only the workspace owner can manage billing")
    if not user.email or not user.user_id.startswith("auth:"):
        raise _error(403, "billing_account_required", "Sign in with a verified Flare account")
    raw = await _read_body(request, 1024)
    if raw:
        try:
            if json.loads(raw) != {}:
                raise ValueError
        except (ValueError, UnicodeError, RecursionError):
            raise _error(400, "billing_invalid_request", "Checkout does not accept account or price fields") from None
    repository = billing_repository(request)
    try:
        state = await run_in_threadpool(repository.subscriptions, user.identity)
        if workspace_entitlement(state, configured.paddle_pro_price_id)["plan"] == "pro":
            raise _error(409, "billing_already_pro", "This workspace already has Pro")
        token = secrets.token_urlsafe(32)
        expires = await run_in_threadpool(repository.create_intent, user.identity,
                                         sha256(token.encode()).hexdigest(),
                                         configured.paddle_pro_price_id, 7200)
    except (MembershipRequiredError, WritePermissionRequiredError, psycopg.errors.InsufficientPrivilege):
        raise _error(403, "billing_owner_required", "Only the workspace owner can manage billing") from None
    except (psycopg.Error, RuntimeError):
        raise _error(503, "billing_unavailable", "Checkout is temporarily unavailable") from None
    return {
        "environment": "sandbox", "priceId": configured.paddle_pro_price_id,
        "quantity": 1, "email": user.email,
        "customData": {"userId": user.user_id, "checkoutIntent": token},
        "expiresAt": expires.isoformat(),
    }


def require_pro(request: Request,
                user: Annotated[AuthenticatedUser, Depends(verified_user)]) -> AuthenticatedUser:
    """Server dependency for Pro features; never authorize using browser plan flags."""
    if billing_status(request, user)["plan"] != "pro":
        raise _error(403, "pro_required", "This feature requires an active workspace Pro subscription")
    return user


@router.post("/paddle/webhook")
async def paddle_webhook(request: Request):
    configured = _configured(request)
    if len(request.headers.getlist("paddle-signature")) != 1:
        raise _error(401, "billing_invalid_signature", "Invalid webhook signature")
    raw = await _read_body(request, MAX_WEBHOOK_BYTES)
    try:
        verify_signature(raw, request.headers.get("paddle-signature"), configured.paddle_webhook_secret)
    except InvalidWebhook:
        raise _error(401, "billing_invalid_signature", "Invalid webhook signature") from None
    try:
        event = normalize_event(raw)
    except InvalidWebhook:
        raise _error(400, "billing_invalid_payload", "Invalid webhook payload") from None
    if event is None:
        return {"received": True, "outcome": "ignored"}
    try:
        outcome = await asyncio.wait_for(
            run_in_threadpool(billing_repository(request).apply_event, event), timeout=2.5)
    except (psycopg.Error, RuntimeError, asyncio.TimeoutError):
        # No successful ACK before durable commit. Paddle retries and DB dedupes.
        raise _error(503, "billing_unavailable", "Webhook processing is temporarily unavailable") from None
    if outcome not in {"applied", "duplicate", "stale", "unlinked", "conflict"}:
        raise _error(503, "billing_unavailable", "Webhook processing is temporarily unavailable")
    # Enum-only telemetry. No event payload, checkout intent, email or signature.
    logger.info("paddle_sandbox_webhook outcome=%s", outcome)
    return {"received": True, "outcome": outcome}
