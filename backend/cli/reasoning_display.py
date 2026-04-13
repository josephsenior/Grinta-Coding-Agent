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

# Thought lines are rendered without an extra manual prefix so they align with
# other activity panel bodies.
_THOUGHT_LINE_PREFIX_CHARS = 0


def _fit_thought_line(text: str, max_width: int | None) -> str:
    """Avoid ultra-wide lines in narrow terminals."""
    line = (text or '').strip()
    if not line or max_width is None or max_width <= _THOUGHT_LINE_PREFIX_CHARS + 12:
        return line
    budget = max_width - _THOUGHT_LINE_PREFIX_CHARS
    if len(line) <= budget:
        return line
    return line[:budget] if budget <= 4 else f'{line[:budget - 1]}…'


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
        # Completed step labels (excludes the current action) for a short breadcrumb.
        self._recent_actions: deque[str] = deque(maxlen=4)
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
            if stripped := line.strip():
                self._thought_lines.append(stripped)
        # Keep only the last N lines for a compact view.
        if len(self._thought_lines) > self._max_lines:
            self._thought_lines = self._thought_lines[-self._max_lines :]

    def set_streaming_thought(self, text: str) -> None:
        """Replace thought lines with new content (for cumulative streaming updates)."""
        self.start()
        self._thought_lines.clear()
        for line in text.splitlines():
            if stripped := line.strip():
                self._thought_lines.append(stripped)
        if len(self._thought_lines) > self._max_lines:
            self._thought_lines = self._thought_lines[-self._max_lines :]

    def update_action(self, label: str) -> None:
        self.start()
        new = (label or '').strip()
        if new != self._current_action:
            if self._current_action:
                self._recent_actions.append(self._current_action)
            self._current_action = new

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
        panel_max_lines = None
        if options.max_height:
            panel_max_lines = max(3, min(10, options.max_height - 6))
        yield self.renderable(max_width=options.max_width, max_lines=panel_max_lines)

    def renderable(
        self,
        *,
        max_width: int | None = None,
        max_lines: int | None = None,
    ) -> Any:
        elapsed_bits: list[str] = []
        secs = self.elapsed_seconds
        if secs is not None:
            m, s = divmod(secs, 60)
            elapsed_bits.append(f'{m}m {s}s' if m > 0 else f'{s}s')

        turn_cost = max(0.0, self._current_cost - self._cost_at_start)
        if turn_cost > 0.0:
            elapsed_bits.append(f'+${turn_cost:.4f}')

        meta_right = ' · '.join(elapsed_bits) if elapsed_bits else ''

        action_label = self._current_action or 'Thinking…'
        if max_width and len(action_label) > max(24, max_width - 24):
            action_label = f'{action_label[:max(8, max_width - 28)]}…'

        rows: list[Any] = []

        header_left = Table.grid(expand=True, padding=(0, 1))
        header_left.add_column(no_wrap=True)
        header_left.add_column(ratio=1)
        header_left.add_row(
            Spinner('dots', style='cyan'),
            Text(action_label, style='bold cyan'),
        )

        header = Table.grid(expand=True, padding=(0, 0))
        header.add_column(ratio=1)
        header.add_column(justify='right')
        header.add_row(
            header_left,
            Text(meta_right, style='dim') if meta_right else Text(''),
        )
        rows.append(header)

        if trail := list(self._recent_actions):
            self._append_recent_actions_crumb(trail, rows)
        visible_thoughts = self._thought_lines
        clipped = False
        if max_lines is not None and max_lines >= 0 and len(visible_thoughts) > max_lines:
            visible_thoughts = visible_thoughts[-max_lines:]
            clipped = True

        for line in visible_thoughts:
            fitted = _fit_thought_line(line, max_width)
            rows.append(Text(fitted, style='italic dim'))

        if clipped:
            rows.append(Text('auto-scroll: showing latest thoughts', style='dim italic'))

        hint = Text()
        hint.append('Ctrl+C', style='bold dim')
        hint.append(' interrupts', style='dim italic')
        rows.append(hint)

        return format_callout_panel(
            'Thinking',
            Group(*rows),
            accent_style='dim cyan',
            padding=(0, 0),
        )

    def _append_recent_actions_crumb(
        self,
        trail: list[str],
        rows: list[Any],
    ) -> None:
        # Last two completed steps — helps users see what already happened.
        tail = trail[-2:]
        crumb = Text()
        crumb.append('then ', style='dim italic')
        crumb.append(' → '.join(tail), style='dim italic')
        rows.append(crumb)
