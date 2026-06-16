"""Embedded terminal chrome for shell and PTY activity cards."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Static

from backend.cli.tui.constants import _TUI_TERMINAL_DISPLAY_LINE_CAP
from backend.cli.tui.helpers import _format_terminal_output_for_display


class TerminalPane(Vertical):
    """Prompt + scrollback + footer layout mimicking a terminal window."""

    DEFAULT_CSS = """
    TerminalPane {
        width: 100%;
        height: auto;
        background: #0a0e14;
        border: none;
        padding: 0;
        margin: 0;
    }
    TerminalPane .terminal-titlebar {
        width: 100%;
        height: 1;
        background: #141c2e;
        color: #8f9fc1;
        padding: 0 1;
    }
    TerminalPane .terminal-prompt {
        width: 100%;
        height: auto;
        min-height: 1;
        padding: 0 1;
        background: #0a0e14;
    }
    TerminalPane .terminal-output-wrap {
        width: 100%;
        height: auto;
        max-height: 20;
        overflow-y: auto;
        background: #080c12;
        padding: 0 1;
        scrollbar-size-vertical: 1;
        scrollbar-color: #334155 #080c12;
    }
    TerminalPane .terminal-output {
        width: 100%;
        height: auto;
        background: #080c12;
        color: #cbd5e1;
    }
    TerminalPane .terminal-footer {
        width: 100%;
        height: 1;
        background: #0d1219;
        color: #54597b;
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
        running: bool = False,
        id: str | None = None,
    ) -> None:
        super().__init__(id=id)
        self._shell_kind = shell_kind
        self._command = command
        self._cwd = cwd
        self._session_id = session_id
        self._footer = footer
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

    def set_running(self, running: bool) -> None:
        self._running = running
        self._refresh_output()

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
            return f'[#8f9fc1]debugger · {label}[/]'
        if self._shell_kind == 'terminal':
            label = self._session_id[:12] if self._session_id else 'session'
            return f'[#8f9fc1]terminal · {label}[/]'
        label = 'pwsh' if self._shell_kind == 'pwsh' else 'bash'
        return f'[#8f9fc1]{label}[/]'

    def _prompt_markup(self) -> str:
        command = self._command or '…'
        if self._shell_kind == 'debugger':
            return f'[#5eead4]DAP>[/] [#e2e8f0]{command}[/]'
        if self._shell_kind == 'pwsh':
            path = self._cwd or '~'
            return f'[#7dd3fc]PS {path}>[/] [#e2e8f0]{command}[/]'
        if self._shell_kind == 'terminal':
            return f'[#5eead4]$[/] [#e2e8f0]{command}[/]'
        return f'[#54efae]$[/] [#e2e8f0]{command}[/]'

    def _footer_markup(self) -> str:
        if self._footer:
            return f'[#54597b]{self._footer}[/]'
        parts: list[str] = []
        if self._cwd:
            parts.append(f'cwd: {self._cwd}')
        if self._running:
            parts.append('running')
        return f'[#54597b]{" · ".join(parts)}[/]' if parts else ''

    def _output_renderable(self) -> Any:
        if not self._output_text and not self._running:
            return Text('')
        renderable = _format_terminal_output_for_display(self._output_text)
        if self._running:
            if self._output_text:
                renderable.append('\n')
            renderable.append('█', style='blink #5eead4')
        if self._hidden_lines:
            prefix = Text(
                f'…{self._hidden_lines} earlier line(s) hidden…\n',
                style='#54597b',
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
