"""Async Groq boundary for already-authorized evidence; no database or HTTP routes."""

import asyncio
import logging
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from collections.abc import Sequence
from dataclasses import replace
from time import perf_counter

import httpx
import groq
from app.ai_engine.groq_structured import create_strict_completion
from groq import AsyncGroq

from app.config import AISettings, load_ai_settings
from app.ai_engine.errors import AnalysisError
from app.ai_engine.analysis import AnalysisMetadata, AnalysisResult, Evidence, TextAnalysis, validate_evidence
from app.ai_engine.prompts import PROMPT_VERSION, SCHEMA_VERSION, build_bounded_request


class GroqTextAnalyzer:
    def __init__(self, settings: AISettings, *, transport: httpx.AsyncBaseTransport | None = None):
        try:
            settings.validate()
            if not isinstance(settings.api_key, str) or not settings.api_key.strip():
                raise ValueError('Missing key')
        except (ValueError, TypeError):
            raise AnalysisError('configuration') from None
        # SDK debug logs include request bodies. Keep them disabled for this boundary,
        # even if the application enables root DEBUG or GROQ_LOG=debug.
        for name in ('groq', 'groq._base_client', 'groq._response'):
            logging.getLogger(name).setLevel(logging.WARNING)
        self.settings = settings
        self._client = AsyncGroq(
            api_key=settings.api_key,
            base_url=settings.base_url,
            max_retries=0,
            timeout=httpx.Timeout(settings.request_timeout_seconds, connect=settings.connect_timeout_seconds),
            http_client=httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False),
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.close()

    def _request(self, evidence: Sequence[Evidence]) -> dict:
        return build_bounded_request(evidence, self.settings)

    async def analyze(self, evidence: Sequence[Evidence]) -> AnalysisResult:
        started = perf_counter()
        metadata = AnalysisMetadata(self.settings.model, PROMPT_VERSION, SCHEMA_VERSION)
        try:
            evidence = tuple(evidence)
            request = self._request(evidence)
        except (ValueError, TypeError):
            raise AnalysisError('invalid_request', metadata=metadata) from None

        failure = None
        raw = None
        try:
            async with asyncio.timeout(self.settings.deadline_seconds):
                raw = await create_strict_completion(self._client, request)
                response = await raw.parse()
        except (groq.APITimeoutError, TimeoutError):
            failure = AnalysisError('timeout', retryable=True)
        except groq.APIConnectionError:
            failure = AnalysisError('network', retryable=True)
        except groq.APIStatusError as error:
            metadata = replace(metadata, request_id=error.response.headers.get('x-request-id'))
            code, retryable = status_error(error.status_code)
            failure = AnalysisError(code, retryable=retryable,
                                    retry_after_seconds=retry_after(error.response.headers.get('retry-after')))
        except (groq.APIResponseValidationError, ValueError, TypeError):
            failure = AnalysisError('invalid_output')
        except groq.APIError:
            failure = AnalysisError('provider_failure')
        metadata = replace(metadata, latency_ms=(perf_counter() - started) * 1000)
        if raw is not None:
            metadata = replace(metadata, request_id=raw.headers.get('x-request-id'))
        if failure is not None:
            failure.metadata = replace(metadata, validation_outcome=(
                'invalid' if failure.code == 'invalid_output' else 'not_run'))
            # Raise outside the except block: don't retain the raw exception/body.
            raise failure

        try:
            if len(response.choices) != 1:
                raise ValueError('Expected one completion')
            choice = response.choices[0]
            metadata = replace(
                metadata, returned_model=response.model, completion_id=response.id,
                input_tokens=response.usage.prompt_tokens if response.usage else None,
                completion_tokens=response.usage.completion_tokens if response.usage else None,
                finish_reason=choice.finish_reason,
            )
            if response.model != self.settings.model or choice.finish_reason != 'stop':
                raise ValueError('Incomplete or unexpected model response')
            if not choice.message.content or getattr(choice.message, 'refusal', None):
                raise ValueError('No analysis')
            analysis = TextAnalysis.model_validate_json(choice.message.content)
            validate_evidence(analysis, evidence)
        except (ValueError, TypeError, AttributeError, IndexError):
            failure = AnalysisError('invalid_output', metadata=replace(metadata, validation_outcome='invalid'))
        if failure is not None:
            raise failure
        return AnalysisResult(analysis, replace(metadata, validation_outcome='valid',
                                               latency_ms=(perf_counter() - started) * 1000))


def status_error(status: int):
    if status in (401, 403):
        return 'provider_auth', False
    if status == 429:
        return 'rate_limited', True
    if status == 408:
        return 'timeout', True
    if status == 409:
        return 'provider_transient', True
    if status >= 500:
        return 'provider_server', True
    if 400 <= status < 500:
        return 'invalid_request', False
    return 'provider_failure', False


def retry_after(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            date = parsedate_to_datetime(value)
            seconds = (date - datetime.now(timezone.utc)).total_seconds()
        except (ValueError, TypeError, OverflowError):
            return None
    return max(0.0, seconds) if math.isfinite(seconds) else None


def create_text_analyzer() -> GroqTextAnalyzer:
    """Explicit opt-in factory, never called by normal API startup or Note saving."""
    try:
        settings = load_ai_settings()
    except ValueError:
        raise AnalysisError('configuration') from None
    return GroqTextAnalyzer(settings)
