"""Deterministic bounded selection; no embeddings, inferred state or provider call."""
import re
from app.ai_engine.analysis import Evidence
from app.ai_engine.text_analysis_prompts import build_bounded_request

SELECTION_REVISION = 'rotating-project-v2'
SIGNALS = re.compile(r'\b(goal|deadline|decision|decided|blocked|constraint|launch|release|mvp|цель|решение|дедлайн|релиз)\b', re.IGNORECASE)


def select_context(candidates, ai, *, preserve_order=False):
    if preserve_order:
        # The database orders never-selected sections first. Reserve one slot
        # for an actionable section from that same unseen tier, when possible;
        # otherwise routine newer files can crowd out an older goal/deadline.
        # Keep the first rotated section so every run still advances coverage.
        ordered = list(candidates)
        if len(ordered) > 1 and ai.max_sources > 1 and 'unseen' in ordered[0]:
            first = ordered[0]
            if not SIGNALS.search(first['content']):
                unseen = [candidate for candidate in ordered[1:]
                          if candidate.get('unseen')]
                pool = unseen if unseen else ordered[1:]
                strongest = max(pool, key=lambda candidate:
                                len(set(SIGNALS.findall(candidate['content'].lower()))),
                                default=None)
                if strongest is not None and SIGNALS.search(strongest['content']):
                    ordered = [first, strongest] + [candidate for candidate in ordered[1:]
                                                    if str(candidate['id']) != str(strongest['id'])]
    else:
        # Keep the original ordering for direct callers supplying recency-only
        # candidates; public runs use the database's rotation order instead.
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
