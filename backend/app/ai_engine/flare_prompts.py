"""Versioned reasoning over only the completed job's pinned context."""

import json

from app.ai_engine.flares import FlareCandidates
from app.ai_engine.prompts import load_metadata, load_prompt

_meta = load_metadata("flare_generation")
PROMPT_VERSION: str = _meta.get("version", "flare-v3")
SCHEMA_VERSION: str = _meta.get("schema", "flare-v1")
SYSTEM_PROMPT: str = load_prompt("flare_generation")


def build_flare_request(analysis, evidence):
    return {
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user', 'content': json.dumps(
                {
                    'analysis': analysis.model_dump(),
                    'evidence': [e.model_dump() for e in evidence],
                },
                ensure_ascii=False,
            )},
        ],
        'response_format': {'type': 'json_schema', 'json_schema': {
            'name': 'flare_candidates', 'strict': True,
            'schema': FlareCandidates.model_json_schema(),
        }},
    }
