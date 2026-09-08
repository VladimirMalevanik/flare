"""Safe failures for future callers; no provider bodies or exception objects."""

from typing import Literal

from app.ai_engine.analysis import AnalysisMetadata

ErrorCode = Literal[
    'configuration', 'provider_auth', 'invalid_request', 'rate_limited',
    'timeout', 'network', 'provider_server', 'provider_transient',
    'provider_failure', 'invalid_output',
]


class AnalysisError(Exception):
    def __init__(self, code: ErrorCode, *, retryable: bool = False,
                 metadata: AnalysisMetadata | None = None, retry_after_seconds: float | None = None):
        super().__init__(f'Text analysis failed: {code}')
        self.code = code
        self.retryable = retryable
        self.metadata = metadata
        self.retry_after_seconds = retry_after_seconds
