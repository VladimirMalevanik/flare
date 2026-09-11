"""Stage 2 Groq adapter; no DB, retrieval, or public routes."""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import replace
from time import perf_counter

import httpx
import groq
from app.ai_engine.groq_structured import create_strict_completion
from groq import AsyncGroq

from app.config import AISettings
from app.ai_engine.errors import AnalysisError
from app.ai_engine.analysis import AnalysisMetadata, Evidence, TextAnalysis, validate_evidence
from app.ai_engine.flare_prompts import PROMPT_VERSION, SCHEMA_VERSION, build_flare_request
from app.ai_engine.flare_config import FlareSettings
from app.ai_engine.flares import FlareCandidates, FlareResult, validate_candidates
from app.ai_engine.groq_adapter import status_error, retry_after
import json


class GroqFlareDetector:
    def __init__(self, settings: AISettings, flare_settings: FlareSettings | None = None, *, transport: httpx.AsyncBaseTransport | None = None):
        try:
            settings.validate()
            self.flare_settings = flare_settings or FlareSettings()
            self.flare_settings.validate()
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

    def _request(self, analysis: TextAnalysis, evidence: Sequence[Evidence]) -> dict:
        if not 1 <= len(evidence) <= self.settings.max_sources:
            raise ValueError('Invalid evidence count')
        if any(not isinstance(source, Evidence) for source in evidence):
            raise ValueError('Typed evidence is required')
        if len({source.source_id for source in evidence}) != len(evidence):
            raise ValueError('Duplicate evidence source IDs')
        # Reject oversized content before building a potentially large JSON request.
        if sum(len(source.content.encode('utf-8')) for source in evidence) > self.settings.max_input_bytes:
            raise ValueError('AI input size limit exceeded')
        validate_evidence(analysis, tuple(evidence))
        request = build_flare_request(analysis, evidence)
        request.update(
            model=self.settings.model, reasoning_effort=self.settings.reasoning_effort,
            max_completion_tokens=self.flare_settings.max_completion_tokens,
            include_reasoning=False, stream=False,
        )
        if len(json.dumps(request, ensure_ascii=False).encode()) > self.flare_settings.max_request_bytes:
            raise ValueError('AI input size limit exceeded')
        return request

    async def detect(self, analysis: TextAnalysis, evidence: Sequence[Evidence]) -> FlareResult:
        started = perf_counter()
        metadata = AnalysisMetadata(self.settings.model, PROMPT_VERSION, SCHEMA_VERSION)
        try:
            evidence = tuple(evidence)
            request = self._request(analysis, evidence)
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
            candidates = FlareCandidates.model_validate_json(choice.message.content)
            candidates = validate_candidates(candidates, analysis, evidence)
        except (ValueError, TypeError, AttributeError, IndexError):
            failure = AnalysisError('invalid_output', metadata=replace(metadata, validation_outcome='invalid'))
        if failure is not None:
            raise failure
        return FlareResult(candidates, replace(metadata, validation_outcome='valid',
                                               latency_ms=(perf_counter() - started) * 1000))
