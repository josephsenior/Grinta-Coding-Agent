"""Unit tests for :mod:`backend.cli.transcript`."""

from __future__ import annotations

import io

import pytest
from rich.console import Console
from rich.text import Text

from backend.cli.layout_tokens import CALLOUT_PANEL_PADDING
from backend.cli.transcript import (
    format_activity_block,
    format_activity_delta_secondary,
    format_activity_primary,
    format_activity_secondary,
    format_activity_shell_block,
    format_activity_turn_header,
    format_callout_panel,
    format_ground_truth_tool_line,
    format_reasoning_snapshot,
    format_shell_result_secondary,
    strip_tool_result_validation_annotations,
)


def test_format_ground_truth_tool_line_uses_ascii_prefix() -> None:
    line = format_ground_truth_tool_line('read: foo.py')
    assert isinstance(line, Text)
    assert line.plain.startswith('    > ')
    assert 'read: foo.py' in line.plain


def test_format_ground_truth_tool_line_strips_label() -> None:
    line = format_ground_truth_tool_line('  read: x  ')
    assert line.plain == '    > read: x'


@pytest.mark.parametrize(
    'label',
    [
        'read: foo.py',
        'Recalling: ctx',
        'code nav: refs: bar.py',
    ],
)
def test_format_ground_truth_tool_line_various_labels(label: str) -> None:
    line = format_ground_truth_tool_line(label)
    assert label in line.plain


def test_format_ground_truth_tool_line_each_call_independent() -> None:
    """No session state: identical labels produce identical rows every time."""
    a = format_ground_truth_tool_line('read: x.py')
    b = format_ground_truth_tool_line('read: x.py')
    assert a.plain == b.plain


def test_format_activity_primary_verb_and_detail() -> None:
    line = format_activity_primary('Ran', '$ ls -la')
    assert 'Ran' in line.plain
    assert '$ ls -la' in line.plain


def test_format_activity_secondary_kinds() -> None:
    ok = format_activity_secondary('done', kind='ok')
    err = format_activity_secondary('exit 1', kind='err')
    assert 'done' in ok.plain
    assert 'exit 1' in err.plain


def test_format_activity_delta_secondary_shows_colored_add_remove_counts() -> None:
    line = format_activity_delta_secondary(added=3, removed=1)
    assert line is not None
    assert '+ 3 lines' in line.plain
    assert '- 1 lines' in line.plain


def test_strip_tool_result_validation_annotations() -> None:
    raw = 'hello\n\n<APP_RESULT_VALIDATION>\nwarnings: x\n</APP_RESULT_VALIDATION>\n'
    assert strip_tool_result_validation_annotations(raw) == 'hello'


def test_strip_tool_result_validation_unclosed_tag() -> None:
    """Streaming or malformed tool results may omit the closing tag."""
    raw = 'out\n<APP_RESULT_VALIDATION>warnings: nope\n'
    assert strip_tool_result_validation_annotations(raw) == 'out'


def test_format_activity_block_includes_secondary_when_set() -> None:
    g = format_activity_block(
        'Viewed', 'src/a.py', secondary='12 lines', secondary_kind='neutral'
    )
    plain = ''.join(getattr(seg, 'plain', str(seg)) for seg in g.renderables)
    assert 'Viewed' in plain
    assert 'src/a.py' in plain
    assert '12 lines' in plain


def test_format_activity_turn_header_plain() -> None:
    import io

    from rich.console import Console
    from rich.rule import Rule

    r = format_activity_turn_header()
    assert isinstance(r, Rule)
    buf = io.StringIO()
    Console(file=buf, width=80, force_terminal=False, color_system=None).print(r)
    assert 'Tools & commands' in buf.getvalue()


def test_format_callout_panel_uses_layout_padding() -> None:
    panel = format_callout_panel('Title', Text('body'))
    assert panel.padding == CALLOUT_PANEL_PADDING


def test_format_callout_panel_accepts_custom_padding() -> None:
    panel = format_callout_panel('Title', Text('body'), padding=(0, 1))
    assert panel.padding == (0, 1)


def test_format_activity_shell_block_uses_card_and_command() -> None:
    import io

    from rich.console import Console

    g = format_activity_shell_block(
        'Ran',
        '$ ls -la',
        result_message='done',
        result_kind='ok',
    )
    buf = io.StringIO()
    Console(
        file=buf, width=88, force_terminal=True, color_system=None, legacy_windows=False
    ).print(g)
    out = buf.getvalue()
    assert 'Ran' in out
    assert '$ ls -la' in out
    assert 'Terminal' in out
    assert '+--' not in out and '--+' not in out
    assert 'done' in out
    assert '✓' in out


def test_format_shell_result_secondary_uses_bright_icon_and_message() -> None:
    line = format_shell_result_secondary('exit 127 · missing tool', kind='err')
    assert '✗' in line.plain
    assert 'exit 127' in line.plain


def test_format_reasoning_snapshot_empty() -> None:
    g = format_reasoning_snapshot([])
    assert len(g.renderables) == 0


def test_format_reasoning_snapshot_lines() -> None:
    g = format_reasoning_snapshot(['  first line  ', '', 'second'])
    buf = io.StringIO()
    Console(
        file=buf, width=88, force_terminal=True, color_system=None, legacy_windows=False
    ).print(g)
    out = buf.getvalue()
    assert 'first line' in out
    assert 'second' in out
