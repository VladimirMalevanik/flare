"""Authenticated transient voice upload -> English transcript -> durable item."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.ai_engine.groq_voice_adapter import create_voice_transcriber
from app.ai_engine.media_inspection import FfprobeMediaInspector, MediaInspectionError
from app.ai_engine.voice import AudioInput, VoiceError
from app.ai_engine.voice_config import load_voice_settings
from app.api.auth import verified_user
from app.api.schemas import ItemResponse
from app.models.database import Database
from app.services.auth_service import AuthenticatedUser
from app.services.voice_service import VoiceTranscriptService


router = APIRouter(prefix="/voice", tags=["voice"])

_MEDIA_EXTENSIONS = {
    "audio/webm": "webm",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/wave": "wav",
    "audio/mpeg": "mp3",
    "audio/mp3": "mp3",
    "audio/mp4": "m4a",
    "audio/x-m4a": "m4a",
    "audio/ogg": "ogg",
}


def _database(request: Request) -> Database:
    database = request.app.state.database
    if database is None:
        raise HTTPException(status_code=503, detail="Database is unavailable")
    return database


async def _read_bounded_audio(request: Request, max_bytes: int, deadline: float) -> bytes:
    chunks: list[bytes] = []
    size = 0
    try:
        async with asyncio.timeout(deadline):
            async for chunk in request.stream():
                if not chunk:
                    continue
                size += len(chunk)
                if size > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Voice recording is too large",
                    )
                chunks.append(bytes(chunk))
    except TimeoutError:
        raise HTTPException(status_code=408, detail="Voice upload timed out") from None
    if size <= 0:
        raise HTTPException(status_code=422, detail="Voice recording is empty")
    return b"".join(chunks)


def _voice_error(error: VoiceError) -> HTTPException:
    if error.code in {"invalid_request", "invalid_output"}:
        return HTTPException(status_code=422, detail="Voice transcription could not be completed")
    if error.code == "rate_limited":
        return HTTPException(status_code=429, detail="Voice transcription is temporarily busy")
    if error.code == "timeout":
        return HTTPException(status_code=504, detail="Voice transcription timed out")
    if error.code in {
        "configuration",
        "provider_auth",
        "network",
        "provider_server",
        "provider_transient",
        "provider_failure",
    }:
        return HTTPException(status_code=503, detail="Voice transcription is temporarily unavailable")
    return HTTPException(status_code=503, detail="Voice transcription is temporarily unavailable")


def _inspection_error(error: MediaInspectionError) -> HTTPException:
    if error.code == "audio_too_long":
        return HTTPException(status_code=422, detail="Voice recording is too long")
    if error.code == "invalid_audio":
        return HTTPException(status_code=422, detail="Voice recording is not valid audio")
    if error.code == "inspection_timeout":
        return HTTPException(status_code=504, detail="Voice recording inspection timed out")
    return HTTPException(status_code=503, detail="Voice recording inspection is unavailable")


@router.post("/transcribe", response_model=ItemResponse, response_model_by_alias=True)
async def transcribe_voice(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(verified_user)],
    database: Annotated[Database, Depends(_database)],
) -> ItemResponse:
    """Keep source audio transient; persist only the validated English-first transcript."""
    try:
        settings = load_voice_settings()
    except ValueError:
        raise HTTPException(status_code=503, detail="Voice transcription is not configured") from None

    content_type = request.headers.get("content-type", "")
    base_type = content_type.split(";", 1)[0].strip().lower()
    extension = _MEDIA_EXTENSIONS.get(base_type)
    if extension is None:
        raise HTTPException(status_code=415, detail="Unsupported voice recording type")

    content = await _read_bounded_audio(
        request,
        settings.max_upload_bytes,
        settings.upload_deadline_seconds,
    )
    audio = AudioInput(
        content=content,
        filename=f"recording.{extension}",
        content_type=content_type,
    )

    try:
        audio.validate(settings.max_upload_bytes)
        inspector = FfprobeMediaInspector(
            max_duration_seconds=settings.max_duration_seconds,
            timeout_seconds=settings.media_inspection_timeout_seconds,
            max_upload_bytes=settings.max_upload_bytes,
            ffprobe_path=settings.ffprobe_path,
        )
        await inspector.duration_seconds(audio)
        async with create_voice_transcriber() as transcriber:
            transcript = await transcriber.transcribe(audio)
        item = VoiceTranscriptService(
            database,
            user.identity,
            max_upload_bytes=settings.max_upload_bytes,
        ).persist(
            transcript,
            media_type=base_type,
            upload_size=len(content),
        )
    except MediaInspectionError as error:
        raise _inspection_error(error) from None
    except VoiceError as error:
        raise _voice_error(error) from None
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Voice recording is invalid") from None

    return ItemResponse.from_record(item)
