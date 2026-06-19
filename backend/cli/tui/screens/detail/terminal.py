"""TerminalDetailScreen — styled full PTY/tmux scrollback for an interaction."""

from __future__ import annotations

from textual.widgets import Static

from backend.cli.tui.screens.detail.base import DetailScreen


class TerminalDetailScreen(DetailScreen):
    """Full session scrollback with ``$``-prefixed commands."""

    DEFAULT_CSS = """
    TerminalDetailScreen #terminal-session {
        width: 100%;
        height: auto;
        padding: 1 2 0 2;
        color: #91abec;
        background: #080c18;
        border-bottom: solid #1e293b;
    }
    TerminalDetailScreen #terminal-cmd-row {
        width: 100%;
        height: auto;
        padding: 1 2 0 2;
        color: #e2e8f0;
    }
    TerminalDetailScreen #terminal-scrollback {
        width: 100%;
        height: auto;
        padding: 0;
        background: #060a14;
        color: #6b7280;
    }
    TerminalDetailScreen #terminal-empty {
        width: 100%;
        height: auto;
        padding: 2;
        color: #54597b;
        text-align: center;
    }
    """

    def __init__(
        self,
        session_id: str = '',
        command: str = '',
        scrollback: str = '',
        cwd: str = '',
        *,
        title: str = 'Terminal',
    ) -> None:
        super().__init__(title=title)
        self._session_id = session_id
        self._command = command
        self._scrollback = scrollback
        self._cwd = cwd

    def build_content(self) -> list:
        widgets: list = []

        meta_parts: list[str] = []
        if self._session_id:
            meta_parts.append(f'[#91abec]{self._session_id}[/]')
        if self._cwd:
            meta_parts.append(f'[#969aad]{self._cwd}[/]')
        if meta_parts:
            widgets.append(
                Static(' · '.join(meta_parts), id='terminal-session')
            )

        if self._command and not self._scrollback:
            prompt = '[#5eead4]$[/]'
            cmd_text = f'[bold #e2e8f0]{self._command}[/]'
            widgets.append(
                Static(f'{prompt} {cmd_text}', id='terminal-cmd-row')
            )

        if self._scrollback:
            display = self._format_scrollback(self._scrollback)
            widgets.append(Static(display, id='terminal-scrollback'))
        elif not self._command:
            widgets.append(Static('(no terminal content)', id='terminal-empty'))

        return widgets

    @staticmethod
    def _format_scrollback(scrollback: str) -> str:
        lines = scrollback.splitlines()
        if not lines:
            return scrollback
        max_width = len(str(len(lines)))
        numbered: list[str] = []
        for i, line in enumerate(lines, 1):
            gutter = f'[#374151]{i:>{max_width}} │[/] '
            numbered.append(gutter + line)
        return '\n'.join(numbered)
