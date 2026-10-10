"""Manual team mail, authorized independently of customer workspace roles."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.api.auth import verified_user
from app.services.auth_service import AuthenticatedUser
from app.services.developer_mail import (
    MAX_BODY, MAX_RECIPIENTS, MAX_SUBJECT, can_send, configured_sender, mailbox,
    send_copies,
)

router = APIRouter(prefix="/mail", tags=["developer-mail"])


class MailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    recipients: list[str] = Field(min_length=1, max_length=MAX_RECIPIENTS)
    subject: str = Field(min_length=1, max_length=MAX_SUBJECT)
    body: str = Field(min_length=1, max_length=MAX_BODY)

    @field_validator("recipients")
    @classmethod
    def addresses(cls, values: list[str]) -> list[str]:
        normalized = [mailbox(value) for value in values]
        if len({value.lower() for value in normalized}) != len(normalized):
            raise ValueError("Remove duplicate recipients")
        return normalized

    @field_validator("subject")
    @classmethod
    def subject_line(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Enter a single-line subject")
        return value.strip()

    @field_validator("body")
    @classmethod
    def message_text(cls, value: str) -> str:
        if not value.strip() or any(ord(char) < 32 and char not in "\r\n\t" for char in value):
            raise ValueError("Enter a message")
        return value


class MailOutcome(BaseModel):
    recipient: str
    status: Literal["accepted", "failed", "unknown"]


def _developer(user: Annotated[AuthenticatedUser, Depends(verified_user)]) -> AuthenticatedUser:
    if not can_send(user):
        raise HTTPException(403, detail={"code": "developer_mail_forbidden"})
    return user


@router.get("/capability")
def capability(request: Request, response: Response,
               user: Annotated[AuthenticatedUser, Depends(verified_user)]) -> dict:
    response.headers["Cache-Control"] = "no-store"
    if not can_send(user):
        return {"allowed": False}
    sender, address = configured_sender(request.app.state.settings)
    return {"allowed": True, "ready": sender is not None, "sender": address,
            "maxRecipients": MAX_RECIPIENTS}


@router.post("/send", response_model=list[MailOutcome])
async def send_mail(payload: MailRequest, request: Request, response: Response,
                    user: Annotated[AuthenticatedUser, Depends(_developer)]) -> list[MailOutcome]:
    del user
    response.headers["Cache-Control"] = "no-store"
    sender, _ = configured_sender(request.app.state.settings)
    if sender is None:
        raise HTTPException(503, detail={"code": "developer_mail_unavailable"})
    return [MailOutcome(recipient=outcome.recipient, status=outcome.status)
            for outcome in await send_copies(sender, payload.recipients, payload.subject, payload.body)]
