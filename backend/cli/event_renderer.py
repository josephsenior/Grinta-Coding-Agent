"""Event stream → terminal renderer.

Subscribes to the backend EventStream and translates events into rich
terminal output.  Handles all three reasoning paths (LLM reasoning,
AgentThinkAction, tool __thought), command output, file edits, errors,
and confirmation flow.
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.live import Live
from rich.text import Text

from backend.cli.hud import HUDBar
from backend.cli.layout_tokens import (
    spacer_live_section,
)
from backend.cli.theme import (
    STYLE_DIM,
    accessible_mode_enabled,
)
from backend.core.enums import AgentState
from backend.ledger import EventStreamSubscriber
from backend.ledger.action import (
    NullAction,
)
from backend.ledger.observation import (
    NullObservation,
)

logger = logging.getLogger(__name__)


from backend.cli._event_renderer.action_renderers_mixin import ActionRenderersMixin
from backend.cli._event_renderer.observation_renderers_mixin import (
    ObservationRenderersMixin,
)
from backend.cli._event_renderer.panels import (
    PendingActivityCard,
)
from backend.cli._event_renderer.sidebar import (
    build_sidebar as _build_sidebar,
)
from backend.cli._event_renderer.sidebar import (
    compute_main_width as _compute_main_width,
)

if TYPE_CHECKING:
    from backend.cli.reasoning_display import ReasoningDisplay

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


from backend.cli._event_renderer._activity_mixin import (
    _EventRendererActivityMixin,  # noqa: F401, E402
)
from backend.cli._event_renderer._live_mixin import (
    _EventRendererLiveMixin,  # noqa: F401, E402
)
from backend.cli._event_renderer._messages_mixin import (
    _EventRendererMessagesMixin,  # noqa: F401, E402
)
from backend.cli._event_renderer._panels_mixin import (
    _EventRendererPanelsMixin,  # noqa: F401, E402
)
from backend.cli._event_renderer._state_mixin import (
    _EventRendererStateMixin,  # noqa: F401, E402
)
from backend.cli._event_renderer._streaming_mixin import (
    _EventRendererStreamingMixin,  # noqa: F401, E402
)
from backend.cli._event_renderer._subscription_mixin import (
    _EventRendererSubscriptionMixin,
)  # noqa: F401, E402


class CLIEventRenderer(
    ActionRenderersMixin,
    ObservationRenderersMixin,
    _EventRendererLiveMixin,
    _EventRendererSubscriptionMixin,
    _EventRendererStateMixin,
    _EventRendererMessagesMixin,
    _EventRendererStreamingMixin,
    _EventRendererActivityMixin,
    _EventRendererPanelsMixin,
):
    @property
    def last_assistant_message_text(self) -> str:
        """Most recent committed assistant message rendered in transcript."""
        return self._last_assistant_message_text

    def set_cli_tool_icons(self, enabled: bool) -> None:
        """Toggle emoji tool headlines (e.g. after /settings)."""
        self._cli_tool_icons = bool(enabled)

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
        self._stream_wrap_width: int | None = None
        self._current_state: AgentState | None = None
        self._state_event = asyncio.Event()
        self._subscribed = False
        self._subscribed_stream: Any = None
        self._max_budget = max_budget
        self._pending_events: deque[Any] = deque(maxlen=10000)
        self._last_assistant_message_text: str = ''
        self._budget_warned_80 = False
        self._budget_warned_100 = False
        #: Running count of stream-fallback retries this session ("Still Working" panels).
        self._stream_fallback_count: int = 0
        self._accessible: bool = accessible_mode_enabled()
        #: Last error observation content printed (used for deduplication).
        self._last_notice_error_content: Any = None
        #: Last retry status signature printed (used for deduplication).
        self._last_retry_status_signature: Any | None = None
        #: Last console dimensions (for resize detection).
        self._last_console_size: tuple[int, int] = (console.width, console.height)
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
        self._pending_finish_renderable: Any | None = None
        #: Monotonic timestamp of the last Live refresh (for throttling).
        self._last_refresh_time: float = 0.0
        #: Last reasoning lines committed to transcript (for prefix de-dup per turn).
        self._last_committed_reasoning_lines: list[str] | None = None
        #: Hash of the last AgentThinkAction rendered to avoid duplicate consecutive cards.
        self._last_think_action_hash: str | None = None

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        # During Live: task strip, streaming preview, reasoning, and a fake
        # prompt bar at the bottom so the input area appears to stay visible.
        # Committed transcript lines are printed via console.print immediately
        # so Rich does not clip tall turns (Live vertical_overflow ellipsis).
        max_width = max(options.max_width or 0, self._console.width)
        if max_width < 20:
            yield Text('Terminal too narrow', style=STYLE_DIM)
            return
        main_width = _compute_main_width(max_width)

        # Build task list from _task_panel_signature for sidebar
        task_list = []
        if self._task_panel_signature:
            for task_id, status, desc in self._task_panel_signature:
                task_list.append({'id': task_id, 'status': status, 'description': desc})

        # Build sidebar if terminal is wide enough
        sidebar = _build_sidebar(
            task_list=task_list,
            mcp_servers=None,
            skill_count=self._hud.bundled_skill_count,
            terminal_width=max_width,
        )

        # Collect main panel content (streaming, reasoning, delegate workers)
        live_sections: list[Any] = self._collect_live_sections()
        self._append_streaming_and_reasoning_sections(
            live_sections,
            None,
            main_width,
        )
        body_items = self._frame_live_sections(live_sections)
        if live_sections:
            body_items.append(spacer_live_section())

        main_content = Group(*body_items)

        fake_prompt = self._render_fake_prompt(main_width)

        if sidebar is not None:
            from rich.columns import Columns

            content_with_hud = Group(main_content, fake_prompt)
            yield Columns([content_with_hud, sidebar])
        else:
            content_with_hud = Group(main_content, fake_prompt)
            yield content_with_hud

    @property
    def budget_warned_80(self) -> bool:
        return self._budget_warned_80

    @property
    def pending_event_count(self) -> int:
        return len(self._pending_events)

    @property
    def streaming_preview(self) -> str:
        return self._streaming_accumulated

    @property
    def current_state(self) -> AgentState | None:
        return self._current_state

    @property
    def budget_warned_100(self) -> bool:
        return self._budget_warned_100
