"""ShellDetailScreen — styled full output for a one-shot shell command."""

from __future__ import annotations

from backend.cli.tui.screens.detail.base import DetailScreen
from backend.cli.tui.screens.detail.helpers import (
    build_terminal_detail_content,
    format_cwd_meta,
    format_exit_chip,
)


class ShellDetailScreen(DetailScreen):
    """Full stdout/stderr for a one-shot shell command with styled output."""

    def __init__(
        self,
        command: str = '',
        output: str = '',
        exit_code: int | None = None,
        cwd: str = '',
        *,
        is_background: bool = False,
        title: str = 'Shell',
        kind: str = 'Shell',
        heading: str = '',
        accent: str | None = None,
    ) -> None:
        super().__init__(
            title=title,
            kind=kind,
            heading=heading or command,
            accent=accent,
        )
        self._command = command
        self._output = output
        self._exit_code = exit_code
        self._cwd = cwd
        self._is_background = is_background

    def build_content(self) -> list:
        meta_parts: list[str] = []
        if self._cwd:
            meta_parts.append(format_cwd_meta(self._cwd))
        exit_chip = format_exit_chip(self._exit_code, is_background=self._is_background)
        if exit_chip:
            meta_parts.append(exit_chip)

        return build_terminal_detail_content(
            self,
            meta_parts=meta_parts,
            command=self._command,
            output=self._output,
            frame_title=self._heading or self._command or 'shell',
            show_command_when_no_output=True,
            meta_widget_id='shell-meta',
            cmd_widget_id='shell-cmd-row',
            output_widget_id='shell-output',
            empty_widget_id='shell-empty',
        )
