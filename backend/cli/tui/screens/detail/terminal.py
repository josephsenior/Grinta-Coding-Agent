"""TerminalDetailScreen — styled full PTY/tmux scrollback for an interaction."""

from __future__ import annotations

from backend.cli.tui.screens.detail.base import DetailScreen
from backend.cli.tui.screens.detail.helpers import (
    format_exit_chip,
    format_meta_chips,
    render_command_syntax,
    render_terminal_output,
)


class TerminalDetailScreen(DetailScreen):
    """Full session scrollback with traffic-light terminal chrome."""

    def __init__(
        self,
        session_id: str = '',
        command: str = '',
        scrollback: str = '',
        cwd: str = '',
        *,
        title: str = 'Terminal',
        kind: str = 'Term',
        heading: str = '',
        accent: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        super().__init__(
            title=title,
            kind=kind,
            heading=heading or session_id,
            accent=accent,
        )
        self._session_id = session_id
        self._command = command
        self._scrollback = scrollback
        self._cwd = cwd
        self._exit_code = exit_code

    def build_content(self) -> list:
        widgets: list = []

        meta_parts: list[str] = []
        if self._session_id:
            meta_parts.append(f'[#91abec]{self._session_id}[/]')
        if self._cwd:
            meta_parts.append(f'[#969aad]{self._cwd}[/]')
        exit_chip = format_exit_chip(self._exit_code)
        if exit_chip:
            meta_parts.append(exit_chip)
        if meta_parts:
            widgets.append(
                self.meta_row(
                    format_meta_chips(meta_parts), widget_id='terminal-session'
                )
            )

        frame_parts: list = []
        if self._command and not self._scrollback:
            frame_parts.append(
                self.syntax_block(
                    render_command_syntax(self._command),
                    widget_id='terminal-cmd-row',
                )
            )
        if self._scrollback:
            frame_parts.append(
                self.syntax_block(
                    render_terminal_output(self._scrollback, language='text'),
                    widget_id='terminal-scrollback',
                )
            )
        if frame_parts:
            frame_title = (self._session_id or self._heading or 'terminal')[:48]
            widgets.append(self.terminal_frame(*frame_parts, title=frame_title))
        elif not self._command:
            widgets.append(
                self.empty_state('(no terminal content)', widget_id='terminal-empty')
            )

        return widgets
