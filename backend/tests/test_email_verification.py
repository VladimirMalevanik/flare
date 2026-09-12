import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.auth_service import AuthService, EmailNotVerified, VerificationInvalid
from test_auth_service import auth


pytestmark = pytest.mark.integration


class CapturingSender:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    def send(self, *, to: str, subject: str, text: str) -> None:
        self.sent.append({"to": to, "subject": subject, "text": text})


def test_registration_sends_link_and_login_is_blocked_until_verified(auth):
    sender = CapturingSender()
    service = AuthService(
        auth.database,
        email_verification_required=True,
        email_sender=sender,
        app_public_url="https://app.flare.test",
    )
    email = f"{uuid4()}@auth-test.invalid"
    service.register(email, "a-long-test-password", "Unverified")
    assert len(sender.sent) == 1
    token = sender.sent[0]["text"].split("token=")[1].split()[0]

    with pytest.raises(EmailNotVerified):
        service.login(email, "a-long-test-password")

    service.verify_email(token)
    assert service.current(service.login(email, "a-long-test-password")).email_verified

    with pytest.raises(VerificationInvalid):
        service.verify_email(token)