import asyncio
from dataclasses import replace

import httpx
import pytest

from app.ai_engine.voice import AudioInput, Transcript, VoiceError
from app.ai_engine.voice_config import VoiceSettings, load_voice_settings
from app.ai_engine.groq_voice_adapter import GroqVoiceTranscriber

AUDIO = AudioInput(b'\x1aE\xdf\xa3test', 'memo.webm', 'audio/webm;codecs=opus')
SETTINGS = VoiceSettings(api_key='test-key')


def execute(handler, audio=AUDIO, settings=SETTINGS):
    async def run():
        async with GroqVoiceTranscriber(settings, transport=httpx.MockTransport(handler)) as adapter:
            assert adapter._client.max_retries == 0
            return await adapter.transcribe(audio)
    return asyncio.run(run())


@pytest.mark.parametrize('audio', [AUDIO,
    AudioInput(b'RIFF\x00\x00\x00\x00WAVEtest', 'memo.wav', 'audio/wav'),
    AudioInput(b'ID3test', 'memo.mp3', 'audio/mpeg'),
    AudioInput(b'\x00\x00\x00\x18ftypM4A ', 'memo.m4a', 'audio/mp4'),
    AudioInput(b'\x00\x00\x00\x18ftypisom', 'memo.mp4', 'audio/mp4'),
    AudioInput(b'OggStest', 'memo.ogg', 'audio/ogg'),
])
def test_contract_and_request(audio):
    def handler(request):
        assert str(request.url) == 'https://api.groq.com/openai/v1/audio/transcriptions'
        assert request.method == 'POST'
        assert b'whisper-large-v3-turbo' in request.content
        assert b'name="response_format"\r\n\r\njson' in request.content
        assert b'filename="recording.' in request.content
        assert audio.content in request.content
        assert request.extensions['timeout']['read'] == 45
        assert b'gpt-oss' not in request.content
        return httpx.Response(200, json={'text': '  hello world\n', 'unused': 'discard'})
    assert execute(handler, audio) == Transcript('hello world')


@pytest.mark.parametrize('audio', [
    replace(AUDIO, content=b''), replace(AUDIO, content=b'x' * (10 * 1024 * 1024 + 1)),
    replace(AUDIO, content='wrong'), replace(AUDIO, content_type='application/octet-stream'),
    replace(AUDIO, filename='memo.wav'), replace(AUDIO, content=b'not a container'),
    *[replace(AUDIO, filename=name) for name in ['../memo.webm', '/tmp/memo.webm', 'C:\\memo.webm', 'x\r\n.webm', 'x\x00.webm']],
    replace(AUDIO, content_type='audio/webm;evil=1'), 'https://example.com/audio.webm',
])
def test_invalid_input_before_network(audio):
    def handler(_):
        pytest.fail('Invalid input reached network')
    with pytest.raises(VoiceError, match='invalid_request'):
        execute(handler, audio)


@pytest.mark.parametrize('payload', [{}, {'text': ''}, {'text': '  '}, {'text': 123},
    {'text': None}, {'text': []}, {'text': 'a' * 30001}, [], 'text'])
def test_invalid_output(payload):
    with pytest.raises(VoiceError, match='invalid_output'):
        execute(lambda _: httpx.Response(200, json=payload))


def test_malformed_json():
    with pytest.raises(VoiceError, match='invalid_output'):
        execute(lambda _: httpx.Response(200, content=b'private broken body', headers={'content-type': 'application/json'}))


@pytest.mark.parametrize('status,code', [(400, 'invalid_request'), (401, 'provider_auth'),
    (403, 'provider_auth'), (408, 'timeout'), (409, 'provider_transient'),
    (429, 'rate_limited'), (500, 'provider_server'), (503, 'provider_server')])
def test_errors_sanitized_no_retries(status, code):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={'error': {'message': 'PRIVATE AUDIO SECRET'}})
    with pytest.raises(VoiceError) as caught:
        execute(handler)
    assert caught.value.code == code
    assert len(calls) == 1
    assert 'PRIVATE' not in str(caught.value)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None


@pytest.mark.parametrize('error,code', [(httpx.ReadTimeout, 'timeout'), (httpx.ConnectError, 'network')])
def test_transport_errors(error, code):
    calls = []
    def handler(request):
        calls.append(request)
        raise error('PRIVATE', request=request)
    with pytest.raises(VoiceError, match=code) as caught:
        execute(handler)
    assert len(calls) == 1
    assert caught.value.__context__ is None


def test_deadline():
    async def handler(_):
        await asyncio.sleep(1)
        return httpx.Response(200, json={'text': 'late'})
    with pytest.raises(VoiceError, match='timeout'):
        execute(handler, settings=replace(SETTINGS, provider_deadline_seconds=0.01))


@pytest.mark.parametrize('changes', [{'model': 'whisper-large-v3'}, {'model': 'openai/gpt-oss-20b'},
    {'api_key': None}, {'max_upload_bytes': 0}, {'max_duration_seconds': 601},
    {'provider_deadline_seconds': float('nan')}, {'max_transcript_chars': 200001}])
def test_configuration(changes):
    with pytest.raises(VoiceError, match='configuration'):
        execute(lambda _: pytest.fail('Network'), settings=replace(SETTINGS, **changes))


def test_environment(monkeypatch):
    monkeypatch.setenv('VOICE_MAX_UPLOAD_BYTES', '1000')
    monkeypatch.setenv('VOICE_MAX_DURATION_SECONDS', '240')
    assert load_voice_settings().max_upload_bytes == 1000
    assert load_voice_settings().max_duration_seconds == 240
    monkeypatch.setenv('VOICE_PROVIDER_DEADLINE_SECONDS', 'bad')
    with pytest.raises(ValueError, match='Invalid voice configuration'):
        load_voice_settings()


@pytest.mark.parametrize('role,key,expected', [
    ('worker', 'test-only-key', 'FAILED: local file or configuration is invalid'),
    ('worker', '', 'SKIPPED: worker GROQ_API_KEY is not configured'),
    ('api', 'test-only-key', 'FAILED: worker environment is invalid'),
    ('migration', 'test-only-key', 'FAILED: worker environment is invalid'),
])
def test_smoke_initializes_selected_worker_environment(tmp_path, role, key, expected):
    import os
    from pathlib import Path
    import subprocess
    import sys
    selected = tmp_path / 'selected.env'
    selected.write_text(f'FLARE_PROCESS_ROLE={role}\nGROQ_API_KEY={key}\n')
    env = {**os.environ, 'FLARE_DOTENV_PATH': str(selected)}
    env.pop('GROQ_API_KEY', None)
    env.pop('PYTHON_DOTENV_DISABLED', None)
    script = Path(__file__).resolve().parents[1] / 'scripts/smoke_groq_voice.py'
    # A missing local file prevents any provider request, even with a test key.
    result = subprocess.run([sys.executable, str(script), str(tmp_path / 'missing.webm'),
                             '--content-type', 'audio/webm', '--live'],
                            env=env, capture_output=True, text=True)
    assert result.returncode != 0
    assert expected in result.stderr
    assert 'test-only-key' not in result.stdout + result.stderr
