"""Versioned extraction instructions and the provider's strict JSON schema."""

import json
from collections.abc import Sequence

from app.ai_engine.analysis import Evidence, TextAnalysis
from app.ai_engine.prompts import load_metadata, load_prompt

_meta = load_metadata("text_analysis")
PROMPT_VERSION: str = _meta.get("version", "text-analysis-v1")
SCHEMA_VERSION: str = _meta.get("schema", "text-analysis-v1")
SYSTEM_PROMPT: str = load_prompt("text_analysis")


def build_request(evidence: Sequence[Evidence]) -> dict:
    return {
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': json.dumps(
                {'evidence': [source.model_dump() for source in evidence]},
                ensure_ascii=False, separators=(',', ':'),
            )},
        ],
        'response_format': {
            'type': 'json_schema',
            'json_schema': {
                'name': 'text_analysis', 'strict': True,
                'schema': TextAnalysis.model_json_schema(),
            },
        },
    }


def request_size_bytes(body: dict) -> int:
    """Safety bound for serialized input, including instructions/schema; not tokens."""
    return len(json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))


def build_bounded_request(evidence: Sequence[Evidence], settings) -> dict:
    """One request budget shared by public selection and the provider boundary."""
    if not 1 <= len(evidence) <= settings.max_sources:
        raise ValueError('Invalid evidence count')
    if any(not isinstance(source, Evidence) for source in evidence):
        raise ValueError('Typed evidence is required')
    if len({source.source_id for source in evidence}) != len(evidence):
        raise ValueError('Duplicate evidence source IDs')
    if sum(len(source.content.encode('utf-8')) for source in evidence) > settings.max_input_bytes:
        raise ValueError('AI input size limit exceeded')
    request = build_request(evidence)
    request.update(model=settings.model, reasoning_effort=settings.reasoning_effort,
                   max_completion_tokens=settings.max_completion_tokens,
                   include_reasoning=False, stream=False)
    if request_size_bytes(request) > settings.max_input_bytes:
        raise ValueError('AI input size limit exceeded')
    return request
