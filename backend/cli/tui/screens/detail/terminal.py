"""TerminalDetailScreen — full PTY/tmux scrollback for an interaction."""

from __future__ import annotations

from textual.widgets import Static

from backend.cli.tui.screens.detail.base import DetailScreen


class TerminalDetailScreen(DetailScreen):
    """Full session scrollback with ``$``-prefixed commands."""

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
        from rich.text import Text as RichText

        widgets: list = []

        header_parts = [f'session {self._session_id}'] if self._session_id else []
        if self._cwd:
            header_parts.append(f'@{self._cwd}')
        if header_parts:
            widgets.append(
                Static(
                    '[#91abec]' + ' '.join(header_parts) + '[/]',
                    id='terminal-header',
                )
            )

        if self._scrollback:
            display = RichText.from_ansi(self._scrollback)
            widgets.append(Static(display, id='terminal-scrollback'))
        elif self._command:
            cmd_display = f'[bold #5eead4]$[/] [#e2e8f0]{self._command}[/]'
            widgets.append(Static(cmd_display, id='terminal-cmd'))

        if not widgets:
            widgets.append(Static('(no terminal content)', id='terminal-empty'))

        return widgets
