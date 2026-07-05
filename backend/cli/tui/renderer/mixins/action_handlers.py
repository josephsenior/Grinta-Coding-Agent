"""RendererActionHandlersMixin: action handlers (search/message/streaming/state)."""

from __future__ import annotations

import time
from typing import Any

from backend.cli.display.hud import HUDBar
from backend.cli.tui.constants import _TUI_STREAM_PAINT_INTERVAL_SECONDS
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

    _LIVE_STREAM_PAINT_INTERVAL = _TUI_STREAM_PAINT_INTERVAL_SECONDS

    def _sync_streaming_mount_mode(self) -> None:
        """Skip transcript mount animations while the LLM stream is active."""
        try:
            display = self._tui._get_display()
        except Exception:
            return
        is_mock = getattr(self, '_display_is_mock', None)
        if callable(is_mock) and is_mock():
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
        if self._live_response_dirty and not self._step_draft.content_committed:
            text = self._normalize_final_response_text(self._live_response)
            if text:
                self._commit_final_response(text)
            else:
                self.clear_live_response()
        elif self._live_response_dirty:
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
        """Commit a final assistant response once via ``MessageAction`` semantics."""
        content = self._normalize_final_response_text(text)
        self._tui.finalize_thinking()
        self.clear_live_response()
        if not content:
            return
        if not self._step_draft.should_commit_content(content):
            return
        self._step_draft.note_content_committed(content)
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
            self._append_history_items(widget)
        self._pending_final_commits.clear()

    async def flush_pending_final_commits(self) -> None:
        if not self._pending_final_commits:
            return
        from backend.cli.tui.widgets.activity_card import AgentMessage

        for content in list(self._pending_final_commits):
            widget = AgentMessage(content)
            self._append_transcript_widget(widget)
            self._append_history_items(widget)
        self._pending_final_commits.clear()

    def _handle_message_action(self, action: MessageAction) -> None:
        if bool(getattr(action, 'suppress_cli', False)):
            self._tui.finalize_thinking()
            self.clear_live_response()
            return

        content = (getattr(action, 'content', '') or '').strip()
        normalized_content = (
            self._normalize_final_response_text(content) if content else ''
        )

        thought = (getattr(action, 'thought', '') or '').strip()
        if thought and self._step_draft.should_render_thought():
            kind = getattr(action, 'kind', '') or ''
            self._render_thinking_payload(thought, finalize=True, kind=kind)

        if not content:
            self._tui.finalize_thinking()
            self.clear_live_response()
            return

        if bool(getattr(action, 'protocol_status', False)):
            self._tui.add_protocol_status(content)
            self.clear_live_response()
            return

        if bool(getattr(action, 'transcript_only', False)):
            if not self._step_draft.should_commit_content(
                normalized_content, transcript_only=True
            ):
                self._tui.finalize_thinking()
                self.clear_live_response()
                return
            self._append_plain_agent_message(content)
            if normalized_content:
                self._step_draft.note_content_committed(
                    normalized_content, transcript_only=True
                )
                self._last_streamed_preamble_text = normalized_content
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
        self._append_history_items(widget)

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

        # Compaction summary chunks: route to the pending CompactionCard so
        # the summary text appears in real time on the detail screen.
        if getattr(action, 'tool_call_name', '') == 'compaction':
            self._stream_to_compaction_card(action)
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

    def _stream_to_compaction_card(self, action: StreamingChunkAction) -> None:
        """Update the pending compaction scan card with a streamed chunk.

        Streaming chunks are preview-only. The card is completed when
        ``CondensationAction`` commits — not on each LLM stream ``is_final``,
        because sanity-gate retries emit multiple finals during one compaction.
        """
        card = self._resolve_running_compaction_card()
        text = (action.accumulated or action.chunk or '').strip()

        if card is None:
            return

        if text:
            update = getattr(card, 'update_summary_streaming', None)
            if callable(update):
                update(text)
            elif hasattr(card, 'summary'):
                card.summary = text
                if hasattr(card, '_refresh_line'):
                    card._refresh_line()

    def _flush_deferred_stream_chunk(self) -> None:
        self._stream_paint_timer_armed = False
        action = getattr(self, '_deferred_stream_chunk', None)
        if action is None or action.is_final:
            return
        self._deferred_stream_chunk = None
        self._last_stream_paint_at = time.monotonic()
        self._apply_streaming_chunk(action)

    def _apply_streaming_chunk(self, action: StreamingChunkAction) -> None:
        content = self._normalize_final_response_text(action.accumulated or '')

        if not self._step_draft.accept_stream_preview(
            is_final=action.is_final,
            incoming=content,
        ):
            return

        self._streaming_active = not action.is_final
        self._sync_streaming_mount_mode()

        thinking = self._normalize_thinking_text(action.thinking_accumulated or '')

        self._debug_log_thinking_chunk(thinking)

        if self._is_visible_thinking_text(thinking):
            self._render_thinking_payload(thinking)
            if action.is_final:
                self._finalize_live_thinking()
        elif action.is_final:
            self._finalize_live_thinking()

        if action.is_final:
            if content and not bool(getattr(action, 'suppress_live_response', False)):
                self._step_draft.set_preview_content(content)
                self.update_live_response(content)
            self._finalize_streaming_response(action, content)
            return

        if content:
            self._step_draft.set_preview_content(content)
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
            # Tool-step finals: keep the live preview until transcript_only
            # MessageAction commits the canonical full text.
            return
        # Streams are preview-only; MessageAction commits permanent rows.
        preview = content or self._normalize_final_response_text(self._live_response)
        if preview:
            self._step_draft.set_preview_content(preview)

    def _update_metrics(self, event: Any) -> None:
        changed = False
        if hasattr(event, 'model') and event.model:
            self._hud.update_model(event.model)
            changed = True
        if hasattr(event, 'llm_metrics') and event.llm_metrics:
            self._hud.update_from_llm_metrics(event.llm_metrics)
            self._apply_hud_prompt_token_accounting()
            changed = True
        cost = getattr(event, 'cost_usd', None)
        if cost is not None and cost > 0:
            self._hud.update_cost(self._hud.state.cost_usd + cost)
            changed = True
        if changed:
            self._tui._render_hud_bar()

    def _apply_hud_prompt_token_accounting(self) -> None:
        controller = getattr(self._tui, '_controller', None)
        if controller is None:
            return
        state = getattr(controller, 'state', None)
        extra = getattr(state, 'extra_data', None) if state is not None else None
        accounting = HUDBar._prompt_token_accounting_from_extra(extra)
        if accounting:
            self._hud.apply_prompt_token_accounting(accounting)

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

        self._maybe_start_agent_turn(state)
        self._maybe_end_agent_turn(state)
        self._state_event.set()
        self._tui._render_hud_bar()

    def _maybe_start_agent_turn(self, state: Any) -> None:
        if self._in_agent_turn or state != AgentState.RUNNING:
            return
        self._in_agent_turn = True
        self._turn_count += 1
        self._tools_in_turn = 0
        self._turn_start_time = time.monotonic()
        self._tui._last_turn_duration = None

    def _maybe_end_agent_turn(self, state: Any) -> None:
        if self._in_agent_turn and state in (
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.STOPPED,
        ):
            self._in_agent_turn = False
            elapsed = time.monotonic() - self._turn_start_time
            self._tui._last_turn_duration = self._format_turn_duration(int(elapsed))

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
