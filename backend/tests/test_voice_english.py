import asyncio

import httpx

from app.ai_engine.groq_voice_adapter import GroqVoiceTranscriber
from app.ai_engine.voice import AudioInput, Transcript
from app.ai_engine.voice_config import VoiceSettings


def test_groq_voice_request_is_explicitly_english():
    audio = AudioInput(
        b"\x1aE\xdf\xa3test",
        "memo.webm",
        "audio/webm;codecs=opus",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert b'name="language"\r\n\r\nen' in request.content
        assert b'name="response_format"\r\n\r\njson' in request.content
        return httpx.Response(200, json={"text": "hello world"})

    async def run() -> Transcript:
        async with GroqVoiceTranscriber(
            VoiceSettings(api_key="test-key"),
            transport=httpx.MockTransport(handler),
        ) as adapter:
            return await adapter.transcribe(audio)

    assert asyncio.run(run()) == Transcript("hello world")
