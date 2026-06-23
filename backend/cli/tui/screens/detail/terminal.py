"""TerminalDetailScreen — styled full PTY/tmux scrollback for an interaction."""

from __future__ import annotations

from backend.cli.tui.screens.detail.base import DetailScreen
from backend.cli.tui.screens.detail.helpers import (
    build_terminal_detail_content,
    format_cwd_meta,
    format_exit_chip,
    format_session_meta,
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
        kind: str = 'Terminal',
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
        meta_parts: list[str] = []
        if self._session_id:
            meta_parts.append(format_session_meta(self._session_id))
        if self._cwd:
            meta_parts.append(format_cwd_meta(self._cwd))
        exit_chip = format_exit_chip(self._exit_code)
        if exit_chip:
            meta_parts.append(exit_chip)

        return build_terminal_detail_content(
            self,
            meta_parts=meta_parts,
            command=self._command,
            output=self._scrollback,
            frame_title=self._session_id or self._heading or 'terminal',
            show_command_when_no_output=not bool(self._scrollback),
            meta_widget_id='terminal-session',
            cmd_widget_id='terminal-cmd-row',
            output_widget_id='terminal-scrollback',
            empty_widget_id='terminal-empty',
            empty_message='(no terminal content)',
        )
