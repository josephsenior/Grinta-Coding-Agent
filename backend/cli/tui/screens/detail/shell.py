"""ShellDetailScreen — styled full output for a one-shot shell command."""

from __future__ import annotations

from textual.widgets import Static

from backend.cli.tui.screens.detail.base import DetailScreen


class ShellDetailScreen(DetailScreen):
    """Full stdout/stderr for a one-shot shell command with styled output."""

    DEFAULT_CSS = """
    ShellDetailScreen #shell-cmd-row {
        width: 100%;
        height: auto;
        padding: 1 2 0 2;
        color: #e2e8f0;
    }
    ShellDetailScreen #shell-meta {
        width: 100%;
        height: auto;
        padding: 0 2 0 2;
        color: #969aad;
        background: #080c18;
        border-bottom: solid #1e293b;
    }
    ShellDetailScreen #shell-output {
        width: 100%;
        height: auto;
        padding: 1 2 1 2;
        background: #060a14;
        color: #6b7280;
    }
    ShellDetailScreen #shell-empty {
        width: 100%;
        height: auto;
        padding: 2;
        color: #54597b;
        text-align: center;
    }
    """

    def __init__(
        self,
        command: str = '',
        output: str = '',
        exit_code: int | None = None,
        cwd: str = '',
        *,
        title: str = 'Shell',
    ) -> None:
        super().__init__(title=title)
        self._command = command
        self._output = output
        self._exit_code = exit_code
        self._cwd = cwd

    def build_content(self) -> list:
        widgets: list = []

        if self._command:
            prompt = '[#5eead4]$[/]'
            cmd_text = f'[bold #e2e8f0]{self._command}[/]'
            widgets.append(
                Static(f'{prompt} {cmd_text}', id='shell-cmd-row')
            )

        meta_parts: list[str] = []
        if self._cwd:
            meta_parts.append(f'[#969aad]{self._cwd}[/]')
        if self._exit_code is not None:
            if self._exit_code == 0:
                meta_parts.append('[#639922]✓ exit 0[/]')
            else:
                meta_parts.append(f'[#E24B4A]✗ exit {self._exit_code}[/]')
        if meta_parts:
            widgets.append(
                Static(' · '.join(meta_parts), id='shell-meta')
            )

        if self._output:
            display = self._format_output_with_line_numbers(self._output)
            widgets.append(Static(display, id='shell-output'))
        elif not self._command:
            widgets.append(Static('(no output)', id='shell-empty'))

        return widgets

    @staticmethod
    def _format_output_with_line_numbers(output: str) -> str:
        lines = output.splitlines()
        if not lines:
            return output
        max_width = len(str(len(lines)))
        numbered: list[str] = []
        for i, line in enumerate(lines, 1):
            gutter = f'[#374151]{i:>{max_width}} │[/] '
            numbered.append(gutter + line)
        return '\n'.join(numbered)
