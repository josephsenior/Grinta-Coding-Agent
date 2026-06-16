"""Unit tests for TerminalPane chrome helpers."""

from __future__ import annotations

from backend.cli.tui.constants import _TUI_TERMINAL_DISPLAY_LINE_CAP
from backend.cli.tui.widgets.terminal_pane import TerminalPane


def test_terminal_pane_prompt_and_title_markup() -> None:
    pane = TerminalPane(shell_kind='pwsh', command='Get-ChildItem', cwd='C:/repo')
    assert 'pwsh' in pane._title_markup() or 'PS' in pane._prompt_markup()
    assert 'Get-ChildItem' in pane._prompt_markup()

    bash = TerminalPane(shell_kind='bash', command='ls -la')
    assert '$' in bash._prompt_markup()

    terminal = TerminalPane(
        shell_kind='terminal', command='help', session_id='sess-12345'
    )
    assert 'terminal' in terminal._title_markup()
    assert 'sess-12345'[:12] in terminal._title_markup()

    debugger = TerminalPane(
        shell_kind='debugger', command='variables', session_id='dbg-session-1'
    )
    assert 'debugger' in debugger._title_markup()
    assert 'dbg-session-1'[:12] in debugger._title_markup()
    assert 'DAP>' in debugger._prompt_markup()
    assert 'variables' in debugger._prompt_markup()


def test_terminal_pane_footer_and_output_renderable() -> None:
    pane = TerminalPane(cwd='/work', running=True, footer='custom footer')
    assert 'custom footer' in pane._footer_markup()

    pane.set_output('line one\nline two')
    renderable = pane._output_renderable()
    assert renderable is not None

    pane.set_running(True)
    renderable_running = pane._output_renderable()
    assert renderable_running is not None


def test_terminal_pane_trims_long_output() -> None:
    pane = TerminalPane()
    long_output = '\n'.join(
        f'line {idx}' for idx in range(_TUI_TERMINAL_DISPLAY_LINE_CAP + 25)
    )
    pane.set_output(long_output)
    assert pane._hidden_lines == 25
    assert len(pane.output_text.splitlines()) == _TUI_TERMINAL_DISPLAY_LINE_CAP


def test_terminal_pane_append_output_skips_empty_chunks() -> None:
    pane = TerminalPane()
    pane.append_output('first')
    pane.append_output('\n')
    pane.append_output('second')
    assert 'first' in pane.output_text
    assert 'second' in pane.output_text
