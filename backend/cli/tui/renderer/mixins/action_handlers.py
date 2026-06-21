"""RendererActionHandlersMixin: action handlers (search/message/streaming/state)."""

from __future__ import annotations

import time
from typing import Any

from backend.cli.event_rendering.text_utils import (
    sanitize_streaming_thinking_text,
    sanitize_visible_transcript_text,
)
from backend.core.enums import (
    AgentState,
    EventSource,
)
from backend.ledger.action import (
    MessageAction,
    StreamingChunkAction,
)


class RendererActionHandlersMixin:
    """action handlers (search/message/streaming/state)."""

    _LIVE_STREAM_PAINT_INTERVAL = 0.033

    def _sync_streaming_mount_mode(self) -> None:
        """Skip transcript mount animations while the LLM stream is active."""
        try:
            display = self._tui._get_display()
        except Exception:
            return
        if type(display).__name__ == 'MagicMock':
            return
        display._suppress_mount_animation = bool(self._streaming_active)

    def flush_live_ui(self, *, terminal: bool = False) -> None:
        """Apply deferred stream paint and optionally finalize live tail widgets."""
        self._stream_paint_timer_armed = False
        deferred = getattr(self, '_deferred_stream_chunk', None)
        self._deferred_stream_chunk = None
        if deferred is not None and not getattr(deferred, 'is_final', False):
            self._last_stream_paint_at = time.monotonic()
            self._apply_streaming_chunk(deferred)

        if not terminal:
            return

        flush_render = getattr(self, '_flush_deferred_streaming_render', None)
        if callable(flush_render):
            flush_render()
        self._streaming_active = False
        self._sync_streaming_mount_mode()
        self._finalize_live_thinking()
        if self._live_response_dirty:
            text = self._normalize_final_response_text(self._live_response)
            if text and text != self._last_final_response_text:
                self._commit_final_response(text)
            else:
                self.clear_live_response()

    @staticmethod
    def _is_user_source(source: Any) -> bool:
        value = getattr(source, 'value', source)
        return str(value or '').strip().lower() == EventSource.USER.value

    @staticmethod
    def _normalize_final_response_text(text: str) -> str:
        return sanitize_visible_transcript_text(text or '').strip()

    @staticmethod
    def _normalize_thinking_text(text: str) -> str:
        return sanitize_streaming_thinking_text(text or '').strip()

    def _commit_final_response(self, text: str) -> None:
        """Commit a final assistant response once, regardless of event shape."""
        content = self._normalize_final_response_text(text)
        self._tui.finalize_thinking()
        self.clear_live_response()
        if not content:
            return
        if content == self._last_final_response_text:
            return
        self._last_final_response_text = content
        self._pending_final_commits.append(content)
        from backend.cli.tui.renderer.drain import _force_immediate_drain

        _force_immediate_drain(self)

    def flush_pending_final_commits_sync(self) -> None:
        if not self._pending_final_commits:
            return
        from backend.cli.tui.widgets.activity_card import AgentMessage

        for content in list(self._pending_final_commits):
            widget = AgentMessage(content)
            self._append_transcript_widget(widget)
            self._history.append(widget)
        self._pending_final_commits.clear()

    async def flush_pending_final_commits(self) -> None:
        if not self._pending_final_commits:
            return
        from backend.cli.tui.widgets.activity_card import AgentMessage

        for content in list(self._pending_final_commits):
            widget = AgentMessage(content)
            self._append_transcript_widget(widget)
            self._history.append(widget)
        self._pending_final_commits.clear()

    def _handle_message_action(self, action: MessageAction) -> None:
        if bool(getattr(action, 'suppress_cli', False)):
            self._tui.finalize_thinking()
            self.clear_live_response()
            return

        thought = (getattr(action, 'thought', '') or '').strip()
        if thought:
            kind = getattr(action, 'kind', '') or ''
            self._render_thinking_payload(thought, finalize=True, kind=kind)

        content = (getattr(action, 'content', '') or '').strip()
        if not content:
            self._tui.finalize_thinking()
            self.clear_live_response()
            return

        if bool(getattr(action, 'protocol_status', False)):
            self._tui.add_protocol_status(content)
            self.clear_live_response()
            return

        if bool(getattr(action, 'transcript_only', False)):
            self._append_plain_agent_message(content)
            return

        self._commit_final_response(content)

    def _append_plain_agent_message(self, text: str) -> None:
        """Show agent preamble before tool calls — no card chrome."""
        content = self._normalize_final_response_text(text)
        self._tui.finalize_thinking()
        self.clear_live_response()
        if not content:
            return
        from backend.cli.tui.widgets.activity_card import AgentMessage

        widget = AgentMessage(content, plain=True)
        self._append_transcript_widget(widget)
        self._history.append(widget)

    @staticmethod
    def _format_retry_status_message(
        status_type: str, extras: dict[str, Any]
    ) -> tuple[str, str, str]:
        attempt = max(1, int(extras.get('attempt') or 1))
        max_attempts = max(attempt, int(extras.get('max_attempts') or attempt))
        reason = str(extras.get('reason') or 'transient failure').strip()
        source = str(extras.get('source') or '').strip().lower()
        retry_target = 'provider stream' if source == 'llm_stream' else 'provider'
        if status_type in ('retry_pending', 'llm_retry_pending'):
            delay_seconds = extras.get('delay_seconds')
            try:
                delay = float(delay_seconds) if delay_seconds is not None else 0.0
            except (TypeError, ValueError):
                delay = 0.0
            delay_str = f'{int(delay)}s' if delay >= 1 else '<1s'
            return (
                f'Backoff {attempt}/{max_attempts} (retrying in {delay_str})',
                f'Waiting {delay_str} to retry after {reason}',
                f'Auto-retrying {retry_target} in {delay_str} ({attempt}/{max_attempts}) after {reason}.',
            )

        return (
            f'Retrying {attempt}/{max_attempts}',
            f'Resuming after {reason}',
            f'Retrying {retry_target} now ({attempt}/{max_attempts}) after {reason}.',
        )

    def _handle_streaming_chunk(self, action: StreamingChunkAction) -> None:
        if action.is_tool_call:
            return

        if action.is_final:
            self._stream_paint_timer_armed = False
            self._deferred_stream_chunk = None
            self._apply_streaming_chunk(action)
            return

        now = time.monotonic()
        last_paint = getattr(self, '_last_stream_paint_at', 0.0)
        if now - last_paint < self._LIVE_STREAM_PAINT_INTERVAL:
            self._deferred_stream_chunk = action
            if not getattr(self, '_stream_paint_timer_armed', False):
                self._stream_paint_timer_armed = True
                delay = max(
                    self._LIVE_STREAM_PAINT_INTERVAL - (now - last_paint),
                    0.01,
                )
                try:
                    self._loop.call_later(delay, self._flush_deferred_stream_chunk)
                except RuntimeError:
                    self._stream_paint_timer_armed = False
                    self._last_stream_paint_at = now
                    self._apply_streaming_chunk(action)
            return

        self._last_stream_paint_at = now
        self._apply_streaming_chunk(action)

    def _flush_deferred_stream_chunk(self) -> None:
        self._stream_paint_timer_armed = False
        action = getattr(self, '_deferred_stream_chunk', None)
        if action is None or action.is_final:
            return
        self._deferred_stream_chunk = None
        self._last_stream_paint_at = time.monotonic()
        self._apply_streaming_chunk(action)

    def _apply_streaming_chunk(self, action: StreamingChunkAction) -> None:
        self._streaming_active = not action.is_final
        self._sync_streaming_mount_mode()

        thinking = self._normalize_thinking_text(action.thinking_accumulated or '')
        content = self._normalize_final_response_text(action.accumulated or '')

        self._debug_log_thinking_chunk(thinking)

        if self._is_visible_thinking_text(thinking):
            self._render_thinking_payload(thinking)
            if action.is_final:
                self._finalize_live_thinking()
        elif action.is_final:
            self._finalize_live_thinking()

        if action.is_final:
            self._finalize_streaming_response(action, content)
            return

        if content:
            self.update_live_response(content)

    def _debug_log_thinking_chunk(self, thinking: str) -> None:
        if not thinking:
            return
        _chunk_n = getattr(self, '_dbg_chunk_n', 0) + 1
        self._dbg_chunk_n = _chunk_n
        if _chunk_n % 5 == 1:
            import logging as _logging

            _log = _logging.getLogger(__name__)
            _log.info(
                '[streaming-dbg] chunk=%d thinking_accumulated len=%d head=%r tail=%r',
                _chunk_n,
                len(thinking),
                thinking[:80],
                thinking[-80:],
            )

    def _finalize_streaming_response(
        self, action: StreamingChunkAction, content: str
    ) -> None:
        if bool(getattr(action, 'suppress_live_response', False)):
            self.clear_live_response()
            return
        final_text = content or self._live_response
        if final_text:
            self._commit_final_response(final_text)
        else:
            self.clear_live_response()

    def _update_metrics(self, event: Any) -> None:
        changed = False
        if hasattr(event, 'model') and event.model:
            self._hud.update_model(event.model)
            changed = True
        if hasattr(event, 'llm_metrics') and event.llm_metrics:
            self._hud.update_from_llm_metrics(event.llm_metrics)
            changed = True
        cost = getattr(event, 'cost_usd', None)
        if cost is not None and cost > 0:
            self._hud.update_cost(self._hud.state.cost_usd + cost)
            changed = True
        if changed:
            self._tui._render_hud_bar()

    def _handle_state_change(self, obs: Any) -> None:
        state = obs.agent_state
        try:
            state = AgentState(state)
        except (ValueError, TypeError):
            pass

        self._current_state = state
        if state in (
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.STOPPED,
        ):
            self._streaming_active = False
            self.flush_live_ui(terminal=True)

        current_label = (self._hud.state.agent_state_label or '').strip()
        if state == AgentState.RATE_LIMITED:
            self._hud.update_ledger('Backoff')
            if not current_label.startswith(('Backoff', 'Retrying')):
                self._hud.update_agent_state('Rate Limited')
                current_label = 'Rate Limited'
            self._tui.set_agent_phase(current_label)
        else:
            self._clear_retry_strip('Idle')
            if state not in (AgentState.ERROR,):
                self._clear_runtime_strip('Idle')
            self._hud.update_agent_state(str(state))
            self._tui.set_agent_phase(str(state))

        self._maybe_end_agent_turn(state)
        self._state_event.set()
        self._tui._render_hud_bar()

    def _maybe_end_agent_turn(self, state: Any) -> None:
        if self._in_agent_turn and state in (
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.STOPPED,
        ):
            self._in_agent_turn = False
            if self._tools_in_turn > 0:
                elapsed = time.monotonic() - self._turn_start_time
                self._tui._last_turn_duration = self._format_turn_duration(
                    int(elapsed)
                )
            else:
                self._tui._last_turn_duration = None

        if state in (AgentState.FINISHED, AgentState.ERROR, AgentState.STOPPED):
            self._tui._agent_running = False

    @staticmethod
    def _format_turn_duration(total_seconds: int) -> str:
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f'{hours}h {minutes}m {seconds}s'
        elif minutes > 0:
            return f'{minutes}m {seconds}s'
        return f'{seconds}s'
