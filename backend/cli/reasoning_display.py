"""Live reasoning panel — shows agent thinking step-by-step."""

from __future__ import annotations

import time

from rich.console import Console, ConsoleOptions, RenderResult
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text


class ReasoningDisplay:
    """Renderable reasoning state used inside the main live layout.

    Usage::

        rd = ReasoningDisplay()
        rd.start()
        rd.update_thought("Analyzing the codebase…")
        rd.update_action("Reading file src/main.py")
        rd.stop()
    """

    def __init__(self) -> None:
        self._active = False
        self._thought_lines: list[str] = []
        self._current_action: str = ''
        self._max_lines: int = 8
        self._start_time: float | None = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._active = True
        if self._start_time is None:
            self._start_time = time.monotonic()

    def stop(self) -> None:
        self._active = False
        self._thought_lines.clear()
        self._current_action = ''
        self._start_time = None

    @property
    def active(self) -> bool:
        return self._active

    @property
    def elapsed_seconds(self) -> int | None:
        if self._start_time is None:
            return None
        return max(0, int(time.monotonic() - self._start_time))

    # -- updates -----------------------------------------------------------

    def update_thought(self, text: str) -> None:
        self.start()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                self._thought_lines.append(stripped)
        # Keep only the last N lines for a compact view.
        if len(self._thought_lines) > self._max_lines:
            self._thought_lines = self._thought_lines[-self._max_lines :]

    def set_streaming_thought(self, text: str) -> None:
        """Replace thought lines with new content (for cumulative streaming updates)."""
        self.start()
        self._thought_lines.clear()
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                self._thought_lines.append(stripped)
        if len(self._thought_lines) > self._max_lines:
            self._thought_lines = self._thought_lines[-self._max_lines :]

    def update_action(self, label: str) -> None:
        self.start()
        self._current_action = label

    # -- rendering ---------------------------------------------------------

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        if not self.active:
            return
        yield self.renderable()

    def renderable(self) -> Panel:
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(width=2)
        grid.add_column(ratio=1)
        elapsed = ''
        secs = self.elapsed_seconds
        if secs is not None:
            elapsed = f' ({secs}s)'
        grid.add_row(
            Spinner('dots', style='cyan'),
            Text(
                (self._current_action or 'Thinking…') + elapsed,
                style='bold cyan',
            ),
        )
        for line in self._thought_lines:
            grid.add_row(Text(''), Text(line, style='dim italic'))
        return Panel(
            grid,
            border_style='bright_black',
            padding=(0, 1),
            title='Reasoning',
        )
