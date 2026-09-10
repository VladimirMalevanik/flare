"""Deterministic bounded selection; no embeddings, inferred state or provider call."""
import re
from app.ai_engine.analysis import Evidence
from app.ai_engine.prompts import build_bounded_request

SELECTION_REVISION = 'recent-project-v1'
SIGNALS = re.compile(r'\b(goal|deadline|decision|decided|blocked|constraint|launch|release|mvp|цель|решение|дедлайн|релиз)\b', re.IGNORECASE)


def select_context(candidates, ai):
    # Input is stable recency order. Reserve the newest fitting chunk; remaining
    # candidates rank by distinct explicit project words, then original recency.
    ranked = sorted(enumerate(candidates), key=lambda pair: (-len(set(SIGNALS.findall(pair[1]['content'].lower()))), pair[0]))
    selected = []
    order = list(enumerate(candidates))
    for index, candidate in order:
        evidence = Evidence(source_id=str(candidate['id']), content=candidate['content'])
        try:
            build_bounded_request([evidence], ai)
        except ValueError:
            continue
        selected = [evidence]
        break
    if not selected:
        return ()
    for _, candidate in ranked:
        if len(selected) >= min(ai.max_sources, 100):
            break
        evidence = Evidence(source_id=str(candidate['id']), content=candidate['content'])
        if evidence.source_id == selected[0].source_id:
            continue
        try:
            build_bounded_request([*selected, evidence], ai)
        except ValueError:
            continue
        selected.append(evidence)
    return tuple(selected)
