"""Unit tests for event rendering text utilities."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.cli.event_rendering.text_utils import (
    contains_any,
    error_panel_outer_width,
    error_panel_text_wrap_width,
    normalize_reasoning_text,
    pty_output_transcript_caption,
    reasoning_lines_skip_already_committed,
    sanitize_streaming_thinking_text,
    sanitize_visible_transcript_text,
    show_reasoning_text,
    strip_pty_echo,
    summarize_cmd_failure,
    sync_reasoning_after_tool_line,
    truncate_activity_detail,
    wrap_panel_text_block,
)


def test_show_reasoning_text_env_toggle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv('APP_CLI_SHOW_REASONING_TEXT', raising=False)
    assert show_reasoning_text() is True
    monkeypatch.setenv('APP_CLI_SHOW_REASONING_TEXT', '0')
    assert show_reasoning_text() is False


def test_normalize_reasoning_text_strips_logged_placeholder() -> None:
    assert normalize_reasoning_text('Your thought has been logged.') == (None, None)


def test_normalize_reasoning_text_returns_plain_text() -> None:
    label, body = normalize_reasoning_text('plain reasoning text')
    assert label is None
    assert body == 'plain reasoning text'


def test_sanitize_visible_transcript_text() -> None:
    cleaned = sanitize_visible_transcript_text('  hello  ')
    assert cleaned == 'hello'


def test_wrap_panel_text_block_respects_width() -> None:
    wrapped = wrap_panel_text_block('word ' * 40, wrap_width=20)
    assert '\n' in wrapped


def test_pty_output_transcript_caption() -> None:
    caption = pty_output_transcript_caption(
        session_id='t1',
        n_lines=5,
        truncated=True,
        has_output=True,
    )
    assert 't1' in caption
    assert '5 lines' in caption
    assert 'truncated' in caption


def test_sync_reasoning_after_tool_line_updates_reasoning() -> None:
    reasoning = MagicMock()
    with patch('backend.cli.event_rendering.text_utils._prompt_role_debug'):
        sync_reasoning_after_tool_line(reasoning, 'grep', 'searching')
    reasoning.start.assert_called_once()
    reasoning.update_action.assert_called_once_with('grep')


def test_reasoning_lines_skip_already_committed() -> None:
    prev = ['a', 'b']
    new = ['a', 'b', 'c']
    assert reasoning_lines_skip_already_committed(prev, new) == ['c']
    assert reasoning_lines_skip_already_committed(None, new) == new


def test_contains_any() -> None:
    assert contains_any('hello world', ('foo', 'world')) is True
    assert contains_any('hello', ('foo', 'bar')) is False


def test_strip_pty_echo_removes_matching_line() -> None:
    text = 'prompt$ ls\nfile.txt\n'
    assert 'ls' not in strip_pty_echo(text, 'ls')


def test_truncate_activity_detail() -> None:
    assert truncate_activity_detail('one two three', 20) == 'one two three'
    long = 'x' * 50
    assert truncate_activity_detail(long, 10).endswith('…')


def test_summarize_cmd_failure_prefers_actionable_line() -> None:
    content = 'noise line\nError: module not found\n'
    assert 'module not found' in summarize_cmd_failure(content)


def test_error_panel_width_helpers() -> None:
    assert error_panel_text_wrap_width(None) is None
    assert error_panel_outer_width(120) is not None


def test_sanitize_streaming_thinking_text_delegates() -> None:
    assert sanitize_streaming_thinking_text('  hello  ') == 'hello'


def test_sanitize_visible_transcript_strips_internal_tags() -> None:
    raw = 'visible line\n<TASK_TRACKING>hidden</TASK_TRACKING>'
    cleaned = sanitize_visible_transcript_text(raw)
    assert 'visible line' in cleaned
    assert 'TASK_TRACKING' not in cleaned
