"""Versioned enrichment instructions and the provider's strict JSON schema."""

import json
from collections.abc import Sequence

from app.ai_engine.prompts import load_metadata, load_prompt

_meta = load_metadata("enrichment")
PROMPT_VERSION: str = _meta.get("version", "enrichment-v1")
SCHEMA_VERSION: str = _meta.get("schema", "enrichment-v1")
SYSTEM_PROMPT: str = load_prompt("enrichment")


def build_enrichment_request(content: str) -> dict:
    """
    Build a bounded enrichment request for a single item.

    The caller is responsible for passing already-authorized content:
    this function performs no authorization and no persistence.
    """
    if not isinstance(content, str) or not content.strip():
        raise ValueError("Enrichment content must be a non-empty string")

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(
                {"content": content},
                ensure_ascii=False,
                separators=(",", ":"),
            )},
        ],
        # Schema is attached at the adapter level once the Pydantic model
        # (Enrichment) is defined; keep this module free of provider details.
    }
