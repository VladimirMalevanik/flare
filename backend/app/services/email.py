"""Outbound email boundary."""
from typing import Protocol


class EmailSender(Protocol):
    def send(self, *, to: str, subject: str, text: str) -> None: ...


def verification_message(app_public_url: str, token: str, ttl_seconds: int) -> tuple[str, str]:
    link = f"{app_public_url.rstrip('/')}/verify-email?token={token}"
    subject = "Verify your Flare email"
    ttl_minutes = max(1, ttl_seconds // 60)
    lifetime = (
        f"{ttl_minutes // 60} hour(s)"
        if ttl_minutes >= 60 and ttl_minutes % 60 == 0
        else f"{ttl_minutes} minute(s)"
    )
    text = (
        f"Confirm your email address to finish setting up your workspace:\n\n"
        f"{link}\n\n"
        f"The link expires in {lifetime}."
    )
    return subject, text
