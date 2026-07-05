"""Tests for post-compact reinject deduplication."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from backend.context.context_pipeline.post_compact_reinject import (
    build_post_compact_attachment_text,
)


def test_post_compact_restore_only_reinjects_recent_files():
    state = MagicMock()
    with patch(
        'backend.context.context_pipeline.post_compact_reinject._recent_files_block',
        return_value='Recently touched files:\n- src/main.py',
    ):
        body = build_post_compact_attachment_text(state, [])
    assert 'Goal context:' not in body
    assert 'Active scope' not in body
    assert 'src/main.py' in body


def test_post_compact_restore_empty_when_no_files():
    state = MagicMock()
    with patch(
        'backend.context.context_pipeline.post_compact_reinject._recent_files_block',
        return_value='',
    ):
        body = build_post_compact_attachment_text(state, [])
    assert body == ''
