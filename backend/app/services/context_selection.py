"""Deterministic bounded selection; no embeddings, inferred state or provider call."""
import re
from app.ai_engine.analysis import Evidence
from app.ai_engine.text_analysis_prompts import build_bounded_request

SELECTION_REVISION = 'rotating-project-v2'
SIGNALS = re.compile(r'\b(goal|deadline|decision|decided|blocked|constraint|launch|release|mvp|цель|решение|дедлайн|релиз)\b', re.IGNORECASE)


def select_context(candidates, ai, *, preserve_order=False):
    if preserve_order:
        # The manual query orders unseen documents and chunks first.
        ordered = candidates
    else:
        # Scheduled selection retains its original ordering until its existing
        # database candidate function can receive the same rotation query.
        ranked = sorted(enumerate(candidates), key=lambda pair: (
            -len(set(SIGNALS.findall(pair[1]['content'].lower()))), pair[0]))
        newest = None
        for candidate in candidates:
            evidence = Evidence(source_id=str(candidate['id']), content=candidate['content'])
            try:
                build_bounded_request([evidence], ai)
            except ValueError:
                continue
            newest = candidate
            break
        ordered = ([newest] if newest else []) + [
            candidate for _, candidate in ranked
            if newest is None or str(candidate['id']) != str(newest['id'])
        ]

    selected = []
    for candidate in ordered:
        if len(selected) >= min(ai.max_sources, 100):
            break
        evidence = Evidence(source_id=str(candidate['id']), content=candidate['content'])
        try:
            build_bounded_request([*selected, evidence], ai)
        except ValueError:
            continue
        selected.append(evidence)
    return tuple(selected)
