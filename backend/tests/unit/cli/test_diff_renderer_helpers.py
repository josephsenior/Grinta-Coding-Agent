"""Unit tests for diff_renderer helper functions."""

from __future__ import annotations

from types import SimpleNamespace

from rich.text import Text

from backend.cli.display.diff_renderer import (
    DiffPanel,
    _append_group_lines,
    _build_diff_header,
    _count_diff_totals,
    _extract_indentation_warnings,
    _extract_tagged_block,
    _is_validation_secondary,
    _preview_syntax_block,
    _preview_text_lines,
    _style_diff_line,
)


def test_preview_text_lines_truncates_long_content() -> None:
    lines = _preview_text_lines('a\n' * 20, max_lines=3, max_chars=5)
    assert len(lines) == 4
    assert 'more lines' in lines[-1].plain


def test_preview_syntax_block_detects_json_and_python() -> None:
    assert _preview_syntax_block('data.json', '{"a": 1}') is not None
    assert _preview_syntax_block('script.py', 'print(1)\n') is not None
    assert _preview_syntax_block('unknown', 'plain text only') is None


def test_is_validation_secondary_matches_lint_markers() -> None:
    assert _is_validation_secondary('Ruff: unused import') is True
    assert _is_validation_secondary('Saved file successfully') is False


def test_extract_indentation_warnings_parses_blocks() -> None:
    content = (
        'main edit\n\n[INDENTATION WARNINGS]\n'
        '[INDENTATION MISMATCH] line 1\nexpected 4 spaces\n'
    )
    main, warnings = _extract_indentation_warnings(content)
    assert 'main edit' in main
    assert warnings is not None
    assert 'INDENTATION MISMATCH' in warnings[0]


def test_extract_tagged_block() -> None:
    content = 'before <TAG>payload</TAG> after'
    assert _extract_tagged_block(content, '<TAG>', '</TAG>') == 'payload'
    assert _extract_tagged_block(content, '<MISSING>', '</MISSING>') is None


def test_count_diff_totals_and_styling() -> None:
    groups = [
        {
            'before_edits': ['-old'],
            'after_edits': ['+new', '+more'],
        }
    ]
    added, removed = _count_diff_totals(groups)
    assert added == 2
    assert removed == 1
    header = _build_diff_header('src/main.py', added, removed)
    assert 'src/main.py' in header.plain
    assert '+2' in header.plain
    assert isinstance(_style_diff_line('+added'), Text)
    assert isinstance(_style_diff_line('-removed'), Text)


def test_append_group_lines() -> None:
    lines: list[Text] = []
    _append_group_lines(
        lines,
        {'before_edits': ['-x'], 'after_edits': ['+y']},
    )
    assert len(lines) == 2


def test_diff_panel_validation_secondary_uses_callout() -> None:
    obs = SimpleNamespace(
        path='main.py',
        tool_result={'operation': 'replace_string', 'ok': True},
        outcome='edited',
        old_content='before',
        get_edit_groups=lambda **kwargs: [],
        content='',
        diff=None,
        visualize_diff=lambda **kwargs: '',
    )
    panel = DiffPanel(
        obs,
        secondary='Syntax error at line 3',
    )
    parts: list[object] = []
    panel._append_secondary(parts)
    assert parts


def test_diff_panel_hides_diff_when_env_disabled(monkeypatch) -> None:
    monkeypatch.setenv('GRINTA_SHOW_DIFF', '0')
    obs = SimpleNamespace(
        path='main.py',
        tool_result={'operation': 'replace_string', 'ok': True},
        outcome='edited',
        old_content='before',
        get_edit_groups=lambda **kwargs: [],
        content='',
        diff=None,
        visualize_diff=lambda **kwargs: '',
    )
    parts: list[object] = []
    DiffPanel(obs)._render_existing_file_parts(parts, obs)
    assert parts


def test_diff_panel_appends_indentation_warnings() -> None:
    obs = SimpleNamespace(
        path='main.py',
        content=(
            'edit ok\n\n[INDENTATION WARNINGS]\n'
            '[INDENTATION MISMATCH] line 2\nexpected 4 spaces\n'
            '[SUGGESTED FIX] reindent block\n'
        ),
    )
    parts: list[object] = []
    DiffPanel(obs)._append_indentation_warnings(parts, obs)
    assert parts
