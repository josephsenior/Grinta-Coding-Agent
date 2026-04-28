"""Event stream → terminal renderer.

Subscribes to the backend EventStream and translates events into rich
terminal output.  Handles all three reasoning paths (LLM reasoning,
AgentThinkAction, tool __thought), command output, file edits, errors,
and confirmation flow.
"""

from __future__ import annotations

import asyncio
import logging
import re
import textwrap
import time
from collections import deque
from collections.abc import Callable
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from rich import box
from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from backend.cli.hud import HUDBar
from backend.cli.layout_tokens import (
    ACTIVITY_BLOCK_BOTTOM_PAD,
    ACTIVITY_CARD_TITLE_SHELL,
    ACTIVITY_PANEL_PADDING,
    CALLOUT_PANEL_PADDING,
    DRAFT_PANEL_ACCENT_STYLE,
    LIVE_PANEL_ACCENT_STYLE,
    TRANSCRIPT_RIGHT_INSET,
    frame_live_body,
    frame_transcript_body,
    gap_below_live_section,
    spacer_live_section,
)
from backend.cli.theme import (
    CLR_AUTONOMY_BALANCED,
    CLR_AUTONOMY_FULL,
    CLR_AUTONOMY_SUPERVISED,
    CLR_BRAND,
    CLR_HUD_DETAIL,
    CLR_HUD_MODEL,
    CLR_META,
    CLR_MUTED_TEXT,
    CLR_SEP,
    CLR_STATE_RUNNING,
    CLR_STATUS_ERR,
    CLR_STATUS_OK,
    CLR_STATUS_WARN,
    CLR_USER_BORDER,
)
from backend.cli.tool_call_display import (
    looks_like_streaming_tool_arguments,
    streaming_args_hint,
    tool_headline,
    try_format_message_as_tool_json,
)
from backend.cli.transcript import (
    format_activity_block,
    format_activity_shell_block,
    format_activity_turn_header,
    format_callout_panel,
    format_ground_truth_tool_line,
    format_reasoning_snapshot,
)
from backend.core.enums import AgentState, EventSource
from backend.ledger import EventStreamSubscriber
from backend.ledger.action import (
    Action,
    NullAction,
    StreamingChunkAction,
)
from backend.ledger.observation import (
    AgentStateChangedObservation,
    NullObservation,
    Observation,
)

logger = logging.getLogger(__name__)



from backend.cli._event_renderer.action_renderers_mixin import ActionRenderersMixin
from backend.cli._event_renderer.observation_renderers_mixin import (
    ObservationRenderersMixin,
)
from backend.cli._event_renderer.constants import (
    THINK_EXTRACT_RE as _THINK_EXTRACT_RE,
    THINK_STRIP_RE as _THINK_STRIP_RE,
)
from backend.cli._event_renderer.error_panel import (
    build_error_panel as _build_error_panel,
    error_guidance as _error_guidance,
    use_recoverable_notice_style as _use_recoverable_notice_style,
)
from backend.cli._event_renderer.panels import (
    PendingActivityCard,
    build_delegate_worker_panel as _build_delegate_worker_panel,
    build_system_notice_panel as _build_system_notice_panel,
    build_task_panel as _build_task_panel,
    delegate_worker_panel_signature as _delegate_worker_panel_signature,
    normalize_system_title as _normalize_system_title,
    task_panel_signature as _task_panel_signature,
)
from backend.cli._event_renderer.text_utils import (
    normalize_reasoning_text as _normalize_reasoning_text,
    reasoning_lines_skip_already_committed as _reasoning_lines_skip_already_committed,
    sanitize_visible_transcript_text as _sanitize_visible_transcript_text,
    show_reasoning_text as _show_reasoning_text,
)

if TYPE_CHECKING:
    from backend.cli.reasoning_display import ReasoningDisplay
    from backend.ledger.stream import EventStream

# Events to silently skip (mirrors gateway filtering).
_SKIP_ACTIONS = (NullAction,)
_SKIP_OBSERVATIONS = (NullObservation,)
_IDLE_STATES = {
    AgentState.AWAITING_USER_INPUT,
    AgentState.FINISHED,
    AgentState.ERROR,
    AgentState.STOPPED,
    AgentState.PAUSED,
    AgentState.REJECTED,
}
# Subscriber ID for the CLI renderer.
_SUBSCRIBER = EventStreamSubscriber.CLI

class CLIEventRenderer(ActionRenderersMixin, ObservationRenderersMixin):
    """Bridges EventStream → live rich layout.

    Activity rows (verb + detail, optional dim stats) are built by
    :func:`backend.cli.transcript.format_activity_block` and related helpers.
    — one line per tool event, no deduplication. Model thoughts use :class:`~backend.cli.reasoning_display.ReasoningDisplay`
    (plain dim text), separate from ground truth.

    Operates in two modes:

    * **Live mode** (during an agent turn): a Rich ``Live`` display shows the
      task strip, streaming preview, reasoning line, and HUD.  Finalized
      transcript lines are ``console.print``ed immediately so they stay in
      scrollback and are not clipped to the terminal height.
    * **Static mode** (idle / prompt): no ``Live`` display.  Output is printed
      once via ``console.print()`` so prompt_toolkit can own the terminal for
      user input without any contention.
    """

    def __init__(
        self,
        console: Console,
        hud: HUDBar,
        reasoning: ReasoningDisplay,
        *,
        loop: asyncio.AbstractEventLoop | None = None,
        max_budget: float | None = None,
        get_prompt_session: Callable[[], Any | None] | None = None,
        cli_tool_icons: bool = True,
    ) -> None:
        self._console = console
        self._hud = hud
        self._reasoning = reasoning
        self._cli_tool_icons = bool(cli_tool_icons)
        self._loop = loop or asyncio.get_event_loop()
        self._get_prompt_session = get_prompt_session
        self._live: Live | None = None
        self._streaming_accumulated = ''
        self._streaming_final = False
        self._current_state: AgentState | None = None
        self._state_event = asyncio.Event()
        self._subscribed = False
        self._max_budget = max_budget
        self._pending_events: deque[Any] = deque()
        self._last_assistant_message_text: str = ''
        self._budget_warned_80 = False
        self._budget_warned_100 = False
        #: Running count of stream-fallback retries this session ("Still Working" panels).
        self._stream_fallback_count: int = 0
        # Per-turn metric snapshots (used to compute deltas at turn completion)
        self._turn_start_cost: float = 0.0
        self._turn_start_tokens: int = 0
        self._turn_start_calls: int = 0
        self._task_panel: Any | None = None
        self._task_panel_signature: tuple[tuple[str, str, str], ...] | None = None
        self._last_printed_task_panel_signature: (
            tuple[tuple[str, str, str], ...] | None
        ) = None
        self._delegate_workers: dict[str, dict[str, Any]] = {}
        self._delegate_batch_id: int | None = None
        self._delegate_panel: Any | None = None
        self._delegate_panel_signature: (
            tuple[tuple[int, str, str, str, str], ...] | None
        ) = None
        self._last_printed_delegate_panel_signature: (
            tuple[tuple[int, str, str, str, str], ...] | None
        ) = None
        #: Last shell command label; paired with :class:`CmdOutputObservation` for one dim result row.
        self._pending_shell_command: str | None = None
        #: Raw input most recently sent via TerminalInputAction (used to strip PTY echo).
        self._last_terminal_input_sent: str = ''
        #: Buffered (verb, label) from CmdRunAction — printed as a combined card on CmdOutputObservation.
        self._pending_shell_action: tuple[str, str] | None = None
        #: Headline for internal shell-backed tool actions (e.g. Analyze project, Search code).
        self._pending_shell_title: str | None = None
        #: True when the buffered shell action is from an internal tool (display_label set).
        #: CmdOutputObservation renders only a brief result line instead of a terminal block.
        self._pending_shell_is_internal: bool = False
        #: Buffered non-shell tool card — printed as a combined card on the matching observation.
        self._pending_activity_card: PendingActivityCard | None = None
        #: First tool/shell row each turn prints a small section marker for scanability.
        self._activity_turn_header_emitted: bool = False
        #: Finish summary text buffered from PlaybookFinishAction; rendered only
        #: once the agent actually reaches AgentState.FINISHED (validation may
        #: block the finish call and keep the agent running).
        self._pending_finish_text: str | None = None
        #: Monotonic timestamp of the last Live refresh (for throttling).
        self._last_refresh_time: float = 0.0
        #: Last reasoning lines committed to transcript (for prefix de-dup per turn).
        self._last_committed_reasoning_lines: list[str] | None = None

    @property
    def current_state(self) -> AgentState | None:
        return self._current_state

    @property
    def streaming_preview(self) -> str:
        return self._streaming_accumulated

    @property
    def budget_warned_80(self) -> bool:
        return self._budget_warned_80

    @property
    def budget_warned_100(self) -> bool:
        return self._budget_warned_100

    @property
    def pending_event_count(self) -> int:
        return len(self._pending_events)

    @property
    def last_assistant_message_text(self) -> str:
        """Most recent committed assistant message rendered in transcript."""
        return self._last_assistant_message_text

    def set_cli_tool_icons(self, enabled: bool) -> None:
        """Toggle emoji tool headlines (e.g. after /settings)."""
        self._cli_tool_icons = bool(enabled)

    # -- Live lifecycle (per agent turn) -----------------------------------

    def start_live(self) -> None:
        """Create and start a Rich Live display for the current agent turn."""
        if self._live is not None:
            return
        live = Live(
            self,
            console=self._console,
            auto_refresh=False,
            transient=True,  # erases on stop — we print final output ourselves
            # ``visible`` causes Rich to re-print overflow content on every
            # refresh when the Live body is taller than the terminal, which
            # makes streaming panels (Draft reply, Thinking) render dozens of
            # duplicate copies per turn. ``crop`` redraws in place; panels
            # that could exceed height (streaming preview, reasoning thoughts)
            # are responsible for clamping themselves to ``options.max_height``.
            vertical_overflow='crop',
        )
        live.start()
        self._live = live
        self.refresh(force=True)

    def stop_live(self) -> None:
        """Stop the Rich Live display."""
        # Flush any remaining thinking before the Live panel disappears.
        self._flush_thinking_block()
        live = self._live
        if live is None:
            try:
                self._console.show_cursor(True)
            except Exception:
                pass
            return
        self._live = None
        if (
            self._task_panel is not None
            and self._task_panel_signature != self._last_printed_task_panel_signature
        ):
            self._console.print(self._task_panel)
            self._last_printed_task_panel_signature = self._task_panel_signature
        if (
            self._delegate_panel is not None
            and self._delegate_panel_signature
            != self._last_printed_delegate_panel_signature
        ):
            self._console.print(self._delegate_panel)
            self._last_printed_delegate_panel_signature = self._delegate_panel_signature
        try:
            live.stop()
        except Exception:
            logger.debug('Live.stop() failed', exc_info=True)
        # Rich usually restores the cursor, but prompt_toolkit may still think the
        # screen layout is pre-Live; force-visible cursor before the next prompt.
        try:
            self._console.show_cursor(True)
        except Exception:
            pass

    # Minimum seconds between non-forced Live refreshes (~20 fps).
    _REFRESH_MIN_INTERVAL: float = 0.05

    def refresh(self, *, force: bool = False) -> None:
        """Redraw the Live display if active.

        When *force* is False the call is throttled so rapid-fire streaming
        tokens do not saturate the terminal with redraws.
        """
        if self._live is None:
            return
        now = time.monotonic()
        if not force and (now - self._last_refresh_time) < self._REFRESH_MIN_INTERVAL:
            return
        self._last_refresh_time = now
        self._live.update(self, refresh=True)

    async def handle_event(self, event: Any) -> None:
        self._process_event_data(event)
        self.refresh(force=True)

    def reset_subscription(self) -> None:
        self._subscribed = False

    @contextmanager
    def suspend_live(self):
        """Stop/start Live around a block (fallback for non-interactive input)."""
        live = self._live
        if live is None:
            yield
            return
        try:
            live.stop()
        except Exception:
            logger.debug('Live.stop() failed during suspend', exc_info=True)
        try:
            yield
        finally:
            try:
                live.start()
            except Exception:
                logger.debug('Live.start() failed during resume', exc_info=True)
            self.refresh()

    def begin_turn(self) -> None:
        """Snapshot metrics and mark the agent as running."""
        self._pending_shell_command = None
        self._pending_shell_action = None
        self._pending_shell_title = None
        self._pending_shell_is_internal = False
        self._pending_activity_card = None
        self._activity_turn_header_emitted = False
        self._last_committed_reasoning_lines = None
        self._current_state = AgentState.RUNNING
        self._hud.update_ledger('Healthy')
        self._hud.update_agent_state('Running')
        self._state_event.clear()
        self._turn_start_cost = self._hud.state.cost_usd
        self._turn_start_tokens = self._hud.state.context_tokens
        self._turn_start_calls = self._hud.state.llm_calls
        self._reasoning.set_cost_baseline(self._hud.state.cost_usd)
        self.refresh()

    async def wait_for_state_change(
        self, wait_timeout_sec: float = 0.25
    ) -> AgentState | None:
        try:
            await asyncio.wait_for(self._state_event.wait(), timeout=wait_timeout_sec)
        except asyncio.TimeoutError:
            return self._current_state
        self._state_event.clear()
        return self._current_state

    def clear_history(self) -> None:
        self._pending_shell_command = None
        self._pending_shell_action = None
        self._pending_shell_title = None
        self._pending_shell_is_internal = False
        self._pending_activity_card = None
        self._activity_turn_header_emitted = False
        self._task_panel = None
        self._task_panel_signature = None
        self._last_printed_task_panel_signature = None
        self._delegate_workers = {}
        self._delegate_batch_id = None
        self._delegate_panel = None
        self._delegate_panel_signature = None
        self._last_printed_delegate_panel_signature = None
        self._last_committed_reasoning_lines = None
        self._clear_streaming_preview()
        self._reasoning.stop()
        self.refresh()

    async def add_user_message(self, text: str) -> None:
        """Print a user turn — rounded panel, high-contrast label."""
        body = Text((text or '').rstrip(), style='default')
        panel = Panel(
            Padding(body, CALLOUT_PANEL_PADDING),
            title=Text('You', style='bold dim'),
            title_align='left',
            box=box.ROUNDED,
            border_style=CLR_USER_BORDER,
            padding=(0, 0),
            style='default',
        )
        framed = frame_transcript_body(panel)
        spacer = frame_transcript_body(Text(''))
        group = Group(spacer, framed, spacer)

        if self._live is not None:
            # Same path as committed transcript lines during a turn: print into
            # scrollback while Live is active, then refresh so the layout stays
            # coherent (printing before Live started could be erased on refresh).
            self._console.print(group)
            self.refresh(force=True)
            return

        sess: Any | None = None
        if self._get_prompt_session is not None:
            try:
                sess = self._get_prompt_session()
            except Exception:
                sess = None
        app = getattr(sess, 'app', None) if sess is not None else None
        if app is not None and getattr(app, 'is_running', False):
            await self._safe_print_above_prompt(group)
            return

        self._console.print(group)

    def add_system_message(self, text: str, *, title: str = 'Info') -> None:
        normalized_title = _normalize_system_title(title)
        lower_title = normalized_title.lower()
        if lower_title == 'error':
            use_notice = _use_recoverable_notice_style(text)
            self._print_or_buffer(
                frame_transcript_body(
                    _build_error_panel(
                        text,
                        title='Error',
                        force_notice=use_notice,
                        content_width=self._console.width,
                    )
                )
            )
            if use_notice:
                self._hud.update_ledger('Idle')
                self._hud.update_agent_state('Ready')
            else:
                self._hud.update_ledger('Error')
            return
        if 'timeout' in lower_title:
            self._print_or_buffer(
                frame_transcript_body(
                    _build_error_panel(
                        text,
                        title=normalized_title,
                        force_notice=True,
                        content_width=self._console.width,
                    )
                )
            )
            self._hud.update_ledger('Idle')
            self._hud.update_agent_state('Ready')
            return
        tone = 'warning' if lower_title == 'warning' else 'info'
        panel = _build_system_notice_panel(
            text,
            title=normalized_title,
            tone=tone,
        )
        self._print_or_buffer(frame_transcript_body(panel))

    def add_markdown_block(self, title: str, text: str) -> None:
        from rich.rule import Rule

        self._print_or_buffer(Text(''))
        self._print_or_buffer(
            Padding(Rule(title, style='dim'), (1, 0, 1, 0), expand=False)
        )
        self._print_or_buffer(Padding(Markdown(text), (0, 0, 1, 0), expand=False))
        self._print_or_buffer(Text(''))

    # -- subscription ------------------------------------------------------

    def subscribe(self, event_stream: EventStream, sid: str) -> None:
        if self._subscribed:
            return
        event_stream.subscribe(_SUBSCRIBER, self._on_event_threadsafe, sid)
        self._subscribed = True

    def _on_event_threadsafe(self, event: Any) -> None:
        """Called from the EventStream's delivery thread pool.

        Appends the event to a thread-safe deque for later processing.
        NO terminal writes happen here — all rendering is done by
        ``drain_events()`` on the main thread.  This avoids two threads
        (delivery pool + Live auto-refresh timer) fighting over stdout.
        """
        self._pending_events.append(event)
        # Wake the main-thread waiter so it drains promptly.
        try:
            self._loop.call_soon_threadsafe(self._state_event.set)
        except RuntimeError:
            pass

    def drain_events(self) -> None:
        """Process all queued events and refresh.

        MUST be called from
        the main thread (the one that owns the Live display).

        Always refreshes even when no events were queued so that
        time-based widgets (e.g. the Thinking… timer) stay up to date.
        """
        while self._pending_events:
            event = self._pending_events.popleft()
            self._process_event_data(event)
        self.refresh(force=True)

    def _process_event_data(self, event: Any) -> None:
        """Update internal state for one event.  Does NOT call refresh()."""
        # Update HUD metrics first so token/cost/call counters advance even if
        # the event itself is later skipped from visual rendering.
        self._update_metrics(event)

        if isinstance(event, _SKIP_ACTIONS) or isinstance(event, _SKIP_OBSERVATIONS):
            return

        source = getattr(event, 'source', None)

        if isinstance(event, Action) and source == EventSource.AGENT:
            self._handle_agent_action(event)
            return

        if isinstance(event, Observation):
            self._handle_observation(event)
            return

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        # During Live: task strip, streaming preview, reasoning, and a fake
        # prompt bar at the bottom so the input area appears to stay visible.
        # Committed transcript lines are printed via console.print immediately
        # so Rich does not clip tall turns (Live vertical_overflow ellipsis).
        live_sections: list[Any] = self._collect_live_sections()
        stream_max_lines, reasoning_max_lines = self._live_section_budgets(options)
        reasoning_section = self._append_streaming_and_reasoning_sections(
            live_sections, stream_max_lines, reasoning_max_lines, options.max_width,
        )
        body_items = self._frame_live_sections(live_sections, reasoning_section)
        if live_sections:
            body_items.append(spacer_live_section())
        # Render a fake prompt bar at the bottom so the input area, stats, and
        # HUD remain visually present while the agent works.
        body_items.append(self._render_fake_prompt(options.max_width))
        yield Group(*body_items)

    def _collect_live_sections(self) -> list[Any]:
        sections: list[Any] = []
        if self._task_panel is not None:
            sections.append(self._task_panel)
        if self._delegate_panel is not None:
            sections.append(self._delegate_panel)
        return sections

    def _live_section_budgets(
        self, options: ConsoleOptions
    ) -> tuple[int | None, int | None]:
        # Split the available vertical budget between the streaming preview
        # and the reasoning panel so neither one grows unbounded and pushes
        # its sibling off-screen (which, with ``vertical_overflow='crop'``,
        # would hide the streamed content entirely).
        #
        # The reserve below accounts for the fake-prompt block at the bottom
        # of the Live display: input row (1) + separator (1) + branded row
        # (1) + stats row (1-2) + padding (~1) = ~6 rows. Previously we
        # reserved 10 rows, which — combined with a very defensive
        # ``max(4, …)`` floor — left as few as 4 physical rows for reasoning
        # content and made long thoughts appear truncated to ~2 lines.
        if not options.max_height:
            return None, None
        available = max(12, options.max_height - 6)
        thought_rows = self._reasoning.live_panel_shows_thought_rows()
        if self._streaming_accumulated and self._reasoning.active:
            return self._budgets_with_both(available, thought_rows)
        if self._streaming_accumulated:
            return max(10, min(28, available)), None
        if self._reasoning.active:
            return None, (max(12, min(32, available)) if thought_rows else 6)
        return None, None

    @staticmethod
    def _budgets_with_both(
        available: int, thought_rows: bool,
    ) -> tuple[int, int]:
        if thought_rows:
            reasoning_share = max(10, available * 3 // 5)
            stream_max = max(6, min(16, available - reasoning_share - 1))
            reasoning_max = max(
                10, min(reasoning_share, available - stream_max - 1)
            )
            return stream_max, reasoning_max
        # Header-only Thinking panel: give the draft-reply preview the bulk.
        return max(10, min(28, available - 5)), 6

    def _append_streaming_and_reasoning_sections(
        self,
        live_sections: list[Any],
        stream_max_lines: int | None,
        reasoning_max_lines: int | None,
        max_width: int,
    ) -> Any | None:
        if self._streaming_accumulated:
            live_sections.append(
                self._render_streaming_preview(
                    max_width=max_width,
                    max_lines=stream_max_lines,
                )
            )
        reasoning_section: Any | None = None
        if self._reasoning.active:
            reasoning_section = self._reasoning.renderable(
                max_width=max_width,
                max_lines=reasoning_max_lines,
            )
            live_sections.append(reasoning_section)
        return reasoning_section

    @staticmethod
    def _frame_live_sections(
        live_sections: list[Any], reasoning_section: Any | None,
    ) -> list[Any]:
        body_items: list[Any] = []
        for index, section in enumerate(live_sections):
            if section is reasoning_section:
                framed = Padding(
                    section,
                    pad=(0, TRANSCRIPT_RIGHT_INSET, 0, 0),
                    expand=False,
                )
            else:
                framed = frame_live_body(section)
            if index < len(live_sections) - 1:
                body_items.append(gap_below_live_section(framed))
            else:
                body_items.append(framed)
        return body_items

    # -- fake prompt (matches prompt_toolkit bottom toolbar) ----------------

    # ``_render_fake_prompt`` shared constants -------------------------------
    _FAKE_PROMPT_BADGE_STYLES: dict[str, str] = {
        'Running': CLR_STATE_RUNNING,
        'Ready': CLR_STATUS_OK + ' bold',
        'Done': CLR_STATUS_OK + ' bold',
        'Finished': CLR_STATUS_OK + ' bold',
        'Needs approval': CLR_STATUS_WARN + ' bold',
        'Needs attention': CLR_STATUS_ERR + ' bold',
        'Stopped': CLR_STATUS_ERR + ' bold',
    }
    _FAKE_PROMPT_LEDGER_OK: frozenset[str] = frozenset(
        {'Healthy', 'Ready', 'Idle', 'Starting'}
    )
    _FAKE_PROMPT_LEDGER_WARN: frozenset[str] = frozenset({'Review', 'Paused'})
    _FAKE_PROMPT_AUTONOMY_STYLES: dict[str, str] = {
        'full': CLR_AUTONOMY_FULL,
        'supervised': CLR_AUTONOMY_SUPERVISED,
    }
    _FAKE_PROMPT_SEP: tuple[str, str] = (' · ', CLR_SEP)
    _FAKE_PROMPT_UNKNOWN_PROVIDERS: frozenset[str] = frozenset(
        {'(not set)', '(unknown)'}
    )

    def _render_fake_prompt(self, width: int) -> Any:
        """Render a prompt look-alike anchored at the bottom of the Live display.

        Visually matches the prompt_toolkit bottom_toolbar so the transition
        between Live (agent executing) and prompt_toolkit (user input) is
        seamless — the input area and stats bar never appear to disappear.
        """
        hud = self._hud.state
        provider, model = HUDBar.describe_model(hud.model)
        items: list[Any] = [
            self._fake_prompt_input_row(hud),
            Text('─' * width, style=CLR_SEP),
        ]
        if width < 72:
            items.append(self._fake_prompt_compact_row(hud, provider, model))
            return Group(*items)
        items.append(self._fake_prompt_row1(hud))
        ws_row = self._fake_prompt_workspace_row(hud, width)
        if ws_row is not None:
            items.append(ws_row)
        items.extend(self._fake_prompt_metrics_rows(hud, provider, model, width))
        return Group(*items)

    @staticmethod
    def _fake_prompt_input_row(hud: Any) -> Any:
        from rich.spinner import Spinner

        state_l = (hud.agent_state_label or 'Running').strip()
        if state_l.lower() == 'running':
            subline = 'Agent working · ctrl+c to interrupt'
            spin_style = CLR_BRAND
        else:
            subline = f'{state_l} · ctrl+c if you need to interrupt'
            spin_style = f'dim {CLR_META}'
        text_style = f'italic {CLR_META}'
        input_row = Table.grid()
        input_row.add_column(width=3)
        input_row.add_column()
        input_row.add_row(
            Spinner('dots', style=spin_style),
            Text(subline, style=text_style),
        )
        return input_row

    @classmethod
    def _fake_prompt_compact_row(
        cls, hud: Any, provider: str, model: str,
    ) -> Text:
        sep = cls._FAKE_PROMPT_SEP
        state_label = hud.agent_state_label or 'Running'
        autonomy = hud.autonomy_level or 'balanced'
        model_short = (
            model
            if provider in cls._FAKE_PROMPT_UNKNOWN_PROVIDERS
            else f'{provider}/{model}'
        )
        ctx = (
            HUDBar._format_tokens(hud.context_tokens)
            if hud.context_tokens > 0
            else '0'
        )
        line = Text()
        first = True
        ws_compact = (hud.workspace_path or '').strip()
        if ws_compact:
            line.append(
                HUDBar.ellipsize_path(ws_compact, 22),
                style=f'dim {CLR_MUTED_TEXT}',
            )
            first = False
        for content in (
            state_label,
            f'autonomy:{autonomy}',
            model_short,
            ctx,
            f'${hud.cost_usd:.4f}',
        ):
            if not first:
                line.append(sep[0], style=sep[1])
            line.append(content, style='dim')
            first = False
        return line

    @classmethod
    def _fake_prompt_row1(cls, hud: Any) -> Text:
        state_label = hud.agent_state_label or 'Running'
        autonomy = hud.autonomy_level or 'balanced'
        row1 = Text()
        row1.append('GRINTA', style=CLR_BRAND)
        row1.append('  ', style='')
        row1.append(
            f' {state_label.upper()} ',
            style=cls._FAKE_PROMPT_BADGE_STYLES.get(
                state_label, CLR_STATUS_OK + ' bold'
            ),
        )
        row1.append('  ', style='')
        auto_style = CLR_AUTONOMY_BALANCED
        for needle, style in cls._FAKE_PROMPT_AUTONOMY_STYLES.items():
            if needle in autonomy:
                auto_style = style
                break
        row1.append(f'autonomy:{autonomy}', style=auto_style)
        return row1

    @staticmethod
    def _fake_prompt_workspace_row(hud: Any, width: int) -> Text | None:
        ws_full = (hud.workspace_path or '').strip()
        if not ws_full:
            return None
        row_ws = Text()
        row_ws.append('workspace ', style=f'dim {CLR_META}')
        row_ws.append(
            HUDBar.ellipsize_path(ws_full, max(28, width - 14)),
            style=CLR_MUTED_TEXT,
        )
        return row_ws

    @classmethod
    def _fake_prompt_token_display(cls, hud: Any) -> str:
        ctx = (
            HUDBar._format_tokens(hud.context_tokens)
            if hud.context_tokens > 0
            else '0'
        )
        if hud.context_tokens == 0 and hud.context_limit == 0:
            return '0 tokens'
        if hud.context_limit == 0:
            return f'{ctx} tokens'
        lim = HUDBar._format_tokens(hud.context_limit) if hud.context_limit else '?'
        return f'{ctx}/{lim}'

    @classmethod
    def _fake_prompt_ledger_style(cls, ledger_status: str) -> str:
        if ledger_status in cls._FAKE_PROMPT_LEDGER_WARN:
            return CLR_STATUS_WARN + ' bold'
        if ledger_status not in cls._FAKE_PROMPT_LEDGER_OK:
            return CLR_STATUS_ERR + ' bold'
        return CLR_STATUS_OK + ' bold'

    def _fake_prompt_metrics_rows(
        self, hud: Any, provider: str, model: str, width: int,
    ) -> list[Text]:
        sep = self._FAKE_PROMPT_SEP
        token_display = self._fake_prompt_token_display(hud)
        mcp_label = HUDBar._format_mcp_servers_label(hud.mcp_servers)
        skills_label = HUDBar._format_skills_label(self._hud.bundled_skill_count)
        ledger_style = self._fake_prompt_ledger_style(hud.ledger_status)
        if provider in self._FAKE_PROMPT_UNKNOWN_PROVIDERS:
            model_display = model
        else:
            model_display = f'{provider}/{model}'
        primary_parts: list[tuple[str, str]] = [
            (model_display, CLR_HUD_MODEL),
            sep,
            (token_display, CLR_HUD_DETAIL),
            sep,
            (f'${hud.cost_usd:.4f}', CLR_HUD_DETAIL),
            sep,
            (hud.ledger_status, ledger_style),
        ]
        optional_parts: list[tuple[str, str]] = [
            (f'{hud.llm_calls} calls', CLR_HUD_DETAIL),
            (mcp_label, CLR_HUD_DETAIL),
            (skills_label, CLR_HUD_DETAIL),
        ]
        parts: list[tuple[str, str]] = list(primary_parts)
        for content, style in optional_parts:
            parts.append(sep)
            parts.append((content, style))
        total_len = sum(len(c) for c, _ in parts)
        if total_len <= width:
            row = Text()
            for content, style in parts:
                row.append(content, style=style)
            return [row]
        # Split: essentials on line 1, optionals on line 2.
        row_a = Text()
        for content, style in primary_parts:
            row_a.append(content, style=style)
        row_b = Text()
        for i, (content, style) in enumerate(optional_parts):
            if i:
                row_b.append(sep[0], style=sep[1])
            row_b.append(content, style=style)
        return [row_a, row_b]

    def _handle_streaming_chunk(self, action: StreamingChunkAction) -> None:
        raw = action.accumulated

        # Tool call argument streaming: spinner + headline only. Do not put partial
        # JSON / command hints into the thinking buffer — those were flushed as dim
        # lines and looked like duplicate ``$ cmd`` reasoning (not LLM thinking).
        if action.is_tool_call:
            self._handle_streaming_tool_call(action)
            return

        # Route <redacted_thinking> content to the reasoning display so the user sees
        # the model's chain-of-thought in real time.
        if looks_like_streaming_tool_arguments(raw):
            self._ensure_reasoning()
            self._reasoning.update_action('Tool…')
            self._streaming_accumulated = ''
            self.refresh()
            return

        # First-class thinking field: if the provider streamed reasoning tokens
        # via the dedicated thinking channel, display them immediately.
        self._absorb_streaming_thinking_field(action)
        # Fallback: extract <redacted_thinking> tags embedded in content text
        # (backward compat for models that embed thinking in the main stream).
        self._absorb_inline_streaming_thinking(raw)

        self._streaming_final = action.is_final
        if action.is_final:
            self._hud.state.llm_calls += 1
        # Always force redraw on streaming updates; throttling here made token
        # output feel delayed vs. the model (refresh() only coalesces to ~20fps).
        self.refresh(force=True)

    def _handle_streaming_tool_call(self, action: StreamingChunkAction) -> None:
        tool_name = action.tool_call_name or 'tool'
        _icon, headline = tool_headline(tool_name, use_icons=self._cli_tool_icons)
        self._ensure_reasoning()
        raw = (action.accumulated or '').strip()
        hint = streaming_args_hint(tool_name, raw)
        if hint:
            self._reasoning.update_action(f'{headline}: {hint}')
        else:
            self._reasoning.update_action(f'{headline}…')
        # Clear any text content that arrived before the tool call started
        # (e.g. a preamble "[" or task-list header). Keeping it would leave
        # a stale "Draft Reply … Still streaming…" panel alongside the
        # Thinking spinner for the entire duration of the tool call stream.
        self._streaming_accumulated = ''
        self.refresh()

    def _absorb_streaming_thinking_field(
        self, action: StreamingChunkAction,
    ) -> None:
        if not (action.thinking_accumulated and _show_reasoning_text()):
            return
        cleaned_thinking = _sanitize_visible_transcript_text(
            action.thinking_accumulated
        )
        if cleaned_thinking:
            self._ensure_reasoning()
            self._reasoning.set_streaming_thought(cleaned_thinking)

    def _absorb_inline_streaming_thinking(self, raw: str) -> None:
        think_match = _THINK_EXTRACT_RE.search(raw)
        if not think_match:
            self._streaming_accumulated = _sanitize_visible_transcript_text(raw)
            return
        thinking_text = _sanitize_visible_transcript_text(think_match.group(1))
        if thinking_text and _show_reasoning_text():
            self._ensure_reasoning()
            self._reasoning.set_streaming_thought(thinking_text)
        # Strip thinking from the streaming preview.
        display_text = _THINK_STRIP_RE.sub('', raw).strip()
        self._streaming_accumulated = _sanitize_visible_transcript_text(
            display_text
        )

    # -- state transitions -------------------------------------------------

    # ``_handle_state_change`` HUD lookup tables --------------------------
    # Mapping of agent state to ``(ledger_status, agent_state_label)``.  States
    # that need bespoke logic (PAUSED collapse, RATE_LIMITED label preservation,
    # RUNNING side-effects) are NOT listed here and are handled out-of-band.
    _STATE_HUD_UPDATES: dict[Any, tuple[str, str]] = {
        # Populated lazily in :meth:`_state_hud_updates`.
    }

    @classmethod
    def _state_hud_updates(cls) -> dict[Any, tuple[str, str]]:
        if cls._STATE_HUD_UPDATES:
            return cls._STATE_HUD_UPDATES
        cls._STATE_HUD_UPDATES = {
            AgentState.ERROR: ('Error', 'Needs attention'),
            AgentState.REJECTED: ('Error', 'Needs attention'),
            AgentState.AWAITING_USER_CONFIRMATION: ('Review', 'Needs approval'),
            AgentState.AWAITING_USER_INPUT: ('Ready', 'Ready'),
            AgentState.FINISHED: ('Idle', 'Done'),
            AgentState.STOPPED: ('Idle', 'Stopped'),
        }
        return cls._STATE_HUD_UPDATES

    def _handle_state_change(self, obs: AgentStateChangedObservation) -> None:
        state = self._coerce_agent_state(obs.agent_state)
        if state is None:
            return
        previous_state = self._current_state
        self._current_state = state
        # Signal waiters on the main event loop (asyncio.Event is not thread-safe).
        try:
            self._loop.call_soon_threadsafe(self._state_event.set)
        except RuntimeError:
            pass
        # PAUSED collapses to STOPPED in CLI — same UX.
        if state == AgentState.PAUSED:
            state = AgentState.STOPPED
            self._current_state = state
        self._apply_state_hud_update(state)
        self._dispatch_state_followup(state, previous_state)

    @staticmethod
    def _coerce_agent_state(state: Any) -> Any:
        if not isinstance(state, str):
            return state
        try:
            return AgentState(state)
        except ValueError:
            logger.debug('Ignoring unknown agent state: %s', state)
            return None

    def _apply_state_hud_update(self, state: Any) -> None:
        update = self._state_hud_updates().get(state)
        if update is not None:
            ledger, label = update
            self._hud.update_ledger(ledger)
            self._hud.update_agent_state(label)
            return
        if state == AgentState.RATE_LIMITED:
            self._hud.update_ledger('Backoff')
            current_label = (self._hud.state.agent_state_label or '').strip()
            if not current_label.startswith(('Auto Retry', 'Retrying')):
                self._hud.update_agent_state('Waiting on recovery')
        elif state == AgentState.RUNNING:
            self._hud.update_ledger('Healthy')
            self._hud.update_agent_state('Running')
            # Finish was blocked — discard the buffered completion text so it
            # never appears while the agent is still working.
            self._pending_finish_text = None

    _STATE_FOLLOWUP_HANDLERS: dict[Any, str] = {
        # Populated lazily in :meth:`_state_followup_handlers`.
    }

    @classmethod
    def _state_followup_handlers(cls) -> dict[Any, str]:
        if cls._STATE_FOLLOWUP_HANDLERS:
            return cls._STATE_FOLLOWUP_HANDLERS
        cls._STATE_FOLLOWUP_HANDLERS = {
            AgentState.AWAITING_USER_CONFIRMATION: '_after_state_awaiting_confirmation',
            AgentState.AWAITING_USER_INPUT: '_after_state_awaiting_input',
            AgentState.FINISHED: '_after_state_finished',
            AgentState.ERROR: '_after_state_error',
            AgentState.REJECTED: '_after_state_error',
            AgentState.STOPPED: '_after_state_stopped',
        }
        return cls._STATE_FOLLOWUP_HANDLERS

    def _dispatch_state_followup(self, state: Any, previous_state: Any) -> None:
        method_name = self._state_followup_handlers().get(state)
        if method_name is not None:
            getattr(self, method_name)(previous_state=previous_state)
            return
        if state in _IDLE_STATES:
            self._stop_reasoning()
        self.refresh()

    def _after_state_awaiting_confirmation(self, *, previous_state: Any) -> None:
        self._flush_pending_tool_cards()
        self._stop_reasoning()
        self._clear_streaming_preview()
        if previous_state != AgentState.AWAITING_USER_CONFIRMATION:
            self._append_history(
                Text(
                    '  approval required — review the pending action.',
                    style='yellow',
                )
            )
        self.refresh()

    def _after_state_awaiting_input(self, *, previous_state: Any) -> None:
        del previous_state
        self._flush_pending_tool_cards()
        self._stop_reasoning()
        self._clear_streaming_preview()
        self.refresh()

    def _after_state_finished(self, *, previous_state: Any) -> None:
        del previous_state
        self._flush_pending_tool_cards()
        self._stop_reasoning()
        self._clear_streaming_preview()
        # Render the finish summary that was buffered when PlaybookFinishAction
        # arrived — we deferred it to here so it only appears when the finish
        # actually went through (not when validation blocks it).
        if self._pending_finish_text:
            self._append_assistant_message(self._pending_finish_text)
            self._pending_finish_text = None

    def _after_state_error(self, *, previous_state: Any) -> None:
        del previous_state
        self._flush_pending_tool_cards()
        self._stop_reasoning()
        self._clear_streaming_preview()
        self._append_history(
            Text('  error — send a follow-up to retry.', style='red dim'),
        )

    def _after_state_stopped(self, *, previous_state: Any) -> None:
        del previous_state
        self._stop_reasoning()
        self._clear_streaming_preview()

    # -- helpers -----------------------------------------------------------

    def _turn_stats_text(self) -> str:
        """Format per-turn token/cost delta as a short summary string."""
        cost_delta = self._hud.state.cost_usd - self._turn_start_cost
        tokens_delta = self._hud.state.context_tokens - self._turn_start_tokens
        calls_delta = self._hud.state.llm_calls - self._turn_start_calls
        parts: list[str] = []
        if tokens_delta > 0:
            parts.append(HUDBar._format_tokens(tokens_delta) + ' tokens')
        if cost_delta > 0.0:
            parts.append(f'${cost_delta:.4f}')
        if calls_delta > 0:
            parts.append(f'{calls_delta} LLM call{"s" if calls_delta != 1 else ""}')
        return '  [' + ' · '.join(parts) + ']' if parts else ''

    def _ensure_reasoning(self) -> None:
        if not self._reasoning.active:
            self._reasoning.start()

    def _append_history(self, renderable: Any) -> None:
        """Add a renderable: buffer during Live, print otherwise."""
        self._print_or_buffer(renderable)

    def _print_or_buffer(self, renderable: Any) -> None:
        """Print transcript output, or schedule above the prompt when idle with PT.

        While Rich ``Live`` is active (agent turn), print each committed line
        through the same console so it lands in normal scrollback and the Live
        region only holds streaming, reasoning, tasks, and HUD — avoiding
        terminal-height clipping.

        When a prompt_toolkit session is active (user at the input prompt), Rich
        ``console.print`` writes at the wrong cursor and corrupts the multiline
        prompt.  In that case schedule ``run_in_terminal`` so output scrolls above
        the prompt.
        """
        framed = frame_transcript_body(renderable)
        if self._live is not None:
            self._console.print(framed)
            self.refresh(force=True)
            return

        sess: Any | None = None
        if self._get_prompt_session is not None:
            try:
                sess = self._get_prompt_session()
            except Exception:
                sess = None
        app = getattr(sess, 'app', None) if sess is not None else None
        if app is not None and getattr(app, 'is_running', False):
            try:
                task = self._loop.create_task(self._safe_print_above_prompt(framed))

                def _log_fail(t: asyncio.Task) -> None:
                    try:
                        t.result()
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        logger.debug(
                            'Safe console print above prompt failed',
                            exc_info=True,
                        )

                task.add_done_callback(_log_fail)
            except RuntimeError:
                self._console.print(framed)
            return

        self._console.print(framed)

    async def _safe_print_above_prompt(self, renderable: Any) -> None:
        from prompt_toolkit.application import run_in_terminal

        def _sync_print() -> None:
            self._console.print(renderable)

        await run_in_terminal(_sync_print)

    def _append_assistant_message(
        self, display_content: str, *, attachments: list[Any] | None = None
    ) -> None:
        """Render a committed assistant message block in the transcript."""
        display_content = _sanitize_visible_transcript_text(display_content)
        if not display_content:
            return
        self._last_assistant_message_text = display_content

        # Render assistant content directly (no "Assistant" header).
        # Keep a small top spacer for readability.
        self._append_history(Text(''))
        tool_lines = try_format_message_as_tool_json(
            display_content, use_icons=self._cli_tool_icons
        )
        if tool_lines is not None:
            _icon, friendly = tool_lines
            for line in friendly.split('\n'):
                self._append_history(Text(line, style=LIVE_PANEL_ACCENT_STYLE))
        else:
            self._append_assistant_body(display_content)
        for attachment in attachments or []:
            self._append_history(attachment)

    def _append_assistant_body(self, display_content: str) -> None:
        """Render the body of an assistant message that isn't a tool JSON."""
        s = display_content.strip()
        if '<search_results>' in s:
            summary = self._summarize_search_results_block(s)
            self._append_history(Text(summary, style=LIVE_PANEL_ACCENT_STYLE))
            return
        plain_summary = self._summarize_plain_match_lines(s)
        if plain_summary is not None:
            self._append_history(Text(plain_summary, style=LIVE_PANEL_ACCENT_STYLE))
            return
        self._append_history(Padding(Markdown(display_content), (0, 0, 1, 0)))

    @staticmethod
    def _summarize_search_results_block(s: str) -> str:
        payload = CLIEventRenderer._search_results_payload(s)
        lines = CLIEventRenderer._search_result_lines(payload)
        if not lines:
            return 'No matches found.'
        if CLIEventRenderer._search_head_says_no_match(lines):
            return 'No matches found.'
        return CLIEventRenderer._format_match_count(lines)

    @staticmethod
    def _search_results_payload(s: str) -> str:
        m = re.search(
            r'<search_results>\s*(?P<payload>.*?)\s*</search_results>', s, re.S
        )
        return m.group('payload') if m else s

    @staticmethod
    def _search_result_lines(payload: str) -> list[str]:
        return [
            ln
            for ln in payload.splitlines()
            if ln.strip() and not ln.startswith('Error running ripgrep:')
        ]

    @staticmethod
    def _search_head_says_no_match(lines: list[str]) -> bool:
        head_blob = '\n'.join(lines[:5])
        return any(
            frag in head_blob for frag in CLIEventRenderer._NO_MATCH_FRAGMENTS
        )

    @staticmethod
    def _format_match_count(lines: list[str]) -> str:
        match_count = sum(
            1 for line in lines if re.match(r'^.*:\\d+:', line)
        ) or len(lines)
        return f'Found {match_count} match{"es" if match_count != 1 else ""}.'

    @staticmethod
    def _summarize_plain_match_lines(s: str) -> str | None:
        plain_lines = [ln for ln in s.splitlines() if ln.strip()]
        if not plain_lines:
            return None
        if not any(re.match(r'^.*:\\d+:', ln) for ln in plain_lines[:5]):
            return None
        match_count = sum(
            1 for line in plain_lines if re.match(r'^.*:\\d+:', line)
        ) or len(plain_lines)
        return f'Found {match_count} match{"es" if match_count != 1 else ""}.'
        self._append_history(Text(''))

    def _emit_activity_turn_header(self) -> None:
        if self._activity_turn_header_emitted:
            return
        self._activity_turn_header_emitted = True
        self._print_or_buffer(Padding(format_activity_turn_header(), pad=(0, 0, 1, 0)))

    def _print_activity(
        self,
        verb: str,
        detail: str,
        stats: str | None = None,
        *,
        shell_rail: bool = False,
        title: str | None = None,
    ) -> None:
        """Primary activity row plus optional dim stats (tool / file / shell)."""
        self._emit_activity_turn_header()  # not a duplicate
        if shell_rail:
            inner = format_activity_shell_block(
                verb,
                detail,
                secondary=stats,
                secondary_kind='neutral',
                title=title,
            )
        else:
            inner = format_activity_block(
                verb, detail, secondary=stats, secondary_kind='neutral', title=title
            )
        self._print_or_buffer(Padding(inner, pad=ACTIVITY_BLOCK_BOTTOM_PAD))

    def _buffer_pending_activity(
        self,
        *,
        title: str,
        verb: str,
        detail: str,
        secondary: str | None = None,
        kind: str = 'generic',
        payload: dict[str, Any] | None = None,
    ) -> None:
        self._flush_pending_activity_card()
        self._pending_activity_card = PendingActivityCard(
            title=title,
            verb=verb,
            detail=detail,
            secondary=secondary,
            kind=kind,
            payload=payload or {},
        )

    def _take_pending_activity_card(
        self, *expected_kinds: str
    ) -> PendingActivityCard | None:
        pending = self._pending_activity_card
        if pending is None:
            return None
        if expected_kinds and pending.kind not in expected_kinds:
            return None
        self._pending_activity_card = None
        return pending

    def _render_pending_activity_card(
        self,
        pending: PendingActivityCard,
        *,
        result_message: str | None = None,
        result_kind: str = 'neutral',
        extra_lines: list[Any] | None = None,
    ) -> None:
        self._emit_activity_turn_header()
        inner = format_activity_block(
            pending.verb,
            pending.detail,
            secondary=pending.secondary,
            secondary_kind='neutral',
            result_message=result_message,
            result_kind=result_kind,
            extra_lines=extra_lines,
            title=pending.title,
        )
        self._print_or_buffer(Padding(inner, pad=ACTIVITY_BLOCK_BOTTOM_PAD))

    def _flush_pending_activity_card(self) -> None:
        pending = self._pending_activity_card
        if pending is None:
            return
        self._pending_activity_card = None
        self._render_pending_activity_card(pending)

    def _flush_pending_tool_cards(self) -> None:
        self._flush_pending_activity_card()
        self._flush_pending_shell_action()

    def _flush_pending_shell_action(self) -> None:
        """Print buffered command card without a result (fallback for orphaned CmdRunActions)."""
        if self._pending_shell_action is None:
            return
        verb, label = self._pending_shell_action
        title = self._pending_shell_title
        is_internal = self._pending_shell_is_internal
        self._pending_shell_action = None
        self._pending_shell_command = None
        self._pending_shell_title = None
        self._pending_shell_is_internal = False
        self._emit_activity_turn_header()  # not a duplicate
        if is_internal:
            inner = format_activity_block(
                verb, label, title=title or ACTIVITY_CARD_TITLE_SHELL
            )
        else:
            inner = format_activity_shell_block(verb, label)
        self._print_or_buffer(Padding(inner, pad=ACTIVITY_BLOCK_BOTTOM_PAD))

    def _print_tool_call(self, label: str) -> None:
        """Emit one legacy ground-truth tool row (``> label``)."""
        self._emit_activity_turn_header()
        self._print_or_buffer(
            Padding(
                format_ground_truth_tool_line(label),
                pad=ACTIVITY_BLOCK_BOTTOM_PAD,
            )
        )

    def _apply_reasoning_text(self, text: str) -> None:
        """Update the reasoning display while keeping tagged tool payloads out of the transcript."""
        action_label, thought = _normalize_reasoning_text(text)
        if action_label is None and thought is None:
            return
        self._ensure_reasoning()
        if action_label:
            self._reasoning.update_action(action_label)
        if thought and _show_reasoning_text():
            self._reasoning.update_thought(thought)

    def _set_task_panel(self, task_list: list[dict[str, Any]]) -> None:
        """Replace the visible task tracker panel with the latest known state."""
        self._task_panel = _build_task_panel(task_list)
        self._task_panel_signature = _task_panel_signature(task_list)
        if (
            self._live is None
            and self._task_panel_signature != self._last_printed_task_panel_signature
        ):
            self._print_or_buffer(self._task_panel)
            self._last_printed_task_panel_signature = self._task_panel_signature

    def _set_delegate_panel(self) -> None:
        """Replace the visible delegated-worker panel with the latest known state."""
        self._delegate_panel = _build_delegate_worker_panel(self._delegate_workers)
        self._delegate_panel_signature = _delegate_worker_panel_signature(
            self._delegate_workers
        )
        if (
            self._live is None
            and self._delegate_panel_signature
            != self._last_printed_delegate_panel_signature
        ):
            self._print_or_buffer(self._delegate_panel)
            self._last_printed_delegate_panel_signature = self._delegate_panel_signature

    def _reset_delegate_panel(self, *, batch_id: int | None) -> None:
        """Start a fresh delegated-worker panel for a new delegation batch."""
        self._delegate_workers = {}
        self._delegate_batch_id = batch_id
        self._delegate_panel = None
        self._delegate_panel_signature = None
        self._last_printed_delegate_panel_signature = None

    def _flush_thinking_block(self) -> None:
        """Print accumulated thoughts as a persistent dim block before they are cleared.

        Called just before _reasoning.stop() so the thought lines are still available.
        Does nothing when no thoughts were collected this turn.
        """
        thoughts = self._reasoning.snapshot_thoughts()
        if not thoughts:
            return
        fresh = _reasoning_lines_skip_already_committed(
            self._last_committed_reasoning_lines,
            thoughts,
        )
        self._last_committed_reasoning_lines = list(thoughts)
        if not fresh:
            return
        self._print_or_buffer(
            Padding(format_reasoning_snapshot(fresh), pad=ACTIVITY_BLOCK_BOTTOM_PAD)
        )

    def _stop_reasoning(self) -> None:
        """Flush any accumulated thoughts to static output, then stop the spinner.

        Always use this instead of calling _reasoning.stop() directly so that
        thoughts are never silently discarded mid-turn or at turn end.
        """
        self._flush_thinking_block()
        self._reasoning.stop()

    def _clear_streaming_preview(self) -> None:
        self._streaming_accumulated = ''
        self._streaming_final = False
        self.refresh()

    @staticmethod
    def _tail_preview_text(
        content: str, *, max_width: int | None, max_lines: int
    ) -> str:
        """Return a bottom-follow viewport of *content* constrained by wrapped lines."""
        if max_lines <= 0 or not content:
            return content

        # Account for panel padding / gutters so wrapping approximates terminal
        # width. 10 = 2 border chars + 4 padding chars (left+right) + 4-char
        # safety margin to leave room for Rich's trailing space on ANSI rows.
        wrap_width = max(20, (max_width or 120) - 10)
        wrapped: list[str] = []
        for raw in content.splitlines() or ['']:
            if not raw:
                wrapped.append('')
                continue
            wrapped.extend(
                textwrap.wrap(
                    raw,
                    width=wrap_width,
                    replace_whitespace=False,
                    drop_whitespace=False,
                )
                or ['']
            )

        if len(wrapped) <= max_lines:
            return content

        tail = wrapped[-max_lines:]
        return '\n'.join(tail)

    def _render_streaming_preview(
        self,
        *,
        max_width: int | None = None,
        max_lines: int | None = None,
    ) -> Any:
        full = self._streaming_accumulated or ''
        clipped = full
        if max_lines is not None:
            clipped = self._tail_preview_text(
                full,
                max_width=max_width,
                max_lines=max_lines,
            )

        body: list[Any] = [Markdown(clipped)]
        if clipped != full:
            body.append(
                Text(
                    'Tail preview — full reply will appear in chat when streaming finishes',
                    style='dim italic',
                )
            )
        if not self._streaming_final:
            body.append(Text('Still streaming…', style='dim'))
        return format_callout_panel(
            'Draft Reply',
            Group(*body),
            accent_style=DRAFT_PANEL_ACCENT_STYLE,
            padding=ACTIVITY_PANEL_PADDING,
        )

    @staticmethod
    def _format_command_display(command: str, *, limit: int = 96) -> str:
        display = ' '.join(command.split())
        if not display:
            return '(empty command)'
        if len(display) > limit:
            return display[: limit - 1] + '…'
        return display

    def _update_metrics(self, event: Any) -> None:
        llm_metrics = getattr(event, 'llm_metrics', None)
        if llm_metrics is not None:
            self._hud.update_from_llm_metrics(llm_metrics)
            self._reasoning.update_cost(self._hud.state.cost_usd)
            self._check_budget()

    def _check_budget(self) -> None:
        if not self._max_budget or self._max_budget <= 0:
            return
        cost = self._hud.state.cost_usd
        if cost >= self._max_budget and not self._budget_warned_100:
            self._budget_warned_100 = True
            self._print_or_buffer(
                Panel(
                    Text(
                        f'Budget limit reached: ${cost:.4f} / ${self._max_budget:.4f}',
                        style='red bold',
                    ),
                    title='[red bold]Budget Exceeded[/red bold]',
                    border_style='red',
                    padding=(1, 2),
                )
            )
        elif cost >= self._max_budget * 0.8 and not self._budget_warned_80:
            self._budget_warned_80 = True
            self._print_or_buffer(
                Panel(
                    Text(
                        f'Approaching budget: ${cost:.4f} / ${self._max_budget:.4f} (80%)',
                        style='yellow',
                    ),
                    title='[yellow]Budget Warning[/yellow]',
                    border_style='yellow',
                    padding=(1, 2),
                )
            )
