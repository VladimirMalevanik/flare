"""Worker configuration, loaded only by the separate worker process."""
import math
import os
from dataclasses import dataclass, field
from hashlib import sha256
import json

from app.ai_engine.text_analysis_prompts import PROMPT_VERSION, SCHEMA_VERSION
from app.config import AISettings


@dataclass(frozen=True)
class WorkerSettings:
    database_url: str = field(default='', repr=False)
    max_attempts: int = 3
    lease_seconds: int = 120
    poll_seconds: float = 1.0
    backoff_seconds: float = 5.0
    max_backoff_seconds: float = 300.0

    def validate(self, ai: AISettings) -> None:
        ai.validate()
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 10:
            raise ValueError('Worker attempts must be between 1 and 10')
        if type(self.lease_seconds) is not int or not ai.deadline_seconds + 30 < self.lease_seconds <= 3600:
            raise ValueError('Worker lease must exceed provider deadline by more than 30 seconds')
        if any(not math.isfinite(v) or v <= 0 for v in
               (self.poll_seconds, self.backoff_seconds, self.max_backoff_seconds)):
            raise ValueError('Worker delays must be finite and positive')
        if self.backoff_seconds > self.max_backoff_seconds:
            raise ValueError('Worker backoff exceeds its cap')


def load_worker_settings() -> WorkerSettings:
    try:
        return WorkerSettings(
            database_url=os.getenv('WORKER_DATABASE_URL', ''),
            max_attempts=int(os.getenv('ANALYSIS_MAX_ATTEMPTS', '3')),
            lease_seconds=int(os.getenv('ANALYSIS_LEASE_SECONDS', '120')),
            poll_seconds=float(os.getenv('ANALYSIS_POLL_SECONDS', '1')),
            backoff_seconds=float(os.getenv('ANALYSIS_BACKOFF_SECONDS', '5')),
            max_backoff_seconds=float(os.getenv('ANALYSIS_MAX_BACKOFF_SECONDS', '300')),
        )
    except ValueError:
        raise ValueError('Invalid worker configuration') from None


def pipeline_revision(ai: AISettings) -> str:
    """Stable logical work identity; secrets never enter fingerprints or storage."""
    ai.validate()
    config = dict(prompt=PROMPT_VERSION, schema=SCHEMA_VERSION, model=ai.model,
                  reasoning_effort=ai.reasoning_effort, output_tokens=ai.max_completion_tokens,
                  max_sources=ai.max_sources, max_input_bytes=ai.max_input_bytes)
    return 'analysis-v1:' + sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
