"""State methods for CLIEventRenderer.

Agent state changes & HUD updates (handle_state_change/_after_state_*/_turn_stats_text).

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

from backend.cli.event_renderer import _IDLE_STATES  # noqa: F401, E402

class _EventRendererStateMixin(CLIEventRenderer if TYPE_CHECKING else object):
    """Mixin class — see module docstring."""

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
            if not current_label.startswith(('Backoff', 'Retrying')):
                self._hud.update_agent_state('Waiting on recovery')
        elif state == AgentState.RUNNING:
            self._hud.update_ledger('Healthy')
            self._hud.update_agent_state('Running')
            # Finish was blocked — discard the buffered completion text so it
            # never appears while the agent is still working.
            self._pending_finish_text = None
            self._pending_finish_renderable = None
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
                    style=CLR_WARN_BODY,
                )
            )
        self.refresh()
    def _after_state_awaiting_input(self, *, previous_state: Any) -> None:
        del previous_state
        self._flush_pending_tool_cards()
        self._clear_streaming_preview()
        self.refresh()
    def _after_state_finished(self, *, previous_state: Any) -> None:
        del previous_state
        self._flush_pending_tool_cards()
        self._clear_streaming_preview()
        # Render the finish summary that was buffered when PlaybookFinishAction
        # arrived — we deferred it to here so it only appears when the finish
        # actually went through (not when validation blocks it).
        if self._pending_finish_renderable is not None:
            self._append_history(Text(''))
            self._append_history(self._pending_finish_renderable)
            self._pending_finish_renderable = None
            self._pending_finish_text = None
        elif self._pending_finish_text:
            self._append_assistant_message(self._pending_finish_text)
            self._pending_finish_text = None
    def _after_state_error(self, *, previous_state: Any) -> None:
        del previous_state
        self._flush_pending_tool_cards()
        self._stop_reasoning()
        self._clear_streaming_preview()
        self._append_history(
            Text(
                '  error - use /retry to resend the last message, or send a new instruction.',
                style=f'dim {CLR_ERR_BODY}',
            ),
        )
    def _after_state_stopped(self, *, previous_state: Any) -> None:
        del previous_state
        self._stop_reasoning()
        self._streaming_accumulated = ''
        self._reasoning._streaming_line = ''
        self._reasoning._committed_lines.clear()
        self._clear_streaming_preview()
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
