"""ShellDetailScreen — styled full output for a one-shot shell command."""

from __future__ import annotations

from backend.cli.tui.screens.detail.base import DetailScreen
from backend.cli.tui.screens.detail.helpers import (
    format_exit_chip,
    format_meta_chips,
    render_command_syntax,
    render_terminal_output,
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
        widgets: list = []

        meta_parts: list[str] = []
        if self._cwd:
            meta_parts.append(f'[#969aad]{self._cwd}[/]')
        exit_chip = format_exit_chip(self._exit_code, is_background=self._is_background)
        if exit_chip:
            meta_parts.append(exit_chip)
        if meta_parts:
            widgets.append(
                self.meta_row(format_meta_chips(meta_parts), widget_id='shell-meta')
            )

        frame_parts: list = []
        if self._command:
            frame_parts.append(
                self.syntax_block(
                    render_command_syntax(self._command),
                    widget_id='shell-cmd-row',
                )
            )
        if self._output:
            frame_parts.append(
                self.syntax_block(
                    render_terminal_output(self._output, language='text'),
                    widget_id='shell-output',
                )
            )
        if frame_parts:
            frame_title = (self._heading or self._command or 'shell')[:48]
            widgets.append(self.terminal_frame(*frame_parts, title=frame_title))
        elif not self._command:
            widgets.append(self.empty_state('(no output)', widget_id='shell-empty'))

        return widgets
