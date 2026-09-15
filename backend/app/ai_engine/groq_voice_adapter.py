"""Official Groq Whisper boundary; no persistence, analysis, URLs or retries."""
import asyncio
import logging

import groq
import httpx
from groq import AsyncGroq

from app.ai_engine.groq_adapter import status_error
from app.ai_engine.voice import AudioInput, Transcript, VoiceError
from app.ai_engine.voice_config import VoiceSettings, load_voice_settings


class GroqVoiceTranscriber:
    def __init__(self, settings: VoiceSettings, *, transport: httpx.AsyncBaseTransport | None = None):
        try:
            settings.validate()
            if not isinstance(settings.api_key, str) or not settings.api_key.strip():
                raise ValueError('Missing key')
        except (ValueError, TypeError):
            raise VoiceError('configuration') from None
        for name in ('groq', 'groq._base_client', 'groq._response'):
            logging.getLogger(name).setLevel(logging.WARNING)
        self.settings = settings
        self._client = AsyncGroq(
            api_key=settings.api_key, base_url='https://api.groq.com', max_retries=0,
            timeout=httpx.Timeout(settings.provider_deadline_seconds, connect=min(5.0, settings.provider_deadline_seconds)),
            http_client=httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False),
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.aclose()

    async def aclose(self):
        await self._client.close()

    async def transcribe(self, audio: AudioInput) -> Transcript:
        try:
            if not isinstance(audio, AudioInput):
                raise ValueError('Typed audio required')
            filename, mime = audio.validate(self.settings.max_upload_bytes)
        except (ValueError, TypeError):
            raise VoiceError('invalid_request') from None
        failure = None
        try:
            async with asyncio.timeout(self.settings.provider_deadline_seconds):
                response = await self._client.audio.transcriptions.with_raw_response.create(
                    model=self.settings.model,
                    file=(filename, audio.content, mime),
                    language='en',
                    response_format='json',
                )
            # Inspect the original JSON too: SDK permissive construction must not coerce text.
            payload = response.http_response.json()
            text = payload.get("text") if isinstance(payload, dict) else None
            if not isinstance(text, str) or len(text) > self.settings.max_transcript_chars:
                raise ValueError('Invalid transcript')
            result = Transcript(text)
        except (groq.APITimeoutError, TimeoutError):
            failure = VoiceError('timeout', retryable=True)
        except groq.APIConnectionError:
            failure = VoiceError('network', retryable=True)
        except groq.APIStatusError as error:
            code, retryable = status_error(error.status_code)
            failure = VoiceError(code, retryable=retryable)
        except (groq.APIResponseValidationError, ValueError, TypeError, AttributeError):
            failure = VoiceError('invalid_output')
        except groq.APIError:
            failure = VoiceError('provider_failure')
        if failure is not None:
            # Raise outside handlers so raw provider exceptions/bodies are not retained.
            raise failure
        return result


def create_voice_transcriber() -> GroqVoiceTranscriber:
    try:
        settings = load_voice_settings()
    except ValueError:
        raise VoiceError('configuration') from None
    return GroqVoiceTranscriber(settings)
