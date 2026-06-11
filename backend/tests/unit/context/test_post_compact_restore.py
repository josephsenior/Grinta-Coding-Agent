"""Tests for bounded post-compaction restore injection."""

from __future__ import annotations

from backend.context.post_compact_restore import inject_post_compact_restore
from backend.ledger.action.message import MessageAction
from backend.ledger.observation.agent import AgentCondensationObservation


def test_post_compact_restore_is_bounded_and_deduped(tmp_path, monkeypatch) -> None:
    edited = tmp_path / 'edited.py'
    edited.write_text('x = 1\n' * 500, encoding='utf-8')
    read_only = tmp_path / 'read_only.py'
    read_only.write_text('y = 2\n' * 500, encoding='utf-8')
    snapshot = {
        'latest_directive': 'finish the compaction fix',
        'files_touched': {
            str(read_only): {'action': 'read', 'type': 'read'},
            str(edited): {'action': 'edit', 'type': 'edit'},
        },
        'background_tasks': [
            {
                'session_id': 'terminal_3',
                'next_action': 'terminal_read(session_id="terminal_3")',
            }
        ],
    }
    monkeypatch.setattr(
        'backend.context.post_compact_restore.load_snapshot',
        lambda state=None: snapshot,
    )

    event = MessageAction(content='continue')
    restored = inject_post_compact_restore(
        [event],
        [event],
        just_compacted=True,
        state=None,
    )

    assert isinstance(restored[0], AgentCondensationObservation)
    assert '<POST_COMPACT_RESTORE>' in restored[0].content
    assert str(edited) in restored[0].content
    assert 'terminal_read(session_id="terminal_3")' in restored[0].content
    assert len(restored[0].content) < 6_000

    second = inject_post_compact_restore(
        restored,
        [event],
        just_compacted=True,
        state=None,
    )

    assert second == restored
