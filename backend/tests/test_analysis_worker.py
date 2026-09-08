"""Configuration and scheduling tests need no database or provider."""
import asyncio
from dataclasses import replace
from time import monotonic

import pytest

from app.ai_engine.analysis import AnalysisMetadata
from app.ai_engine.errors import AnalysisError
from app.config import AISettings
from app.services.analysis_jobs import retry_delay, safe_metadata
from app.workers.analysis_worker import run_loop
from app.workers.config import WorkerSettings, pipeline_revision


@pytest.mark.parametrize('changes', [
    {'max_attempts': 0}, {'max_attempts': 11}, {'lease_seconds': 70},
    {'lease_seconds': 3601}, {'poll_seconds': 0}, {'backoff_seconds': float('nan')},
    {'max_backoff_seconds': float('inf')}, {'max_backoff_seconds': 1},
])
def test_invalid_worker_configuration(changes):
    with pytest.raises(ValueError):
        replace(WorkerSettings(), **changes).validate(AISettings())


def test_pipeline_revision_changes_only_for_work_identity():
    ai = AISettings()
    assert pipeline_revision(ai) == pipeline_revision(replace(ai, api_key='unused-private-key'))
    assert pipeline_revision(ai) != pipeline_revision(replace(ai, max_completion_tokens=1000))
    assert 'unused-private-key' not in pipeline_revision(ai)


def test_retry_backoff_jitter_cap_and_hint(monkeypatch):
    settings = WorkerSettings()
    monkeypatch.setattr('app.services.analysis_jobs.random.uniform', lambda a,b: 1.0)
    transient = AnalysisError('network', retryable=True)
    assert [retry_delay(transient, n, settings) for n in (1,2,3,10)] == [5,10,20,300]
    assert retry_delay(AnalysisError('rate_limited', retryable=True, retry_after_seconds=900), 2, settings) == 900
    assert retry_delay(AnalysisError('provider_auth', retryable=True), 1, settings) is None
    assert retry_delay(AnalysisError('network', retryable=False), 1, settings) is None


def test_metadata_excludes_multiline_provider_values():
    metadata = AnalysisMetadata('openai/gpt-oss-20b', 'v1', 'v1', request_id='PRIVATE NOTE\nsecret', input_tokens=-1)
    safe = safe_metadata(metadata)
    assert safe['request_id'] is None and safe['input_tokens'] is None
    assert 'PRIVATE' not in str(safe)


def test_idle_worker_waits_and_stops():
    async def scenario():
        stop = asyncio.Event()
        class Empty:
            settings = WorkerSettings(poll_seconds=0.02)
            calls = 0
            async def process_one(self):
                self.calls += 1
                if self.calls == 2:
                    stop.set()
                return None
        processor = Empty()
        started = monotonic()
        await run_loop(processor, stop)
        assert processor.calls == 2 and monotonic() - started >= 0.02
    asyncio.run(scenario())
