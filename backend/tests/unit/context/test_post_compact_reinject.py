"""Tests for unified compact snapshot injection."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.context.context_pipeline.post_compact_reinject import (
    build_post_compact_attachment_text,
)
from backend.context.prompt.compact_snapshot import build_compact_snapshot_body


def test_compact_snapshot_body_includes_snapshot_facts_not_tasks():
    state = MagicMock()
    snapshot = {
        'events_condensed': 3,
        'files_touched': {'src/main.py': {'action': 'edit'}},
        'recent_errors': [],
        'decisions': [],
        'recent_commands': [],
        'attempted_approaches': [],
        'background_tasks': [],
        'test_results': [],
    }
    with patch(
        'backend.context.compactor.pre_condensation_snapshot.load_snapshot',
        return_value=snapshot,
    ):
        with patch(
            'backend.context.compactor.pre_condensation_snapshot.format_snapshot_body_lines',
            return_value=[
                'Events condensed: 3',
                '\nFiles touched before condensation:',
                '  edit: src/main.py',
            ],
        ):
            body = build_compact_snapshot_body(state, [])
    assert 'Goal context:' not in body
    assert 'Active scope' not in body
    assert 'src/main.py' in body


def test_compact_snapshot_body_empty_when_no_snapshot():
    state = MagicMock()
    with patch(
        'backend.context.compactor.pre_condensation_snapshot.load_snapshot',
        return_value=None,
    ):
        body = build_compact_snapshot_body(state, [])
    assert body == ''


def test_legacy_attachment_wraps_compact_snapshot():
    state = MagicMock()
    with patch(
        'backend.context.context_pipeline.post_compact_reinject.build_compact_snapshot_body',
        return_value='Events condensed: 1',
    ):
        body = build_post_compact_attachment_text(state, [])
    assert body.startswith('<COMPACT_SNAPSHOT>')
    assert body.endswith('</COMPACT_SNAPSHOT>')
