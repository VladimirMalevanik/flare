"""Private account grants and bounded manual SMTP delivery (no follow-up jobs)."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import os
import re
import smtplib
from uuid import UUID

from app.services.auth_service import AuthenticatedUser
from app.services.email import EmailSender
from app.services.smtp_email import SmtpEmailSender

MAX_RECIPIENTS = 20
MAX_SUBJECT = 200
MAX_BODY = 20_000
_ADDRESS = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+\Z")


def mailbox(value: str) -> str:
    """Accept a single ASCII mailbox, never headers or display-name syntax."""
    value = value.strip()
    if len(value) > 254 or not _ADDRESS.fullmatch(value):
        raise ValueError("Enter a valid email address")
    local, domain = value.split("@")
    if len(local) > 64 or local.startswith(".") or local.endswith(".") or ".." in local:
        raise ValueError("Enter a valid email address")
    if any(len(label) > 63 for label in domain.split(".")):
        raise ValueError("Enter a valid email address")
    return value


def account_grants() -> dict[str, str]:
    """Fail closed on absent or malformed private release-owner configuration.

    Pin both the account ID and its email; a new signup using the same email must
    never inherit a deleted developer's access. No email list enters source or JS.
    """
    try:
        raw = json.loads(os.environ.get("DEVELOPER_MAIL_ACCOUNTS", "{}"))
        if not isinstance(raw, dict) or not 1 <= len(raw) <= 6:
            return {}
        grants = {}
        for user_id, email in raw.items():
            if not isinstance(user_id, str) or not user_id.startswith("auth:"):
                return {}
            if str(UUID(user_id[5:])) != user_id[5:]:
                return {}
            grants[user_id] = mailbox(email).lower()
        return grants
    except (ValueError, TypeError, AttributeError):
        return {}


def can_send(user: AuthenticatedUser) -> bool:
    return bool(
        user.email_verified
        and user.legal_accepted
        and account_grants().get(user.user_id) == user.email.strip().lower()
    )


def configured_sender(settings) -> tuple[EmailSender | None, str | None]:
    # Never reuse main's LoggingEmailSender: local logging is not delivery.
    if not settings.smtp_url or not settings.email_from:
        return None, None
    try:
        sender_address = mailbox(settings.email_from)
        return SmtpEmailSender(settings.smtp_url, sender_address), sender_address
    except (ValueError, TypeError):
        return None, None


@dataclass(frozen=True)
class SendOutcome:
    recipient: str
    status: str


def _send_one(sender: EmailSender, recipient: str, subject: str, body: str) -> SendOutcome:
    try:
        sender.send(to=recipient, subject=subject, text=body)
        return SendOutcome(recipient, "accepted")
    except (smtplib.SMTPRecipientsRefused, smtplib.SMTPSenderRefused,
            smtplib.SMTPDataError, smtplib.SMTPAuthenticationError,
            smtplib.SMTPConnectError, smtplib.SMTPNotSupportedError):
        # Explicit SMTP rejection means the message was not accepted.
        return SendOutcome(recipient, "failed")
    except Exception:
        # Disconnect/timeout (including QUIT after DATA) can follow acceptance.
        # Never expose provider credentials, recipient responses, or message text.
        return SendOutcome(recipient, "unknown")


async def send_copies(sender: EmailSender, recipients: list[str], subject: str,
                      body: str) -> list[SendOutcome]:
    slots = asyncio.Semaphore(4)

    async def deliver(recipient: str) -> SendOutcome:
        async with slots:
            return await asyncio.to_thread(_send_one, sender, recipient, subject, body)

    return list(await asyncio.gather(*(deliver(address) for address in recipients)))
