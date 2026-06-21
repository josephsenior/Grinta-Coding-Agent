"""Unit tests for detail screen helpers and chrome."""

from __future__ import annotations

from backend.cli.tui.screens.detail.base import DetailScreen
from backend.cli.tui.screens.detail.helpers import (
    detail_accent_for_state,
    format_exit_chip,
    format_numbered_block,
    format_shell_command,
    split_detail_title,
)
from backend.cli.tui.screens.detail.shell import ShellDetailScreen


def test_split_detail_title():
    assert split_detail_title('Shell  npm install') == ('Shell', 'npm install')
    assert split_detail_title('npm install') == ('', 'npm install')


def test_detail_accent_for_state():
    assert detail_accent_for_state('done') == '#639922'
    assert detail_accent_for_state('failed') == '#E24B4A'
    assert detail_accent_for_state('running') == '#EF9F27'


def test_format_exit_chip():
    assert '✓' in (format_exit_chip(0) or '')
    assert '✗ exit 1' in (format_exit_chip(1) or '')
    assert format_exit_chip(None) is None


def test_format_numbered_block_includes_gutter():
    text = format_numbered_block('line one\nline two')
    assert '│' in text
    assert 'line one' in text


def test_format_shell_command():
    assert '$' in format_shell_command('cargo test')
    assert 'cargo test' in format_shell_command('cargo test')


def test_traffic_lights_markup():
    from backend.cli.tui.screens.detail.helpers import traffic_lights_markup

    markup = traffic_lights_markup('pytest -q')
    assert '●' in markup
    assert 'pytest -q' in markup


def test_render_command_syntax_is_rich_syntax():
    from rich.syntax import Syntax

    from backend.cli.tui.screens.detail.helpers import render_command_syntax

    block = render_command_syntax('cargo test')
    assert isinstance(block, Syntax)
    assert 'cargo test' in block.code


def test_shell_detail_screen_uses_terminal_frame():
    screen = ShellDetailScreen(
        command='pytest -q',
        output='2 passed',
        exit_code=0,
        cwd='/project',
        kind='Shell',
        heading='pytest -q',
        accent='#639922',
    )
    widgets = screen.build_content()
    from backend.cli.tui.widgets.detail_terminal_frame import DetailTerminalFrame

    frames = [w for w in widgets if isinstance(w, DetailTerminalFrame)]
    assert len(frames) == 1
    assert len(frames[0]._children_widgets) == 2


def test_detail_screen_escape_binding():
    assert any(
        binding[0] == 'escape'
        for binding in DetailScreen.BINDINGS
    )


def test_edit_detail_screen_fills_body_without_terminal_frame():
    from backend.cli.tui.screens.detail.edit import EditDetailScreen
    from backend.cli.tui.widgets.detail_terminal_frame import DetailTerminalFrame
    from backend.cli.tui.widgets.unified_diff_view import (
        UnifiedDiffView,
        encode_diff_view_payload,
    )

    encoded = encode_diff_view_payload(
        path='backend/raft/__init__.py',
        old_content='',
        new_content='"""Raft cluster API."""\n',
    )
    assert encoded is not None
    screen = EditDetailScreen(
        title='Created  backend/raft/__init__.py',
        encoded_diff=encoded,
        kind='Created',
        heading='raft/__init__.py',
    )
    assert screen._wrap_content_in_panel is False
    assert screen._use_scroll_body is False
    widgets = screen.build_content()
    assert not any(isinstance(w, DetailTerminalFrame) for w in widgets)
    views = [w for w in widgets if isinstance(w, UnifiedDiffView)]
    assert len(views) == 1
    assert views[0].has_class('-detail')
