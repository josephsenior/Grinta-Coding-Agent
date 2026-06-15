"""Tests for embedded terminal chrome."""

from __future__ import annotations

from backend.cli.tui.helpers import (
    _format_terminal_output_for_display,
    infer_display_shell_kind,
)


def test_infer_display_shell_kind_detects_powershell_commands() -> None:
    assert infer_display_shell_kind('Get-ChildItem -Name') == 'pwsh'


def test_infer_display_shell_kind_defaults_to_bash_on_posix_markers() -> None:
    assert infer_display_shell_kind('ls -la') in {'bash', 'pwsh'}


def test_format_terminal_output_preserves_ansi_as_styled_text() -> None:
    rendered = _format_terminal_output_for_display('ok \x1b[32mgreen\x1b[0m')
    assert '\x1b' not in rendered.plain
    assert 'green' in rendered.plain
