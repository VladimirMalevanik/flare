"""Rotating selection preserves coverage without losing actionable context."""

from dataclasses import replace
from uuid import uuid4

from app.config import AISettings
from app.services.context_selection import select_context


def test_rotating_order_does_not_reselect_a_used_high_signal_chunk():
    newest, unseen, used = (uuid4() for _ in range(3))
    candidates = [
        {'id': newest, 'content': 'Routine status update.', 'unseen': True},
        {'id': unseen, 'content': 'Another routine status update.', 'unseen': True},
        {'id': used, 'content': 'Our goal is the release deadline.', 'unseen': False},
    ]
    ai = replace(AISettings(), max_sources=2)

    manual = select_context(candidates, ai, preserve_order=True)
    scheduled = select_context(candidates, ai)

    assert [item.source_id for item in manual] == [str(newest), str(unseen)]
    assert [item.source_id for item in scheduled] == [str(newest), str(used)]


def test_rotating_selection_includes_older_unseen_actionable_note():
    routine = [uuid4() for _ in range(6)]
    goal = uuid4()
    candidates = [
        {'id': item, 'content': 'Routine status update.', 'unseen': True}
        for item in routine
    ] + [{'id': goal, 'content': 'Our goal is the release deadline.', 'unseen': True}]
    ai = replace(AISettings(), max_sources=5)

    selected = select_context(candidates, ai, preserve_order=True)

    assert [item.source_id for item in selected] == [
        str(routine[0]), str(goal), *[str(item) for item in routine[1:4]]
    ]
