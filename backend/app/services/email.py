"""Outbound email boundary."""
from typing import Protocol
from urllib.parse import quote


class EmailSender(Protocol):
    def send(self, *, to: str, subject: str, text: str) -> None: ...


def password_reset_message(app_public_url: str, token: str) -> tuple[str, str]:
    # Fragments are not sent to the HTTP server or included in Referer headers.
    link = f"{app_public_url.rstrip('/')}/reset-password#token={token}"
    return "Reset your Flare password", (
        f"Someone requested a password reset for your Flare account.\n\n{link}\n\n"
        "This one-use link expires in 30 minutes. If you did not request it, "
        "ignore this email. Your password has not changed."
    )


def password_changed_message() -> tuple[str, str]:
    return "Your Flare password was changed", (
        "Your Flare password has been changed and your previous sessions have ended. "
        "Sign in again with your new password. If you did not make this change, "
        "request a new password reset from Flare and secure your email account."
    )


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


def scheduled_flares_message(
    app_public_url: str,
    flares: tuple[tuple[str, str], ...],
) -> tuple[str, str]:
    """Build a notification containing titles and product links, never evidence."""
    if not flares:
        raise ValueError("At least one Flare is required")
    subject = "Flare found something worth checking"
    lines = ["Flare found something worth checking:", ""]
    for flare_id, title in flares:
        safe_title = " ".join(title.split())
        if not safe_title:
            raise ValueError("Flare title is required")
        link = f"{app_public_url.rstrip('/')}/insights?insight={quote(flare_id, safe='')}"
        lines.extend((safe_title, link, ""))
    lines.append("Open Flare to review the details and supporting evidence.")
    return subject, "\n".join(lines)
