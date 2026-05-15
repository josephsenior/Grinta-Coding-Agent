"""Live reasoning panel — activity chrome while the agent works.

Two separate buffers:
- ``_committed_lines`` — distinct reasoning steps from AgentThinkAction/Observation,
  appended over the course of a turn.  Preserved for the final committed output.
- ``_streaming_line`` — the current streaming thought from the model, replaced
  on every streaming chunk.  Shown in the Live display only, never persisted.

When the turn ends, :meth:`CLIEventRenderer._flush_thinking_block`
collects ``_committed_lines`` for the transcript via
:func:`backend.cli.transcript.format_reasoning_snapshot`.
"""

from __future__ import annotations

import textwrap
import time
from typing import Any

from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.text import Text

from backend.cli.layout_tokens import (
    CALLOUT_PANEL_CHROME_WIDTH,
)
from backend.cli.theme import CLR_META, NAVY_TEXT_MUTED
from backend.engine import prompt_role_debug as _prompt_role_debug

# Panel chrome overhead: live ``MINIMAL`` frame + horizontal padding from
# :func:`backend.cli.transcript.format_live_panel`. Sourced from ``layout_tokens`` so the wrap
# width tracks the actual rendered panel and never desynchronises if the
# padding token is retuned in one place but forgotten here.
_PANEL_CHROME_WIDTH = CALLOUT_PANEL_CHROME_WIDTH

# Character used at the end of the latest thought while streaming is active.
# Uses a thinner block character for a more subtle instrumentation feel.
_STREAM_CURSOR = '\u258c'

# Left gutter marker for reasoning blocks (vertical bar in teal).
_GUTTER_MARKER = '┃'

# Safety cap on stored logical lines (streaming can be very chatty).
_MAX_STORED_THOUGHT_LINES = 50_000


def _thought_lines_for_display(
    line: str,
    max_width: int | None,
    *,
    stable_wrap_width: int | None = None,
) -> list[str]:
    """One logical thought line → one or more panel rows (wrap when width is known).

    Never truncates with an ellipsis — we prefer to wrap across multiple
    rows so the user can read the full thought. When the terminal is too
    narrow to meaningfully wrap, we fall back to returning the line as-is
    (Rich will then soft-wrap the row itself).

    *stable_wrap_width* pins the wrap column during streaming so rapid token
    updates do not change the line break positions (wrap jitter).
    """
    stripped = (line or '').strip()
    if not stripped:
        return []
    if max_width is None or max_width <= _PANEL_CHROME_WIDTH + 12:
        return [stripped]
    computed = max(12, max_width - _PANEL_CHROME_WIDTH)
    wrap_width = stable_wrap_width if stable_wrap_width is not None else computed
    wrapped = textwrap.wrap(
        stripped,
        width=wrap_width,
        break_long_words=True,
        break_on_hyphens=False,
    )
    return wrapped or [stripped]


class ReasoningDisplay:
    """Renderable reasoning state used inside the main live layout.

    Two buffers (see module docstring): ``_committed_lines`` for distinct
    reasoning steps and ``_streaming_line`` for the current streaming thought.

    Usage::

        rd = ReasoningDisplay()
        rd.start()
        rd.set_streaming_thought("Analyzing the codebase…")
        rd.update_action("Reading file src/main.py")
        rd.stop()
    """

    def __init__(self) -> None:
        self._active = False
        self._committed_lines: list[str] = []
        self._streaming_line: str = ''
        self._current_action: str = ''
        self._max_lines: int = _MAX_STORED_THOUGHT_LINES
        self._start_time: float | None = None
        self._cost_at_start: float = 0.0
        self._current_cost: float = 0.0
        self._last_debug_stream_log: float = 0.0
        # True when ``set_streaming_thought`` has written content since the
        # last non-streaming update — drives the trailing stream cursor.
        self._streaming: bool = False
        # First computed wrap width while streaming — kept stable until streaming ends.
        self._stream_wrap_width: int | None = None
        # Step tracking for ETA estimation.
        self._step_count: int = 0
        self._step_times: list[float] = []  # monotonic timestamps of each commit

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        was_active = self._active
        self._active = True
        if self._start_time is None:
            self._start_time = time.monotonic()
        if not was_active:
            _prompt_role_debug.log_reasoning_transition('reasoning.start', '')

    def stop(self) -> None:
        self._active = False
        self._committed_lines.clear()
        self._streaming_line = ''
        self._current_action = ''
        self._start_time = None
        self._streaming = False
        self._stream_wrap_width = None
        self._step_count = 0
        self._step_times.clear()
        _prompt_role_debug.log_reasoning_transition('reasoning.stop', '')

    @property
    def active(self) -> bool:
        return self._active

    @property
    def elapsed_seconds(self) -> int | None:
        if self._start_time is None:
            return None
        return max(0, int(time.monotonic() - self._start_time))

    @property
    def step_count(self) -> int:
        """Number of committed reasoning steps in this turn."""
        return self._step_count

    @property
    def avg_step_duration(self) -> float | None:
        """Average seconds per step, or None if fewer than 2 steps."""
        if len(self._step_times) < 2 or self._start_time is None:
            return None
        total = self._step_times[-1] - self._start_time
        return total / len(self._step_times)

    @property
    def eta_display(self) -> str | None:
        """Formatted ETA string like '~2m 15s remaining', or None if not enough data.

        Uses a rolling average of the last 5 step durations to estimate
        remaining time. Returns None until at least 3 steps have completed.
        """
        if self._start_time is None or self._step_count < 3:
            return None
        # Use rolling window of last 5 step intervals for responsiveness.
        window = min(5, len(self._step_times) - 1)
        if window < 1:
            return None
        recent_times = self._step_times[-window - 1 :]
        intervals = [
            recent_times[i + 1] - recent_times[i] for i in range(len(recent_times) - 1)
        ]
        avg = sum(intervals) / len(intervals)
        if avg <= 0:
            return None
        # Heuristic: agent tasks typically need ~8-15 steps.
        # Use the current step count to project forward.
        estimated_total = max(self._step_count + 3, int(self._step_count * 1.3))
        remaining_steps = max(0, estimated_total - self._step_count)
        eta_seconds = int(remaining_steps * avg)
        if eta_seconds <= 0:
            return None
        if eta_seconds < 60:
            return f'~{eta_seconds}s remaining'
        minutes = eta_seconds // 60
        seconds = eta_seconds % 60
        if seconds > 0:
            return f'~{minutes}m {seconds}s remaining'
        return f'~{minutes}m remaining'

    # -- updates -----------------------------------------------------------

    def set_streaming_thought(self, text: str) -> None:
        """Replace the current streaming thought (Live display only)."""
        self.start()
        if _prompt_role_debug.env_reasoning_astep_debug():
            now = time.monotonic()
            if now - self._last_debug_stream_log >= 1.0:
                self._last_debug_stream_log = now
                _prompt_role_debug.log_reasoning_transition(
                    'reasoning.set_streaming_thought', text
                )
        self._streaming_line = text.strip()
        self._streaming = bool(self._streaming_line)

    def commit_thought(self, text: str) -> None:
        """Append a distinct reasoning step to the committed history.

        Called for AgentThinkAction / AgentThinkObservation — these represent
        the model committing to a discrete reasoning step.  The committed
        lines are preserved for the final assistant message.
        """
        self.start()
        _prompt_role_debug.log_reasoning_transition('reasoning.commit_thought', text)
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if self._committed_lines and self._committed_lines[-1] == stripped:
                continue  # skip consecutive duplicate
            self._committed_lines.append(stripped)
        if len(self._committed_lines) > self._max_lines:
            self._committed_lines = self._committed_lines[-self._max_lines :]
        # A committed thought ends any prior streaming run.
        self._streaming = False
        self._stream_wrap_width = None
        # Track step timing for ETA.
        self._step_count += 1
        now = time.monotonic()
        self._step_times.append(now)
        # Keep only the last 100 timestamps to bound memory within long turns.
        if len(self._step_times) > 100:
            self._step_times = self._step_times[-100:]

    def update_action(self, label: str) -> None:
        self.start()
        new = (label or '').strip()
        if new != self._current_action:
            _prompt_role_debug.log_reasoning_transition('reasoning.update_action', new)
            self._current_action = new
            # Action changes end any prior streaming run — the model is
            # committing to a next step, not still generating text.
            self._streaming = False
            self._stream_wrap_width = None

    def snapshot_thoughts(self) -> list[str]:
        """Return a copy of committed thought lines without clearing them."""
        return list(self._committed_lines)

    def get_streaming_line(self) -> str:
        """Return the current streaming thought line."""
        return self._streaming_line

    def update_cost(self, cost_usd: float) -> None:
        """Track current session cost for budget burn display."""
        self._current_cost = cost_usd

    def set_cost_baseline(self, cost_usd: float) -> None:
        """Set cost baseline at the start of a turn."""
        self._cost_at_start = cost_usd

    def live_panel_shows_thought_rows(self) -> bool:
        """Whether the Rich Live layout should reserve vertical space for thought lines.

        When there is no thought text yet, only the Thinking *header* (spinner +
        action) appears so idle states stay compact. As soon as the model
        supplies reasoning (streaming or snapshot lines), the strip grows to
        show the live-updating body within the renderer's line budget.
        """
        return bool(self._committed_lines or self._streaming_line)

    # -- rendering ---------------------------------------------------------

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        if not self.active:
            return
        yield self.renderable(max_width=options.max_width, max_lines=None)

    def renderable(
        self,
        *,
        max_width: int | None = None,
        max_lines: int | None = None,
    ) -> Any:
        rows: list[Any] = []

        if self.live_panel_shows_thought_rows():
            self._append_thought_rows(rows, max_width, max_lines)

        # Append ETA footer if available.
        eta = self.eta_display
        if eta and rows:
            elapsed = self.elapsed_seconds
            elapsed_str = f'{elapsed}s' if elapsed is not None else '?'
            footer = f'{_GUTTER_MARKER} step {self._step_count} · {elapsed_str} elapsed · {eta}'
            rows.append(Text(footer, style=CLR_META))

        if not rows:
            return Group()

        return Group(*rows)

    def _append_thought_rows(
        self,
        rows: list[Any],
        max_width: int | None,
        max_lines: int | None,
    ) -> None:
        stable: int | None = None
        if self._streaming and max_width and max_width > _PANEL_CHROME_WIDTH + 12:
            inner = max(12, max_width - _PANEL_CHROME_WIDTH)
            if self._stream_wrap_width is None:
                self._stream_wrap_width = inner
            stable = self._stream_wrap_width

        wrapped_rows: list[str] = []
        entry_starts: set[int] = set()

        # Each committed line is its own thought entry with a gutter marker.
        for line in self._committed_lines:
            entry_wrapped = _thought_lines_for_display(
                line, max_width, stable_wrap_width=stable
            )
            if entry_wrapped:
                entry_starts.add(len(wrapped_rows))
                wrapped_rows.extend(entry_wrapped)

        # The streaming line is rendered as a separate final entry.
        if self._streaming and self._streaming_line:
            stream_wrapped = _thought_lines_for_display(
                self._streaming_line, max_width, stable_wrap_width=stable
            )
            if stream_wrapped:
                entry_starts.add(len(wrapped_rows))
                wrapped_rows.extend(stream_wrapped)

        clipped = False
        if max_lines is not None and max_lines >= 0 and len(wrapped_rows) > max_lines:
            wrapped_rows = wrapped_rows[-max_lines:]
            clipped = True

        if wrapped_rows and self._streaming and self._streaming_line:
            wrapped_rows = wrapped_rows[:-1] + [wrapped_rows[-1] + _STREAM_CURSOR]

        for i, row in enumerate(wrapped_rows):
            # First row of each entry gets the gutter marker
            if i in entry_starts:
                rows.append(Text(f'{_GUTTER_MARKER} {row}', style=NAVY_TEXT_MUTED))
            else:
                rows.append(Text(f'  {row}', style=NAVY_TEXT_MUTED))

        if clipped:
            rows.append(
                Text(f'{_GUTTER_MARKER} … showing latest thoughts', style=CLR_META)
            )
