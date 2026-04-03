"""Live reasoning panel — shows agent thinking step-by-step."""

from __future__ import annotations

import time
from collections import deque

from rich.console import Console, ConsoleOptions, RenderResult
from rich.panel import Panel
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

# Tool-specific icons for the spinner line
_TOOL_ICONS: dict[str, str] = {
    'read': '👁 ',
    'edit': '✏️ ',
    'write': '✏️ ',
    'run': '⚡',
    'bash': '⚡',
    'terminal': '💻',
    'search': '🔍',
    'grep': '🔍',
    'find': '🔍',
    'lsp': '🔍',
    'browse': '🌐',
    'mcp': '🔧',
    'recall': '📚',
    'delegate': '🔀',
    'think': '💭',
    'compress': '🗜️ ',
}


def _icon_for_action(label: str) -> str:
    """Return a tool-specific icon based on the action label."""
    lower = label.lower()
    for key, icon in _TOOL_ICONS.items():
        if key in lower:
            return icon
    return '⚙️ '


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
        self._max_lines: int = 4  # compact: max 4 thought lines
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
            if stripped and (not self._thought_lines or self._thought_lines[-1] != stripped):
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

    def renderable(self) -> Panel:
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(width=2)
        grid.add_column(ratio=1)

        # Elapsed time
        elapsed = ''
        secs = self.elapsed_seconds
        if secs is not None:
            elapsed = f' ({secs}s)'

        # Tool-specific icon
        action_label = self._current_action or 'Thinking…'
        icon = _icon_for_action(action_label)

        grid.add_row(
            Spinner('dots', style='cyan'),
            Text(
                f'{icon} {action_label}{elapsed}',
                style='bold cyan',
            ),
        )

        # Action trail
        if len(self._recent_actions) > 1:
            trail = ' → '.join(self._recent_actions)
            grid.add_row(Text(''), Text(trail, style='bright_black'))

        # Thought lines (compact: max 4)
        for line in self._thought_lines:
            grid.add_row(Text('•', style='bright_black'), Text(line, style='dim italic'))

        # Budget burn when cost is meaningful
        turn_cost = self._current_cost - self._cost_at_start
        if turn_cost > 0.01:
            grid.add_row(
                Text('$', style='green dim'),
                Text(f'Turn cost: ${turn_cost:.4f}', style='green dim'),
            )

        return Panel(grid, title='[dim]agent[/dim]', border_style='bright_black', padding=(0, 1))
