"""Durable orchestration around the pure Block 2 analyzer. No HTTP entry point."""
import asyncio
from dataclasses import asdict
import math
import random
import re
from uuid import UUID, uuid4

import psycopg

from app.ai_engine.analysis import Evidence, TextAnalysis, validate_evidence
from app.ai_engine.errors import AnalysisError
from app.ai_engine.llm import TextAnalyzer
from app.ai_engine.prompts import PROMPT_VERSION, SCHEMA_VERSION
from app.config import AISettings
from app.models.analysis_jobs import AnalysisJobs, WorkerJobs
from app.models.database import WorkspaceIdentity
from app.workers.config import WorkerSettings, pipeline_revision

RETRYABLE = {'rate_limited', 'timeout', 'network', 'provider_transient', 'provider_server'}


def retry_delay(error: AnalysisError, attempt: int, settings: WorkerSettings) -> float | None:
    if not error.retryable or error.code not in RETRYABLE:
        return None
    delay = min(settings.max_backoff_seconds,
                settings.backoff_seconds * 2 ** (attempt - 1) * random.uniform(0.5, 1.5))
    hint = error.retry_after_seconds
    if hint is not None and math.isfinite(hint) and hint >= 0:
        delay = max(delay, hint)
    return delay


def safe_metadata(metadata) -> dict | None:
    if metadata is None:
        return None
    data = asdict(metadata)
    # Persist only the contract's allowlisted fields, never SDK bodies/reasoning.
    result = {}
    for key in ('configured_model', 'prompt_version', 'schema_version', 'returned_model',
                'request_id', 'completion_id', 'finish_reason', 'validation_outcome'):
        value = data.get(key)
        result[key] = value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_./:-]{1,200}', value) else None
    for key in ('input_tokens', 'completion_tokens'):
        value = data.get(key)
        result[key] = value if type(value) is int and value >= 0 else None
    value = data.get('latency_ms')
    result['latency_ms'] = value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None
    return result


class AnalysisJobService:
    def __init__(self, queue: AnalysisJobs, ai: AISettings, settings: WorkerSettings):
        settings.validate(ai)
        self.queue, self.ai, self.settings = queue, ai, settings

    def enqueue(self, identity: WorkspaceIdentity, chunks: tuple[UUID, ...]) -> UUID:
        if not 1 <= len(chunks) <= min(self.ai.max_sources, 100):
            raise ValueError('Invalid analysis source count')
        return self.queue.enqueue(identity, chunks, pipeline_revision(self.ai), self.settings.max_attempts)


    def start_run(self, identity: WorkspaceIdentity, key: UUID, generation_revision: str):
        from app.models.analysis_runs import AnalysisRuns, DailyLimitReached
        try:
            with self.queue.database.workspace_transaction(identity, write=True) as conn:
                return AnalysisRuns.start(conn, identity, key, self.ai, pipeline_revision(self.ai),
                                          generation_revision, self.settings.max_attempts)
        except psycopg.errors.UniqueViolation as error:
            if (
                getattr(getattr(error, "diag", None), "constraint_name", None)
                == "analysis_cycles_workspace_local_date_key"
            ):
                raise DailyLimitReached("daily_limit") from None
            raise

    def read_run(self, identity: WorkspaceIdentity, run_id: UUID):
        from app.models.analysis_runs import AnalysisRuns
        with self.queue.database.workspace_transaction(identity) as conn:
            return AnalysisRuns.read(conn, run_id)


class AnalysisProcessor:
    def __init__(self, jobs: WorkerJobs, analyzer: TextAnalyzer, ai: AISettings,
                 settings: WorkerSettings, *, owner: UUID | None = None):
        settings.validate(ai)
        self.jobs, self.analyzer, self.ai, self.settings = jobs, analyzer, ai, settings
        self.owner = owner or uuid4()

    async def process_one(self) -> str | None:
        claim = await asyncio.to_thread(self.jobs.claim, self.owner, self.settings.lease_seconds)
        if claim is None:
            return None
        result, metadata, error, delay = None, None, None, None
        if claim.pipeline_revision != pipeline_revision(self.ai):
            error = 'pipeline_mismatch'
        else:
            loaded = await asyncio.to_thread(self.jobs.evidence, claim, self.ai.max_sources, self.ai.max_input_bytes)
            if 'error' in loaded:
                if loaded['error'] == 'lease_lost':
                    return 'lease_lost'
                error = loaded['error']
            else:
                try:
                    evidence = tuple(Evidence.model_validate(e) for e in loaded['evidence'])
                except (ValueError, TypeError, KeyError):
                    error = 'invalid_request'
                else:
                    # Both DB capabilities have COMMITTED and CLOSED before this await.
                    # A bounded analyzer lets graceful shutdown finish the current job.
                    try:
                        async with asyncio.timeout(self.ai.deadline_seconds):
                            response = await self.analyzer.analyze(evidence)
                        analysis = TextAnalysis.model_validate(response.analysis.model_dump())
                        validate_evidence(analysis, evidence)
                        metadata = safe_metadata(response.metadata)
                        if (metadata['validation_outcome'] != 'valid'
                            or metadata['configured_model'] != self.ai.model
                            or metadata['returned_model'] not in (None, self.ai.model)
                            or metadata['prompt_version'] != PROMPT_VERSION
                            or metadata['schema_version'] != SCHEMA_VERSION):
                            raise ValueError('Invalid analysis metadata')
                        result = analysis.model_dump()
                    except AnalysisError as failure:
                        error = failure.code
                        metadata = safe_metadata(failure.metadata)
                        delay = retry_delay(failure, claim.attempts, self.settings)
                    except TimeoutError:
                        error = 'timeout'
                        delay = retry_delay(AnalysisError('timeout', retryable=True), claim.attempts, self.settings)
                    except (ValueError, TypeError, AttributeError, KeyError):
                        error, metadata = 'invalid_output', None
                    except Exception:
                        # Do not persist/log exception text, evidence or SDK request bodies.
                        error, metadata = 'internal_error', None
        return await asyncio.to_thread(self.jobs.finish, claim, result=result, metadata=metadata,
                                       error=error, retry_seconds=delay)
