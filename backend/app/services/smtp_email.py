"""SMTP implementation and an explicit local-development sender."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import urlparse

class SmtpEmailSender:
    def __init__(self, smtp_url: str, default_from: str):
        parsed = urlparse(smtp_url)
        if parsed.scheme not in {"smtp", "smtps"} or not parsed.hostname:
            raise ValueError("SMTP_URL must be smtp:// or smtps://host[:port]")
        self._host = parsed.hostname
        self._port = parsed.port or (465 if parsed.scheme == "smtps" else 587)
        self._user = parsed.username
        self._password = parsed.password
        self._implicit_tls = parsed.scheme == "smtps"
        self._from = default_from

    def send(self, *, to: str, subject: str, text: str) -> None:
        message = EmailMessage()
        message["From"] = self._from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        if self._implicit_tls:
            with smtplib.SMTP_SSL(self._host, self._port, timeout=10) as client:
                self._deliver(client, message)
        else:
            with smtplib.SMTP(self._host, self._port, timeout=10) as client:
                client.starttls(context=ssl.create_default_context())
                self._deliver(client, message)

    def _deliver(self, client: smtplib.SMTP, message: EmailMessage) -> None:
        if self._user:
            client.login(self._user, self._password or "")
        client.send_message(message)


class LoggingEmailSender:
    """Local-only sender: prints the verification link for manual testing."""

    def send(self, *, to: str, subject: str, text: str) -> None:
        print(
            f"\n===== EMAIL =====\n"
            f"to:      {to}\n"
            f"subject: {subject}\n"
            f"{text}\n"
            f"=================\n",
            flush=True,
        )
