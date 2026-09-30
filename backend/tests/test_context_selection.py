"""Manual rotation and scheduled legacy selection keep distinct ordering."""

from dataclasses import replace
from uuid import uuid4

from app.config import AISettings
from app.services.context_selection import select_context


def test_rotating_order_does_not_reselect_a_used_high_signal_chunk():
    newest, unseen, used = (uuid4() for _ in range(3))
    candidates = [
        {'id': newest, 'content': 'Routine status update.'},
        {'id': unseen, 'content': 'Another routine status update.'},
        {'id': used, 'content': 'Our goal is the release deadline.'},
    ]
    ai = replace(AISettings(), max_sources=2)

    manual = select_context(candidates, ai, preserve_order=True)
    scheduled = select_context(candidates, ai)

    assert [item.source_id for item in manual] == [str(newest), str(unseen)]
    assert [item.source_id for item in scheduled] == [str(newest), str(used)]
