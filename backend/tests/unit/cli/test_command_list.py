"""Unit tests for shared command list widgets."""

from __future__ import annotations

from backend.cli.tui.widgets.command_list import (
    build_slash_command_rows,
    slash_command_runs_immediately,
)


def test_build_slash_command_rows_merges_description_and_syntax():
    rows = build_slash_command_rows(
        {
            '/clear': '/clear',
            '/help': '/help [--all|--search <term>|<command>]',
            '/sessions': '/sessions [list] [--limit N]',
        }
    )
    by_name = dict(rows)
    assert by_name['/clear'] == 'Clear the transcript'
    assert by_name['/help'] == '[--all|--search <term>|<command>]'
    assert by_name['/sessions'] == '[list] [--limit N]'


def test_slash_command_runs_immediately():
    assert slash_command_runs_immediately('/settings') is True
    assert slash_command_runs_immediately('/resume') is False
