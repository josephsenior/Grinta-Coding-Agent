"""Live reasoning panel — shows agent thinking step-by-step."""

from __future__ import annotations

import time
from collections import deque
from typing import Any

from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from backend.cli.transcript import format_callout_panel


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
        self._recent_actions: deque[str] = deque(maxlen=3)
        self._max_lines: int = 10  # show up to 10 thought lines for real-time stream
        self._start_time: float | None = None
        self._cost_at_start: float = 0.0
        self._current_cost: float = 0.0

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        self._active = True
        if self._start_time is None:
            self._start_time = time.monotonic()

    def stop(self) -> None:
        self._active = False
        self._thought_lines.clear()
        self._current_action = ''
        self._recent_actions.clear()
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
        if label and label != self._current_action:
            self._recent_actions.append(label)
        self._current_action = label

    def snapshot_thoughts(self) -> list[str]:
        """Return a copy of current thought lines without clearing them."""
        return list(self._thought_lines)

    def update_cost(self, cost_usd: float) -> None:
        """Track current session cost for budget burn display."""
        self._current_cost = cost_usd

    def set_cost_baseline(self, cost_usd: float) -> None:
        """Set cost baseline at the start of a turn."""
        self._cost_at_start = cost_usd

    # -- rendering ---------------------------------------------------------

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        if not self.active:
            return
        yield self.renderable()

    def renderable(self) -> Any:
        elapsed_bits: list[str] = []
        secs = self.elapsed_seconds
        if secs is not None:
            m, s = divmod(secs, 60)
            elapsed_bits.append(f'{m}m {s}s' if m > 0 else f'{s}s')

        turn_cost = max(0.0, self._current_cost - self._cost_at_start)
        if turn_cost > 0.0:
            elapsed_bits.append(f'+${turn_cost:.4f}')
        elapsed_bits.append('esc to interrupt')

        action_label = self._current_action or 'Thinking…'
        rows: list[Any] = []

        header = Table.grid(expand=True)
        header.add_column(width=3)
        header.add_column(ratio=1)
        header.add_column(justify='right')
        header.add_row(
            Spinner('dots', style='dim'),
            Text(action_label, style='bold dim'),
            Text(' · '.join(elapsed_bits), style='dim'),
        )
        rows.append(header)

        for line in self._thought_lines:
            t = Text()
            t.append('  ', style='')
            t.append('· ', style='dim')
            t.append(line, style='dim')
            rows.append(t)

        return format_callout_panel(
            'Working',
            Group(*rows),
            accent_style='dim',
        )
