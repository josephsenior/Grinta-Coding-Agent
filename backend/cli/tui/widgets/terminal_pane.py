"""Embedded terminal chrome for shell and PTY activity cards."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Static

from backend.cli.theme.cards import (
    TERM_COMMAND_FG,
    TERM_DEBUGGER_PROMPT,
    TERM_FOOTER_NEUTRAL,
    TERM_HIDDEN_LINES_FG,
    TERM_PTY_PROMPT,
    TERM_PWSH_PROMPT,
    TERM_RUNNING_CURSOR,
    TERM_SHELL_PROMPT,
    TERM_TITLEBAR_FG,
    footer_color_for_exit_code,
)
from backend.cli.tui.constants import _TUI_TERMINAL_DISPLAY_LINE_CAP
from backend.cli.tui.helpers import _format_terminal_output_for_display


class TerminalPane(Vertical):
    """Prompt + scrollback + footer layout mimicking a terminal window."""

    DEFAULT_CSS = """
    TerminalPane {
        width: 100%;
        height: auto;
        border: none;
        padding: 0;
        margin: 0;
    }
    TerminalPane .terminal-titlebar {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    TerminalPane .terminal-prompt {
        width: 100%;
        height: auto;
        min-height: 1;
        padding: 0 1;
    }
    TerminalPane .terminal-output-wrap {
        width: 100%;
        height: auto;
        overflow-y: auto;
        padding: 0 1;
        scrollbar-size-vertical: 1;
    }
    TerminalPane .terminal-output {
        width: 100%;
        height: auto;
    }
    TerminalPane .terminal-footer {
        width: 100%;
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        *,
        shell_kind: str = 'bash',
        command: str = '',
        cwd: str | None = None,
        session_id: str = '',
        footer: str = '',
        exit_code: int | None = None,
        running: bool = False,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._shell_kind = shell_kind
        self._command = command
        self._cwd = cwd
        self._session_id = session_id
        self._footer = footer
        self._exit_code = exit_code
        self._running = running
        self._output_text = ''
        self._hidden_lines = 0

    @property
    def output_text(self) -> str:
        return self._output_text

    def set_shell_kind(self, shell_kind: str) -> None:
        self._shell_kind = shell_kind
        self._refresh_chrome()

    def set_command(self, command: str) -> None:
        self._command = (command or '').strip()
        self._refresh_prompt()

    def set_cwd(self, cwd: str | None) -> None:
        self._cwd = (cwd or '').strip() or None
        self._refresh_prompt()
        self._refresh_footer()

    def set_session_id(self, session_id: str) -> None:
        self._session_id = (session_id or '').strip()
        self._refresh_title()

    def set_footer(self, footer: str) -> None:
        self._footer = footer
        self._refresh_footer()

    def set_exit_code(self, exit_code: int | None) -> None:
        self._exit_code = exit_code
        self._refresh_footer()

    def set_running(self, running: bool) -> None:
        self._running = running
        self._refresh_output()
        self._refresh_footer()

    def set_output(self, content: str) -> None:
        self._output_text = content or ''
        self._hidden_lines = 0
        self._trim_output()
        self._refresh_output()

    def append_output(self, text: str) -> None:
        chunk = (text or '').strip('\n')
        if not chunk:
            return
        if self._output_text:
            self._output_text += '\n' + chunk
        else:
            self._output_text = chunk
        self._trim_output()
        self._refresh_output()

    def _trim_output(self) -> None:
        lines = self._output_text.splitlines()
        if len(lines) <= _TUI_TERMINAL_DISPLAY_LINE_CAP:
            return
        hidden = len(lines) - _TUI_TERMINAL_DISPLAY_LINE_CAP
        self._hidden_lines += hidden
        self._output_text = '\n'.join(lines[-_TUI_TERMINAL_DISPLAY_LINE_CAP:])

    def _title_markup(self) -> str:
        if self._shell_kind == 'debugger':
            label = self._session_id[:12] if self._session_id else 'session'
            return f'[{TERM_TITLEBAR_FG}]debugger · {label} │[/]'
        if self._shell_kind == 'terminal':
            label = self._session_id[:12] if self._session_id else 'session'
            return f'[{TERM_TITLEBAR_FG}]terminal · {label} │[/]'
        label = 'pwsh' if self._shell_kind == 'pwsh' else 'bash'
        return f'[{TERM_TITLEBAR_FG}]{label} │[/]'

    def _prompt_markup(self) -> str:
        command = self._command or '…'
        if self._shell_kind == 'debugger':
            return f'[{TERM_DEBUGGER_PROMPT}]DAP>[/] [{TERM_COMMAND_FG}]{command}[/]'
        if self._shell_kind == 'pwsh':
            path = self._cwd or '~'
            return f'[{TERM_PWSH_PROMPT}]PS {path}>[/] [{TERM_COMMAND_FG}]{command}[/]'
        if self._shell_kind == 'terminal':
            return f'[{TERM_PTY_PROMPT}]$[/] [{TERM_COMMAND_FG}]{command}[/]'
        return f'[{TERM_SHELL_PROMPT}]$[/] [{TERM_COMMAND_FG}]{command}[/]'

    def _format_footer_text(self, text: str) -> str:
        if not text:
            return ''
        parts = text.split(' · ')
        markup_parts: list[str] = []
        for part in parts:
            if part.startswith('exit '):
                try:
                    code = int(part.split()[1])
                except (IndexError, ValueError):
                    color = TERM_FOOTER_NEUTRAL
                else:
                    color = footer_color_for_exit_code(code)
                markup_parts.append(f'[{color}]{part}[/]')
            elif part == 'running':
                markup_parts.append(f'[{TERM_PTY_PROMPT}]{part}[/]')
            else:
                markup_parts.append(f'[{TERM_FOOTER_NEUTRAL}]{part}[/]')
        sep = f' [{TERM_FOOTER_NEUTRAL}]·[/] '
        return sep.join(markup_parts)

    def _footer_markup(self) -> str:
        if self._footer:
            return self._format_footer_text(self._footer)
        parts: list[str] = []
        if self._cwd:
            parts.append(f'cwd: {self._cwd}')
        if self._exit_code is not None:
            parts.append(f'exit {self._exit_code}')
        elif self._running:
            parts.append('running')
        return self._format_footer_text(' · '.join(parts)) if parts else ''

    def _output_renderable(self) -> Any:
        if not self._output_text and not self._running:
            return Text('')
        renderable = _format_terminal_output_for_display(self._output_text)
        if self._running:
            if self._output_text:
                renderable.append('\n')
            renderable.append('█', style=f'blink {TERM_RUNNING_CURSOR}')
        if self._hidden_lines:
            prefix = Text(
                f'…{self._hidden_lines} earlier line(s) hidden…\n',
                style=TERM_HIDDEN_LINES_FG,
            )
            if isinstance(renderable, Text):
                renderable = prefix + renderable
            else:
                renderable = prefix
        return renderable

    def compose(self) -> ComposeResult:
        yield Static(
            self._title_markup(), id='terminal-titlebar', classes='terminal-titlebar'
        )
        yield Static(
            self._prompt_markup(), id='terminal-prompt', classes='terminal-prompt'
        )
        with Container(classes='terminal-output-wrap', id='terminal-output-wrap'):
            yield Static(
                self._output_renderable(),
                id='terminal-output',
                classes='terminal-output',
            )
        yield Static(
            self._footer_markup(), id='terminal-footer', classes='terminal-footer'
        )

    def on_mount(self) -> None:
        self._refresh_chrome()

    def _refresh_chrome(self) -> None:
        self._refresh_title()
        self._refresh_prompt()
        self._refresh_output()
        self._refresh_footer()

    def _refresh_title(self) -> None:
        try:
            self.query_one('#terminal-titlebar', Static).update(self._title_markup())
        except Exception:
            pass

    def _refresh_prompt(self) -> None:
        try:
            self.query_one('#terminal-prompt', Static).update(self._prompt_markup())
        except Exception:
            pass

    def _refresh_output(self) -> None:
        try:
            self.query_one('#terminal-output', Static).update(self._output_renderable())
        except Exception:
            pass

    def _refresh_footer(self) -> None:
        try:
            self.query_one('#terminal-footer', Static).update(self._footer_markup())
        except Exception:
            pass
