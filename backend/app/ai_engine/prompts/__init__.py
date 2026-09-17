"""Versioned prompt loader with the original text-analysis API preserved."""

from app.ai_engine.prompts.loader import load_metadata, load_prompt


def build_request(*args, **kwargs):
    from app.ai_engine.text_analysis_prompts import build_request as implementation
    return implementation(*args, **kwargs)


def build_bounded_request(*args, **kwargs):
    from app.ai_engine.text_analysis_prompts import build_bounded_request as implementation
    return implementation(*args, **kwargs)


def request_size_bytes(*args, **kwargs):
    from app.ai_engine.text_analysis_prompts import request_size_bytes as implementation
    return implementation(*args, **kwargs)


def __getattr__(name: str):
    if name in {"PROMPT_VERSION", "SCHEMA_VERSION", "SYSTEM_PROMPT"}:
        from app.ai_engine import text_analysis_prompts
        return getattr(text_analysis_prompts, name)
    raise AttributeError(name)

__all__ = [
    "PROMPT_VERSION",
    "SCHEMA_VERSION",
    "SYSTEM_PROMPT",
    "build_bounded_request",
    "build_request",
    "load_metadata",
    "load_prompt",
    "request_size_bytes",
]
