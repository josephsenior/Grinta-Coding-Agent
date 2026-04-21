"""Live reasoning panel — compact *activity* chrome while the agent works.

Thought text is **not** duplicated here: model reasoning streams into this
object for snapshotting, but :meth:`renderable` shows only the header (spinner
+ current action + elapsed/cost). Committed thoughts are flushed to the main
transcript via :func:`backend.cli.transcript.format_reasoning_snapshot`, styled
dim so they read as internal monologue rather than assistant reply.

No duplicate Ctrl+C hint (the fake-prompt bar directly below the panel
already shows "Agent working… ctrl+c to interrupt"), and no inline
breadcrumb — the committed activity stream above the panel already
tells the user what happened earlier in the turn.
"""

from __future__ import annotations

import textwrap
import time
from typing import Any

from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.spinner import Spinner
from rich.table import Table
from rich.text import Text

from backend.cli.transcript import format_callout_panel
from backend.engine import prompt_role_debug as _prompt_role_debug

# Thought lines are rendered without an extra manual prefix so they align with
# other activity panel bodies.
_THOUGHT_LINE_PREFIX_CHARS = 0
# Safety cap on stored logical lines (streaming can be very chatty).
_MAX_STORED_THOUGHT_LINES = 50_000


# Panel chrome overhead: ``╭─ Thinking ─╮`` borders + left/right padding added
# by ``format_callout_panel``. Subtract from ``max_width`` before handing the
# width to ``textwrap.wrap`` so wrapped rows fit inside the panel instead of
# being clipped by Rich when the rendered row exceeds the interior width.
_PANEL_CHROME_WIDTH = 6

# Character used at the end of the latest thought while streaming is active.
# Rich spinner in the header already conveys "thinking" — this cursor conveys
# "tokens are still flowing for this specific thought".
_STREAM_CURSOR = '▌'


def _truncate_action_line(label: str, max_len: int) -> str:
    """Ellipsis at end of label, preferring a word boundary when there is room."""
    text = (label or '').strip()
    if max_len <= 0 or len(text) <= max_len:
        return text
    if max_len <= 1:
        return '…'
    limit = max_len - 1
    chunk = text[:limit]
    if ' ' in chunk:
        at = chunk.rfind(' ')
        if at > max(6, limit // 4):
            chunk = chunk[:at].rstrip()
    return f'{chunk}…'


def _thought_lines_for_display(line: str, max_width: int | None) -> list[str]:
    """One logical thought line → one or more panel rows (wrap when width is known).

    Never truncates with an ellipsis — we prefer to wrap across multiple
    rows so the user can read the full thought. When the terminal is too
    narrow to meaningfully wrap, we fall back to returning the line as-is
    (Rich will then soft-wrap the row itself).
    """
    stripped = (line or '').strip()
    if not stripped:
        return []
    if max_width is None or max_width <= _PANEL_CHROME_WIDTH + 12:
        return [stripped]
    wrap_width = max(12, max_width - _PANEL_CHROME_WIDTH - _THOUGHT_LINE_PREFIX_CHARS)
    wrapped = textwrap.wrap(
        stripped,
        width=wrap_width,
        break_long_words=True,
        break_on_hyphens=False,
    )
    return wrapped or [stripped]


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
        self._max_lines: int = _MAX_STORED_THOUGHT_LINES
        self._start_time: float | None = None
        self._cost_at_start: float = 0.0
        self._current_cost: float = 0.0
        self._last_debug_stream_log: float = 0.0
        # True when ``set_streaming_thought`` has written content since the
        # last non-streaming update — drives the trailing stream cursor.
        self._streaming: bool = False

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
        self._thought_lines.clear()
        self._current_action = ''
        self._start_time = None
        self._streaming = False
        _prompt_role_debug.log_reasoning_transition('reasoning.stop', '')

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
        _prompt_role_debug.log_reasoning_transition('reasoning.update_thought', text)
        for line in text.splitlines():
            if stripped := line.strip():
                self._thought_lines.append(stripped)
        if len(self._thought_lines) > self._max_lines:
            self._thought_lines = self._thought_lines[-self._max_lines :]
        # A non-streaming thought snapshot turns the cursor off again.
        self._streaming = False

    def set_streaming_thought(self, text: str) -> None:
        """Replace thought lines with new content (for cumulative streaming updates)."""
        self.start()
        if _prompt_role_debug.env_reasoning_astep_debug():
            now = time.monotonic()
            if now - self._last_debug_stream_log >= 1.0:
                self._last_debug_stream_log = now
                _prompt_role_debug.log_reasoning_transition(
                    'reasoning.set_streaming_thought', text
                )
        self._thought_lines.clear()
        for line in text.splitlines():
            if stripped := line.strip():
                self._thought_lines.append(stripped)
        if len(self._thought_lines) > self._max_lines:
            self._thought_lines = self._thought_lines[-self._max_lines :]
        self._streaming = bool(self._thought_lines)

    def update_action(self, label: str) -> None:
        self.start()
        new = (label or '').strip()
        if new != self._current_action:
            _prompt_role_debug.log_reasoning_transition('reasoning.update_action', new)
            self._current_action = new
            # Per-step wall clock: the header timer should reflect the *current* sub-step
            # (e.g. browser CDP), not time since the first spinner in this agent turn.
            self._start_time = time.monotonic()
            # Action changes end any prior streaming run — the model is
            # committing to a next step, not still generating text.
            self._streaming = False

    def snapshot_thoughts(self) -> list[str]:
        """Return a copy of current thought lines without clearing them."""
        return list(self._thought_lines)

    def update_cost(self, cost_usd: float) -> None:
        """Track current session cost for budget burn display."""
        self._current_cost = cost_usd

    def set_cost_baseline(self, cost_usd: float) -> None:
        """Set cost baseline at the start of a turn."""
        self._cost_at_start = cost_usd

    @staticmethod
    def live_panel_shows_thought_rows() -> bool:
        """Whether the Rich Live layout should reserve vertical space for thought lines.

        When ``False`` (default), only the Thinking *header* (spinner + action)
        appears in the live panel; thought bodies are transcript-only. This
        avoids duplicating long CoT next to the draft reply and keeps the two
        streams visually distinct.
        """
        return False

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
        elapsed_bits: list[str] = []
        secs = self.elapsed_seconds
        if secs is not None:
            m, s = divmod(secs, 60)
            elapsed_bits.append(f'{m}m {s}s' if m > 0 else f'{s}s')

        turn_cost = max(0.0, self._current_cost - self._cost_at_start)
        if turn_cost > 0.0:
            elapsed_bits.append(f'+${turn_cost:.4f}')

        meta_right = ' · '.join(elapsed_bits) if elapsed_bits else ''

        action_label = self._current_action or 'Thinking'
        # Reserve room for the right-side meta + separators when trimming.
        reserved = len(meta_right) + 6 if meta_right else 4
        if max_width and len(action_label) > max(24, max_width - reserved):
            action_label = _truncate_action_line(
                action_label, max(12, max_width - reserved)
            )

        rows: list[Any] = []

        header = Table.grid(expand=True, padding=(0, 0))
        header.add_column(width=2, no_wrap=True)
        header.add_column(ratio=1)
        header.add_column(justify='right', no_wrap=True)
        header.add_row(
            Spinner('dots', style='#7dd3fc'),
            Text(action_label, style='bold #dbe7f3'),
            Text(meta_right, style='#5d7286') if meta_right else Text(''),
        )
        rows.append(header)

        # Thought bodies are intentionally omitted from the live panel — they
        # are flushed to the transcript (dim) so they are not mistaken for the
        # assistant reply and do not compete with the draft-reply preview for
        # vertical space. ``_thought_lines`` are still maintained for
        # :meth:`snapshot_thoughts` / :meth:`CLIEventRenderer._flush_thinking_block`.
        if self.live_panel_shows_thought_rows():
            wrapped_rows: list[str] = []
            for line in self._thought_lines:
                wrapped_rows.extend(_thought_lines_for_display(line, max_width))

            clipped = False
            if max_lines is not None and max_lines >= 0 and len(wrapped_rows) > max_lines:
                wrapped_rows = wrapped_rows[-max_lines:]
                clipped = True

            if wrapped_rows and self._streaming:
                wrapped_rows = wrapped_rows[:-1] + [wrapped_rows[-1] + _STREAM_CURSOR]

            for row in wrapped_rows:
                rows.append(Text(row, style='#8b9eb5 dim'))

            if clipped:
                rows.append(
                    Text('… showing latest thoughts', style='#5d7286 italic')
                )

        return format_callout_panel(
            'Thinking',
            Group(*rows),
            accent_style='#4a6b82',
            padding=(0, 0),
        )
