"""DebuggerDetailScreen — call stack and local variables."""

from __future__ import annotations

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
        kind: str = 'Debug',
        heading: str = '',
        accent: str | None = None,
    ) -> None:
        super().__init__(
            title=title,
            kind=kind,
            heading=heading,
            accent=accent,
        )
        self._stack = list(stack or [])
        self._variables = list(variables or [])
        self._current_frame_index = current_frame_index

    def build_content(self) -> list:
        widgets: list = []

        if self._stack:
            widgets.extend(
                self.section(
                    'Stack',
                    *[
                        self.list_row(
                            f'{"→" if idx == self._current_frame_index else " "} {frame}',
                            active=idx == self._current_frame_index,
                        )
                        for idx, frame in enumerate(self._stack)
                    ],
                )
            )

        if self._variables:
            widgets.extend(
                self.section(
                    'Variables',
                    *[
                        self.list_row(
                            f'[#c8d4e8]{name}[/] [#54597b]=[/] [#91abec]{value}[/]'
                        )
                        for name, value in self._variables
                    ],
                )
            )

        if not widgets:
            widgets.append(self.empty_state('(no debugger state)', widget_id='debugger-empty'))

        return widgets
