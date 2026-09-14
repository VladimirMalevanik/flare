"""Explicit local-file Whisper smoke; never run by CI, never writes to DB."""
import argparse
import asyncio
from dataclasses import replace
import json
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', type=Path)
    parser.add_argument('--content-type', required=True)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    if not args.live:
        parser.error('Pass --live to authorize one real Groq request')
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.environment import load_project_dotenv
    try:
        load_project_dotenv(allowed_roles={'worker'})
    except RuntimeError:
        parser.exit(2, 'FAILED: worker environment is invalid.\n')
    if not os.getenv('GROQ_API_KEY', '').strip():
        parser.exit(2, 'SKIPPED: worker GROQ_API_KEY is not configured.\n')
    from app.ai_engine.voice import AudioInput, VoiceError
    from app.ai_engine.voice_config import load_voice_settings
    from app.ai_engine.groq_voice_adapter import GroqVoiceTranscriber

    async def run():
        # The explicit local smoke runs under the worker secret boundary. The
        # web API uses the separate VOICE_GROQ_API_KEY deployment secret.
        settings = replace(load_voice_settings(), api_key=os.environ['GROQ_API_KEY'])
        # Bounded read, even when the file grows after selection.
        with args.audio.open('rb') as source:
            content = source.read(settings.max_upload_bytes + 1)
        audio = AudioInput(content, args.audio.name, args.content_type)
        async with GroqVoiceTranscriber(settings) as transcriber:
            transcript = await transcriber.transcribe(audio)
        print(json.dumps({'model': settings.model, 'text': transcript.text}, ensure_ascii=False))
    try:
        asyncio.run(run())
    except VoiceError as error:
        parser.exit(1, f'FAILED: {error.code}\n')
    except (OSError, ValueError):
        parser.exit(1, 'FAILED: local file or configuration is invalid\n')


if __name__ == '__main__':
    main()
