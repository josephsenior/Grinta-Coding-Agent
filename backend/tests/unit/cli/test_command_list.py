"""Unit tests for shared command list widgets."""

from __future__ import annotations

from backend.cli.tui.widgets.command_list import (
    build_slash_command_rows,
)


def test_build_slash_command_rows_merges_description_and_syntax():
    rows = build_slash_command_rows(
        {
            '/clear': '/clear',
            '/help': '/help [--all|--search <term>|<command>]',
        }
    )
    by_name = dict(rows)
    assert 'Clear the transcript' in by_name['/clear']
    assert '/help [--all' in by_name['/help']
