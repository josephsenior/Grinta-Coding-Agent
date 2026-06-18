"""DebuggerDetailScreen — call stack and local variables."""

from __future__ import annotations

from textual.widgets import Rule, Static

from backend.cli.tui.screens.detail.base import DetailScreen


class DebuggerDetailScreen(DetailScreen):
    """Debugger state: stack trace and local variables."""

    def __init__(
        self,
        stack: list[str] | None = None,
        variables: list[tuple[str, str]] | None = None,
        current_frame_index: int = 0,
        *,
        title: str = 'Debugger',
    ) -> None:
        super().__init__(title=title)
        self._stack = list(stack or [])
        self._variables = list(variables or [])
        self._current_frame_index = current_frame_index

    def build_content(self) -> list:
        widgets: list = []

        if self._stack:
            widgets.append(Rule('Stack', line_style='heavy'))
            for idx, frame in enumerate(self._stack):
                prefix = '  →' if idx == self._current_frame_index else '    '
                style = '#5eead4' if idx == self._current_frame_index else '#c8d4e8'
                widgets.append(
                    Static(
                        f'[{style}]{prefix} {frame}[/]',
                        classes='debugger-frame',
                    )
                )

        if self._variables:
            widgets.append(Rule('Variables', line_style='heavy'))
            for name, value in self._variables:
                widgets.append(
                    Static(
                        f'  [#c8d4e8]{name}[/] [#54597b]=[/] [#91abec]{value}[/]',
                        classes='debugger-var',
                    )
                )

        if not widgets:
            widgets.append(Static('(no debugger state)', id='debugger-empty'))

        return widgets
