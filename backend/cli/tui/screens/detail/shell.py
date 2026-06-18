"""ShellDetailScreen — full stdout/stderr output for a one-shot shell command."""

from __future__ import annotations

from textual.widgets import Static

from backend.cli.tui.screens.detail.base import DetailScreen


class ShellDetailScreen(DetailScreen):
    """Full stdout/stderr for a one-shot shell command."""

    def __init__(
        self,
        command: str = '',
        output: str = '',
        exit_code: int | None = None,
        *,
        title: str = 'Shell',
    ) -> None:
        super().__init__(title=title)
        self._command = command
        self._output = output
        self._exit_code = exit_code

    def build_content(self) -> list:
        from rich.text import Text as RichText

        widgets: list = []

        if self._command:
            widgets.append(
                Static(
                    f'[bold #5eead4]$[/] [#e2e8f0]{self._command}[/]',
                    id='shell-cmd',
                )
            )

        if self._output:
            display = RichText.from_ansi(self._output)
            widgets.append(Static(display, id='shell-output'))
        elif self._exit_code is not None:
            widgets.append(
                Static(
                    f'[#54597b]Exit code:[/] [#E24B4A if self._exit_code != 0 else #639922]{self._exit_code}[/]',
                    id='shell-exit',
                )
            )

        if not widgets:
            widgets.append(Static('(no output)', id='shell-empty'))

        return widgets
