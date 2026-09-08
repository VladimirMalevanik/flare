"""Small provider-independent contracts; evidence authorization belongs to callers."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

Category = Literal['fact', 'decision', 'intention', 'problem', 'entity']


class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)


class Evidence(StrictModel):
    source_id: str
    content: str

    @field_validator('source_id')
    @classmethod
    def valid_id(cls, value: str) -> str:
        if not value.strip() or value != value.strip() or len(value) > 128:
            raise ValueError('Invalid source ID')
        return value

    @field_validator('content')
    @classmethod
    def nonblank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError('Evidence must contain text')
        return value


class EvidenceReference(StrictModel):
    source_id: str
    quote: str

    @field_validator('source_id', 'quote')
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip() or len(value) > 1000:
            raise ValueError('Invalid evidence reference')
        return value


class Observation(StrictModel):
    category: Category
    text: str
    evidence: list[EvidenceReference]

    @field_validator('text')
    @classmethod
    def valid_text(cls, value: str) -> str:
        if not value.strip() or len(value) > 500:
            raise ValueError('Observation text must contain 1–500 characters')
        return value

    @field_validator('evidence')
    @classmethod
    def required_evidence(cls, value: list[EvidenceReference]) -> list[EvidenceReference]:
        if not 1 <= len(value) <= 5:
            raise ValueError('Observation requires 1–5 evidence references')
        return value


class TextAnalysis(StrictModel):
    observations: list[Observation]

    @field_validator('observations')
    @classmethod
    def bounded_observations(cls, value: list[Observation]) -> list[Observation]:
        if len(value) > 20:
            raise ValueError('At most 20 observations are allowed')
        return value


@dataclass(frozen=True)
class AnalysisMetadata:
    configured_model: str
    prompt_version: str
    schema_version: str
    returned_model: str | None = None
    request_id: str | None = None
    completion_id: str | None = None
    input_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    latency_ms: float = 0.0
    validation_outcome: Literal['not_run', 'invalid', 'valid'] = 'not_run'


@dataclass(frozen=True)
class AnalysisResult:
    analysis: TextAnalysis
    metadata: AnalysisMetadata


def validate_evidence(analysis: TextAnalysis, sources: tuple[Evidence, ...]) -> None:
    """Validate exact source IDs and quotes, normalizing whitespace only."""
    supplied = {source.source_id: ' '.join(source.content.split()) for source in sources}
    for observation in analysis.observations:
        for reference in observation.evidence:
            content = supplied.get(reference.source_id)
            quote = ' '.join(reference.quote.split())
            if content is None or not quote or quote not in content:
                raise ValueError('Analysis references evidence not supplied')
