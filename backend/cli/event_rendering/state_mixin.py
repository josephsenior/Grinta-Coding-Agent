"""State methods for CLIEventRenderer.

Agent state changes & HUD updates (handle_state_change/_after_state_*/_turn_stats_text).

Extracted from backend/cli/event_renderer.py to keep the parent module
under the per-file LOC budget. All methods rely on attributes/methods
defined on CLIEventRenderer; this mixin is meant to be combined with
that class via multiple inheritance.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from rich.text import Text

from backend.cli.display.hud import HUDBar
from backend.cli.theme import (
    CLR_ERR_BODY,
    CLR_WARN_BODY,
)
from backend.core.enums import AgentState
from backend.ledger.observation import (
    AgentStateChangedObservation,
)

if TYPE_CHECKING:
    from backend.cli.event_renderer import CLIEventRenderer


logger = logging.getLogger(__name__)

from backend.cli.event_rendering.renderer_constants import (  # noqa: E402
    IDLE_STATES as _IDLE_STATES,
)


class StateMixin(CLIEventRenderer if TYPE_CHECKING else object):
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
