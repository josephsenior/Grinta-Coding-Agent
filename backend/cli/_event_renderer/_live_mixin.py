"""Live methods for CLIEventRenderer.

Live display lifecycle (start/stop/refresh/suspend/begin/clear/wait).

Extracted from backend/cli/event_renderer.py to keep the parent module
under the per-file LOC budget. All methods rely on attributes/methods
defined on CLIEventRenderer; this mixin is meant to be combined with
that class via multiple inheritance.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from rich import box
from rich.console import Console, ConsoleOptions, Group, RenderResult
from rich.live import Live
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.style import Style
from rich.text import Text

from backend.cli._event_renderer.constants import (
    THINK_EXTRACT_RE as _THINK_EXTRACT_RE,
)
from backend.cli._event_renderer.constants import (
    THINK_STRIP_RE as _THINK_STRIP_RE,
)
from backend.cli._event_renderer.error_panel import (
    build_error_panel as _build_error_panel,
)
from backend.cli._event_renderer.error_panel import (
    use_recoverable_notice_style as _use_recoverable_notice_style,
)
from backend.cli._event_renderer.panels import (
    PendingActivityCard,
)
from backend.cli._event_renderer.panels import (
    build_delegate_worker_panel as _build_delegate_worker_panel,
)
from backend.cli._event_renderer.panels import (
    build_system_notice_panel as _build_system_notice_panel,
)
from backend.cli._event_renderer.panels import (
    build_task_panel as _build_task_panel,
)
from backend.cli._event_renderer.panels import (
    delegate_worker_panel_signature as _delegate_worker_panel_signature,
)
from backend.cli._event_renderer.panels import (
    normalize_system_title as _normalize_system_title,
)
from backend.cli._event_renderer.panels import (
    task_panel_signature as _task_panel_signature,
)
from backend.cli._event_renderer.sidebar import (
    build_sidebar as _build_sidebar,
)
from backend.cli._event_renderer.sidebar import (
    compute_main_width as _compute_main_width,
)
from backend.cli._event_renderer.text_utils import (
    normalize_reasoning_text as _normalize_reasoning_text,
)
from backend.cli._event_renderer.text_utils import (
    sanitize_visible_transcript_text as _sanitize_visible_transcript_text,
)
from backend.cli._event_renderer.text_utils import (
    show_reasoning_text as _show_reasoning_text,
)
from backend.cli.hud import HUDBar
from backend.cli.layout_tokens import (
    ACTIVITY_BLOCK_BOTTOM_PAD,
    ACTIVITY_CARD_TITLE_SHELL,
    CALLOUT_PANEL_PADDING,
    LIVE_PANEL_ACCENT_STYLE,
    frame_live_body,
    frame_transcript_body,
    gap_below_live_section,
    spacer_live_section,
)
from backend.cli.path_links import file_uri_for_path, linkify_plain
from backend.cli.status_chrome import rich_fake_prompt_group, status_fields_from_hud
from backend.cli.theme import (
    CLR_ERR_BODY,
    CLR_ERR_ICON,
    CLR_STATUS_ERR,
    CLR_STATUS_WARN,
    CLR_USER_BG,
    CLR_USER_BORDER,
    CLR_WARN_BODY,
    CLR_WARN_ICON,
    STYLE_BOLD_DIM,
    STYLE_DIM,
    accessible_mode_enabled,
    get_grinta_pygments_style,
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
    format_ground_truth_tool_line,
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

if TYPE_CHECKING:
    from backend.cli.event_renderer import CLIEventRenderer


logger = logging.getLogger(__name__)

class _EventRendererLiveMixin(CLIEventRenderer if TYPE_CHECKING else object):
    """Mixin class — see module docstring."""

    def start_live(self) -> None:
        """Create and start a Rich Live display for the current agent turn.

        In accessible mode no Live display is created — output is printed
        directly instead.
        """
        self.drain_events()
        if self._accessible:
            return
        if self._live is not None:
            return
        live = Live(
            self,
            console=self._console,
            auto_refresh=False,
            transient=True,  # erases on stop — we print final output ourselves
            # Use 'scroll' for better viewport management when content exceeds
            # terminal height. This prevents the visual mess where old content
            # overlaps with new.
            vertical_overflow='scroll',  # type: ignore[arg-type]
        )
        live.start()
        self._live = live
        self.refresh(force=True)
    def stop_live(self) -> None:
        """Stop the Rich Live display.

        In accessible mode, flush output directly instead.
        """
        # Process any last events while Live is still active so they land
        # in the console scrollback immediately (avoiding run_in_terminal delay).
        self.drain_events()

        # In accessible mode, flush pending output directly.
        if self._accessible:
            self._flush_thinking_block()
            self._console.print()
            try:
                self._console.show_cursor(True)
            except Exception:
                pass
            return
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
        # Task panel is now shown in sidebar - no need to print separately
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
    _REFRESH_MIN_INTERVAL: float = 0.05
    def refresh(self, *, force: bool = False) -> None:
        """Redraw the Live display if active.

        In accessible mode, flush pending events and return immediately.

        When *force* is False the call is throttled so rapid-fire streaming
        tokens do not saturate the terminal with redraws.

        However, when content exceeds terminal height and needs scrolling,
        we skip throttle to ensure the viewport updates properly.
        """
        if self._accessible:
            self.drain_events()
            return
        if self._live is None:
            return
        now = time.monotonic()
        has_streaming_content = bool(self._streaming_accumulated)
        if (
            not force
            and not has_streaming_content
            and (now - self._last_refresh_time) < self._REFRESH_MIN_INTERVAL
        ):
            return
        self._last_refresh_time = now
        current_size = (self._console.width, self._console.height)
        if current_size != self._last_console_size:
            self._last_console_size = current_size
            force = True
        try:
            self._live.update(self, refresh=force)
        except Exception:
            logger.debug('Live.update() failed', exc_info=True)
    @contextmanager
    def suspend_live(self):
        """Stop/start Live around a block (fallback for non-interactive input)."""
        if self._accessible:
            yield
            return
        live = self._live
        if live is None:
            yield
            return
        was_active = True
        try:
            live.stop()
        except Exception:
            logger.debug('Live.stop() failed during suspend', exc_info=True)
            was_active = False
        self._live = None
        try:
            yield
        finally:
            if was_active and self._live is None:
                try:
                    live.start()
                    self._live = live
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
        if self._pending_events:
            return self._current_state
        try:
            await asyncio.wait_for(self._state_event.wait(), timeout=wait_timeout_sec)
        except asyncio.TimeoutError:
            return self._current_state
        if not self._pending_events:
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
