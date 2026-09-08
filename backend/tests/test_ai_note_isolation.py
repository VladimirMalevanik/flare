"""The opt-in AI component must not affect the existing authenticated Note flow."""
import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from test_auth_service import auth  # noqa: F401; disposable PostgreSQL cleanup

pytestmark = pytest.mark.integration


def test_missing_or_invalid_ai_config_never_calls_provider_for_notes(auth, monkeypatch):
    from app.ai_engine.groq_adapter import GroqTextAnalyzer
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    monkeypatch.setenv('LLM_MAX_INPUT_BYTES', 'invalid-on-purpose')
    def forbidden(*args, **kwargs):
        pytest.fail('Note API constructed an AI provider')
    monkeypatch.setattr(GroqTextAnalyzer, '__init__', forbidden)
    settings = Settings(database_url=os.environ['DATABASE_URL'], environment='test',
                        cors_origins=['http://testserver'])
    with TestClient(create_app(settings), headers={'Origin': 'http://testserver'}) as client:
        assert client.post('/auth/register', json={
            'email': f'{uuid4()}@auth-test.invalid', 'password': 'a-long-test-password', 'name': 'Test',
        }).status_code == 201
        created = client.post('/items', json={'type': 'note', 'content': 'No AI required.'})
        assert created.status_code == 201
        assert client.get('/items/' + created.json()['id']).json()['content'] == 'No AI required.'
        assert client.delete('/items/' + created.json()['id']).status_code == 204
