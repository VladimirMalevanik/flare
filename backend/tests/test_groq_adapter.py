import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from app.config import AISettings
from app.ai_engine.analysis import Evidence
from app.ai_engine.groq_adapter import GroqTextAnalyzer
from app.ai_engine.errors import AnalysisError

SOURCES = [Evidence(source_id='s1', content='Use PostgreSQL.')]


def completion(content='{"observations": []}', **changes):
    return {'id': 'chat-test', 'object': 'chat.completion', 'created': 0,
            'model': 'openai/gpt-oss-20b',
            'choices': [{'index': 0, 'finish_reason': 'stop',
                         'message': {'role': 'assistant', 'content': content}}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20, 'total_tokens': 120},
            **changes}


def execute(handler, evidence=SOURCES, settings=None):
    async def run():
        async with GroqTextAnalyzer(settings or AISettings(api_key='test-key'),
                                    transport=httpx.MockTransport(handler)) as analyzer:
            return await analyzer.analyze(evidence)
    return asyncio.run(run())


def test_actual_sdk_request_contract_and_metadata():
    calls = []
    def handler(request):
        calls.append(request)
        assert str(request.url) == 'https://api.groq.com/openai/v1/chat/completions'
        body = json.loads(request.content)
        assert body['model'] == 'openai/gpt-oss-20b'
        assert body['reasoning_effort'] == 'low'
        assert body['include_reasoning'] is False and body['stream'] is False
        assert body['max_completion_tokens'] == 2000
        assert body['response_format']['json_schema']['strict'] is True
        assert 'tools' not in body and 'reasoning_format' not in body
        assert request.extensions['timeout']['connect'] == 5
        return httpx.Response(200, json=completion(), headers={'x-request-id': 'req-test'})
    result = execute(handler)
    assert len(calls) == 1
    assert result.analysis.observations == []
    assert result.metadata.request_id == 'req-test'
    assert result.metadata.input_tokens == 100
    assert result.metadata.completion_tokens == 20
    assert result.metadata.validation_outcome == 'valid'


@pytest.mark.parametrize('evidence', [
    [], SOURCES * 2,
    [Evidence(source_id='s1', content='x' * (AISettings().max_input_bytes + 1))],
])
def test_bad_input_makes_no_request(evidence):
    def handler(_):
        pytest.fail('Invalid input reached provider')
    with pytest.raises(AnalysisError, match="invalid_request"):
        execute(handler, evidence)


@pytest.mark.parametrize('status,code,retryable', [
    (400, 'invalid_request', False), (401, 'provider_auth', False),
    (403, 'provider_auth', False), (404, 'invalid_request', False),
    (408, 'timeout', True), (409, 'provider_transient', True),
    (413, 'invalid_request', False), (422, 'invalid_request', False),
    (429, 'rate_limited', True), (500, 'provider_server', True),
    (503, 'provider_server', True),
])
def test_status_errors_are_safe_and_never_retried(status, code, retryable):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={'error': {'message': 'private-provider-body'}},
                              headers={'retry-after': '17', 'x-request-id': 'req-error'})
    with pytest.raises(AnalysisError) as caught:
        execute(handler)
    error = caught.value
    assert error.code == code and error.retryable is retryable
    assert len(calls) == 1
    assert error.retry_after_seconds == 17
    assert error.metadata.request_id == 'req-error'
    assert error.metadata.validation_outcome == 'not_run'
    assert error.__context__ is None
    assert 'private-provider-body' not in str(error)


@pytest.mark.parametrize('kind,code', [(httpx.ReadTimeout, 'timeout'), (httpx.ConnectError, 'network')])
def test_transport_errors(kind, code):
    calls = []
    def handler(request):
        calls.append(request)
        raise kind('private-network-body', request=request)
    with pytest.raises(AnalysisError) as caught:
        execute(handler)
    assert caught.value.code == code and caught.value.retryable
    assert caught.value.__context__ is None
    assert len(calls) == 1


@pytest.mark.parametrize('content', [
    '', 'not json', '{}', '{"observations": null}',
    '{"observations": [{"category":"fact","text":"invented","evidence":[{"source_id":"forged","quote":"Use PostgreSQL."}]}]}',
])
def test_invalid_output_is_normalized(content):
    with pytest.raises(AnalysisError) as caught:
        execute(lambda _: httpx.Response(200, json=completion(content)))
    assert caught.value.code == 'invalid_output'
    assert caught.value.metadata.validation_outcome == 'invalid'
    assert caught.value.__context__ is None


def test_nonempty_analysis_and_whitespace_quote():
    output = {'observations': [{'category': 'decision', 'text': 'Use PostgreSQL.',
              'evidence': [{'source_id': 's1', 'quote': 'Use\nPostgreSQL.'}]}]}
    result = execute(lambda _: httpx.Response(200, json=completion(json.dumps(output))))
    assert result.analysis.observations[0].evidence[0].source_id == 's1'
    assert result.metadata.configured_model == result.metadata.returned_model
    assert result.metadata.prompt_version == result.metadata.schema_version == 'text-analysis-v1'
    assert result.metadata.finish_reason == 'stop' and result.metadata.latency_ms >= 0


@pytest.mark.parametrize('body', [
    completion(model='openai/gpt-oss-120b'),
    completion(choices=[]),
    completion(choices=[{'index': 0, 'finish_reason': 'length',
                        'message': {'role': 'assistant', 'content': '{"observations": []}'}}]),
    completion(choices=[{'index': 0, 'finish_reason': 'stop',
                        'message': {'role': 'assistant', 'content': '{"observations": []}', 'refusal': 'refused'}}]),
    {}, {'choices': None},
])
def test_wrong_model_incomplete_refusal_or_bad_envelope(body):
    with pytest.raises(AnalysisError) as caught:
        execute(lambda _: httpx.Response(200, json=body))
    assert caught.value.code == 'invalid_output'


def test_absent_usage_is_not_zero():
    result = execute(lambda _: httpx.Response(200, json=completion(usage=None)))
    assert result.metadata.input_tokens is None and result.metadata.completion_tokens is None


def test_total_deadline_and_client_cleanup():
    calls = []
    async def slow(request):
        calls.append(request)
        await asyncio.sleep(1)
        return httpx.Response(200, json=completion())
    with pytest.raises(AnalysisError) as caught:
        execute(slow, settings=AISettings(api_key='test-key', deadline_seconds=0.01))
    assert caught.value.code == 'timeout' and len(calls) == 1


def test_full_request_byte_boundary_without_truncation():
    from app.ai_engine.prompts import request_size_bytes
    settings = AISettings(api_key='test-key')
    async def run():
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json=completion())
        transport = httpx.MockTransport(handler)
        async with GroqTextAnalyzer(settings, transport=transport) as probe:
            size = request_size_bytes(probe._request(SOURCES))
        async with GroqTextAnalyzer(replace(settings, max_input_bytes=size), transport=transport) as exact:
            await exact.analyze(SOURCES)
        async with GroqTextAnalyzer(replace(settings, max_input_bytes=size - 1), transport=transport) as small:
            with pytest.raises(AnalysisError, match='invalid_request'):
                await small.analyze(SOURCES)
        assert len(calls) == 1
        assert json.loads(json.loads(calls[0].content)['messages'][1]['content'])['evidence'][0]['content'] == SOURCES[0].content
    asyncio.run(run())


def test_no_private_data_in_debug_logs_or_normalized_error(caplog, monkeypatch):
    import logging
    monkeypatch.setenv('GROQ_LOG', 'debug')
    caplog.set_level(logging.DEBUG)
    logging.getLogger('groq._base_client').setLevel(logging.DEBUG)
    secret, private = 'private-test-api-key', 'private-unpublished-note'
    def handler(_):
        return httpx.Response(400, json={'error': {'message': f'{secret} {private}'}})
    with pytest.raises(AnalysisError) as caught:
        execute(handler, [Evidence(source_id='s1', content=private)], AISettings(api_key=secret))
    assert secret not in caplog.text and private not in caplog.text
    assert secret not in repr(caught.value) and private not in repr(caught.value)
    assert caught.value.__context__ is None


def test_factory_missing_key_is_explicit(monkeypatch):
    from app.ai_engine.groq_adapter import create_text_analyzer
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    with pytest.raises(AnalysisError, match='configuration'):
        create_text_analyzer()


def test_retry_after_header_parsing():
    from app.ai_engine.groq_adapter import retry_after
    assert retry_after(None) is None
    assert retry_after('nan') is None
    assert retry_after('bad-value') is None
    assert retry_after('12.5') == 12.5
    assert retry_after('Wed, 01 Jan 2020 00:00:00 GMT') == 0
