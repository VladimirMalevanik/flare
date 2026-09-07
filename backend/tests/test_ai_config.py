from dataclasses import replace

import pytest

from app.config import AISettings, load_ai_settings


def test_ai_defaults_without_key(monkeypatch):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    configured = load_ai_settings()
    assert configured.api_key is None
    assert configured.model == 'openai/gpt-oss-20b'
    assert configured.reasoning_effort == 'low'
    assert configured.base_url == 'https://api.groq.com'
    assert 'private-test-key' not in repr(AISettings(api_key='private-test-key'))


@pytest.mark.parametrize('values', [
    {'model': 'openai/gpt-oss-120b'}, {'reasoning_effort': 'high'},
    {'base_url': 'https://api.groq.com/openai/v1'},
    {'base_url': 'https://other.invalid'}, {'max_input_bytes': 0},
    {'max_sources': -1}, {'max_completion_tokens': 65537},
    {'deadline_seconds': float('nan')}, {'request_timeout_seconds': 0},
])
def test_invalid_ai_configuration(values):
    with pytest.raises(ValueError):
        replace(AISettings(), **values).validate()


def test_bad_environment_is_sanitized(monkeypatch):
    monkeypatch.setenv('LLM_MAX_INPUT_BYTES', 'private-invalid-value')
    with pytest.raises(ValueError, match='^Invalid AI configuration$'):
        load_ai_settings()
