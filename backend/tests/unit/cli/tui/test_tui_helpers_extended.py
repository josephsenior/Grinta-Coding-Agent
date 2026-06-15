"""Unit tests for TUI helper utilities."""

from __future__ import annotations

from backend.cli.tui.helpers import (
    _count_text_lines,
    _count_unified_diff_changes,
    _encode_unified_diff_text,
    _extract_tagged_block,
    _format_diff_summary,
    _join_secondary_parts,
    _sanitize_terminal_display_text,
    _should_collapse_file_diff,
    _split_combined_diff,
    _strip_ansi,
    _strip_terminal_control_literals,
    infer_display_shell_kind,
)


def test_infer_display_shell_kind() -> None:
    assert infer_display_shell_kind('Get-ChildItem') == 'pwsh'
    assert infer_display_shell_kind('npm run build') in {'bash', 'pwsh'}


def test_strip_ansi_and_control_literals() -> None:
    assert _strip_ansi('ok \x1b[32mgreen\x1b[0m') == 'ok green'
    mouse = '\x1b[<0;1;1M'
    assert mouse not in _strip_terminal_control_literals(f'hello{mouse}world')


def test_sanitize_terminal_display_text() -> None:
    cleaned = _sanitize_terminal_display_text('  line\x1b[0m\n')
    assert '\x1b' not in cleaned


def test_count_text_lines_and_diff_summary() -> None:
    assert _count_text_lines('a\nb') == 2
    assert _count_text_lines('a\nb\n') == 3
    assert _format_diff_summary(3, 1) == '+3 -1'
    assert _format_diff_summary(0, 0) is None


def test_count_unified_diff_changes() -> None:
    diff = '@@ -1 +1 @@\n-old\n+new\n context'
    added, removed = _count_unified_diff_changes(diff)
    assert added >= 1
    assert removed >= 1


def test_encode_unified_diff_text() -> None:
    encoded = _encode_unified_diff_text('@@\n-old\n+new')
    assert isinstance(encoded, str)
    assert 'grinta-diff-view' in encoded


def test_split_combined_diff() -> None:
    combined = '--- a/file.py\n+++ b/file.py\n@@\n-old\n+new'
    parts = _split_combined_diff(combined)
    assert parts


def test_extract_tagged_block() -> None:
    content = 'before <TAG>inside</TAG> after'
    assert _extract_tagged_block(content, '<TAG>', '</TAG>') == 'inside'
    assert _extract_tagged_block(content, '<MISSING>', '</MISSING>') is None


def test_should_collapse_file_diff() -> None:
    huge = '\n'.join(['+line'] * 200)
    assert _should_collapse_file_diff(huge) is True
    assert _should_collapse_file_diff('+one') is False


def test_join_secondary_parts() -> None:
    assert _join_secondary_parts('a', None, 'b') == 'a · b'
    assert _join_secondary_parts(None, None) is None
