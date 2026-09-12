"""Outbound email boundary."""
from typing import Protocol


class EmailSender(Protocol):
    def send(self, *, to: str, subject: str, text: str) -> None: ...


def verification_message(app_public_url: str, token: str, ttl_hours: int) -> tuple[str, str]:
    link = f"{app_public_url.rstrip('/')}/verify-email?token={token}"
    subject = "Verify your Flare email"
    text = (
        f"Confirm your email address to finish setting up your workspace:\n\n"
        f"{link}\n\n"
        f"The link expires in {ttl_hours} hour(s)."
    )
    return subject, text
