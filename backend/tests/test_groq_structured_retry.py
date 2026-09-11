import asyncio
import json

import httpx
import pytest

from app.config import AISettings
from app.ai_engine.analysis import Evidence, TextAnalysis
from app.ai_engine.errors import AnalysisError
from app.ai_engine.groq_adapter import GroqTextAnalyzer
from app.ai_engine.groq_flare_adapter import GroqFlareDetector
from test_groq_adapter import completion


@pytest.mark.parametrize('stage', ['text', 'flare'])
@pytest.mark.parametrize('case,count,error', [
    ('recover', 2, None), ('twice', 2, 'invalid_request'),
    ('unrelated', 1, 'invalid_request'), ('malformed', 1, 'invalid_request'),
    ('invalid_output', 2, 'invalid_output'), ('bad_citation', 2, 'invalid_output'),
    ('rate_limit', 1, 'rate_limited'), ('server', 1, 'provider_server'),
])
def test_strict_retry_boundary(stage, case, count, error):
    calls = []
    def handler(request):
        calls.append(request.content)
        body = json.loads(request.content)
        assert body['response_format']['json_schema']['strict'] is True
        assert body['model'] == 'openai/gpt-oss-20b'
        if case in ('rate_limit', 'server'):
            return httpx.Response(429 if case == 'rate_limit' else 503, json={'error': {'code': 'json_validate_failed'}})
        if case == 'malformed':
            return httpx.Response(400, text='not JSON')
        if len(calls) == 1 or case == 'twice':
            return httpx.Response(400, json={'error': {
                'code': 'invalid_request_error' if case == 'unrelated' else 'json_validate_failed',
                'message': 'Generated JSON does not match the expected schema.',
                'failed_generation': 'NEVER SALVAGE THIS',
            }})
        content = {'observations': []} if stage == 'text' else {'flares': []}
        if case == 'invalid_output':
            content['unexpected'] = 'invalid'
        if case == 'bad_citation':
            ref = {'source_id': 'invented', 'quote': 'Use PostgreSQL.'}
            content = ({'observations': [{'category': 'fact', 'text': 'Use PostgreSQL.', 'evidence': [ref]}]}
                       if stage == 'text' else {'flares': [{'type': 'Warning', 'title': 'Scope conflict',
                           'statement': 'The plan conflicts with the agreed scope.', 'action': None,
                           'reason': 'Integrations were deferred.', 'evidence': [{**ref, 'supports': ['conflict']}]}]})
        return httpx.Response(200, json=completion(json.dumps(content)))
    async def run():
        cls = GroqTextAnalyzer if stage == 'text' else GroqFlareDetector
        async with cls(AISettings(api_key='test-only'), transport=httpx.MockTransport(handler)) as adapter:
            evidence = [Evidence(source_id='s1', content='Use PostgreSQL.')]
            return await (adapter.analyze(evidence) if stage == 'text' else adapter.detect(TextAnalysis(observations=[]), evidence))
    if error:
        with pytest.raises(AnalysisError) as caught:
            asyncio.run(run())
        assert caught.value.code == error
        assert 'NEVER SALVAGE' not in str(caught.value)
        if error == 'invalid_request': assert not caught.value.retryable
    else:
        assert asyncio.run(run()).metadata.validation_outcome == 'valid'
    assert len(calls) == count
    if count == 2: assert calls[0] == calls[1]
