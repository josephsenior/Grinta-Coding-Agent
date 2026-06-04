from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from backend.context import ContextMemory
from backend.context.compactor import Compactor
from backend.context.pre_condensation_snapshot import (
    commit_snapshot,
    delete_snapshot,
    extract_snapshot,
    format_snapshot_for_injection,
    load_snapshot,
    save_snapshot,
)
from backend.context.prompt_window import select_prompt_events
from backend.context.view import View
from backend.core.logger import app_logger as logger
from backend.core.message import Message, TextContent
from backend.inference.prompt_caching import model_supports_prompt_cache_hints
from backend.ledger.action import MessageAction
from backend.ledger.action.agent import CondensationAction

if TYPE_CHECKING:
    from backend.core.config import AgentConfig
    from backend.core.contracts.state import State
    from backend.inference.llm_registry import LLMRegistry
    from backend.ledger.action import Action
    from backend.ledger.event import Event
    from backend.utils.prompt import PromptManager


@dataclass
class CondensedHistory:
    events: list[Event]
    pending_action: Action | None


_MIN_HISTORY_EVENTS_FOR_FORCED_COMPACTION = 30


class ContextMemoryManager:
    """Owns context memory and condensation."""

    def __init__(
        self,
        config: AgentConfig,
        llm_registry: LLMRegistry,
    ) -> None:
        self._config = config
        self._llm_registry = llm_registry
        self.conversation_memory: ContextMemory | None = None
        self.compactor: Compactor | None = None

    def initialize(self, prompt_manager: PromptManager) -> None:
        """Initialize context memory with prompt manager."""
        self.conversation_memory = ContextMemory(self._config, prompt_manager)
        # Initialize compactor from config if available
        compactor_config = getattr(self._config, 'compactor_config', None)
        self._init_compactor(compactor_config)

    def _init_compactor(self, compactor_config) -> None:
        """Initialize the compactor from config."""
        if compactor_config is None:
            self.compactor = None
            return

        try:
            self.compactor = Compactor.from_config(
                compactor_config,
                self._llm_registry,
            )
            logger.debug('Using compactor: %s', type(self.compactor))
        except Exception as exc:  # pragma: no cover - condensation optional
            logger.warning('Failed to initialize compactor: %s', exc)
            self.compactor = None

    # --------------------------------------------------------------------- #
    # History utilities
    # --------------------------------------------------------------------- #
    @staticmethod
    def _memory_pressure_signal(state: State) -> str | None:
        turn_signals = getattr(state, 'turn_signals', None)
        memory_pressure = getattr(turn_signals, 'memory_pressure', None)
        if isinstance(memory_pressure, str) and memory_pressure.strip():
            return memory_pressure
        return None

    @staticmethod
    def _has_unhandled_condensation_request(state: State) -> bool:
        view = getattr(state, 'view', None)
        flag = getattr(view, 'unhandled_condensation_request', False)
        return flag if isinstance(flag, bool) else False

    @staticmethod
    def _is_noop_condensation_action(action: object | None) -> bool:
        if not isinstance(action, CondensationAction):
            return False
        if action.summary is not None:
            return False
        return len(action.pruned) == 0

    def should_emit_compaction_status(self, state: State) -> bool:
        """Return True when foreground condensation is likely to emit an action."""
        if not self.compactor:
            return False
        history = list(getattr(state, 'history', []))
        turn_signals = getattr(state, 'turn_signals', None)
        if getattr(turn_signals, 'prewarmed_compaction', None) is not None:
            return True
        if self._has_unhandled_condensation_request(state):
            return True
        if (
            self._memory_pressure_signal(state)
            and len(history) >= _MIN_HISTORY_EVENTS_FOR_FORCED_COMPACTION
        ):
            return True

        view = getattr(state, 'view', None)
        if view is None:
            return False

        predictor = getattr(self.compactor, 'should_emit_compaction_status', None)
        if callable(predictor):
            try:
                return bool(predictor(view))
            except Exception:
                logger.debug('Compaction status prediction failed', exc_info=True)
                return False

        from backend.context.compactor.compactor import RollingCompactor

        if isinstance(self.compactor, RollingCompactor):
            try:
                return bool(self.compactor.should_compact(view))
            except Exception:
                logger.debug(
                    'Rolling compactor status prediction failed', exc_info=True
                )
        return False

    async def _maybe_force_compaction_under_memory_pressure(
        self,
        state: State,
        history: list,
        condensation_result: View | object,
    ) -> object:
        """When memory pressure is active and compaction returned a plain View, try forced compaction."""
        memory_pressure = self._memory_pressure_signal(state)
        if not memory_pressure or not isinstance(condensation_result, View):
            return condensation_result

        from backend.context.compactor.compactor import RollingCompactor

        if len(history) < _MIN_HISTORY_EVENTS_FOR_FORCED_COMPACTION:
            logger.info(
                'Memory pressure %s: skipping forced compaction for short history (%d events)',
                memory_pressure,
                len(history),
            )
        elif isinstance(self.compactor, RollingCompactor):
            logger.info(
                'Memory pressure %s: forcing compaction',
                memory_pressure,
            )
            try:
                forced = await self.compactor.get_compaction(condensation_result)
                condensation_result = forced
            except Exception as exc:
                logger.warning('Forced compaction failed: %s', exc)
        state.ack_memory_pressure(source='ContextMemoryManager')
        return condensation_result

    async def _maybe_force_compaction_for_explicit_request(
        self,
        state: State,
        condensation_result: View | object,
    ) -> object:
        """Honor an explicit condensation request even if normal thresholds do not fire."""
        if not self._has_unhandled_condensation_request(state) or not isinstance(
            condensation_result, View
        ):
            return condensation_result

        from backend.context.compactor.compactor import RollingCompactor

        if not isinstance(self.compactor, RollingCompactor):
            return condensation_result

        logger.info('Explicit condensation request: forcing compaction')
        try:
            return await self.compactor.get_compaction(condensation_result)
        except Exception as exc:
            logger.warning('Explicit-request compaction failed: %s', exc)
            return condensation_result

    async def condense_history(self, state: State) -> CondensedHistory:
        started = time.perf_counter()
        history = list(getattr(state, 'history', []))
        if not self.compactor:
            logger.debug(
                'ContextMemoryManager.condense_history skipped: no compactor '
                '(history_events=%d elapsed=%.3fs)',
                len(history),
                time.perf_counter() - started,
            )
            return CondensedHistory(history, None)

        # Auto-extract critical context before compaction may discard events
        snapshot_started = time.perf_counter()
        self._extract_pre_condensation_snapshot(state, history)
        snapshot_elapsed = time.perf_counter() - snapshot_started

        # Check if we have a pre-warmed condensation from the background task
        turn_signals = getattr(state, 'turn_signals', None)
        prewarmed = getattr(turn_signals, 'prewarmed_compaction', None)
        if prewarmed is not None:
            turn_signals.prewarmed_compaction = None  # type: ignore[union-attr]
            logger.info('Utilizing background pre-warmed condensation result.')
            condensation_result = prewarmed

            # Tag the CondensationAction to identify it as prewarmed
            action = getattr(condensation_result, 'action', None)
            if action:
                action.is_prewarmed = True
        else:
            compaction_started = time.perf_counter()
            condensation_result = await self.compactor.compacted_history(state)
            logger.info(
                'ContextMemoryManager.condense_history compactor returned %s '
                '(history_events=%d snapshot=%.3fs compactor=%.3fs)',
                type(condensation_result).__name__,
                len(history),
                snapshot_elapsed,
                time.perf_counter() - compaction_started,
            )

        postprocess_started = time.perf_counter()
        condensation_result = (
            await self._maybe_force_compaction_for_explicit_request(
                state, condensation_result
            )
        )
        condensation_result = await self._maybe_force_compaction_under_memory_pressure(  # type: ignore[assignment]
            state, history, condensation_result
        )
        memory_pressure = self._memory_pressure_signal(state)

        if isinstance(condensation_result, View):
            # Compaction did not fire — clean up the staged snapshot
            # so it cannot be injected stale on a future turn or session.
            delete_snapshot()
            logger.info(
                'ContextMemoryManager.condense_history finished with View '
                '(events=%d postprocess=%.3fs elapsed=%.3fs)',
                len(condensation_result.events),
                time.perf_counter() - postprocess_started,
                time.perf_counter() - started,
            )
            return CondensedHistory(condensation_result.events, None)

        # Compaction fired — promote the staged snapshot so it survives.
        commit_snapshot()

        action = condensation_result.action  # type: ignore[attr-defined]
        if self._is_noop_condensation_action(
            action
        ) and not self._has_unhandled_condensation_request(state):
            logger.info('Ignoring no-op condensation action without explicit request')
            if memory_pressure:
                state.ack_memory_pressure(source='ContextMemoryManager')
            logger.info(
                'ContextMemoryManager.condense_history finished with ignored no-op '
                '(history_events=%d elapsed=%.3fs)',
                len(history),
                time.perf_counter() - started,
            )
            return CondensedHistory(history, None)

        if memory_pressure:
            state.ack_memory_pressure(source='ContextMemoryManager')

        # Compaction occurred — attach the snapshot for post-recovery injection
        logger.info(
            'ContextMemoryManager.condense_history finished with pending action %s '
            '(postprocess=%.3fs elapsed=%.3fs)',
            type(action).__name__,
            time.perf_counter() - postprocess_started,
            time.perf_counter() - started,
        )
        return CondensedHistory([], action)

    def _extract_pre_condensation_snapshot(
        self, state: State, history: list[Event]
    ) -> None:
        """Extract and persist a snapshot of critical context from current history.

        This runs *before* the compactor, so the full event stream is still
        available.  The snapshot is read back during post-condensation recovery.
        """
        try:
            snapshot = extract_snapshot(history)
            self._attach_runtime_snapshot(snapshot, state)
            if (
                snapshot.get('files_touched')
                or snapshot.get('recent_errors')
                or snapshot.get('decisions')
                or snapshot.get('runtime')
            ):
                save_snapshot(snapshot)
        except Exception:
            logger.debug('Pre-condensation snapshot extraction failed', exc_info=True)

    @staticmethod
    def _attach_runtime_snapshot(snapshot: dict, state: State) -> None:
        """Attach live run position so post-condensation recovery is anchored."""
        iteration_flag = getattr(state, 'iteration_flag', None)
        turn_signals = getattr(state, 'turn_signals', None)
        runtime: dict[str, object] = {}
        session_id = getattr(state, 'session_id', None)
        if isinstance(session_id, str) and session_id:
            runtime['session_id'] = session_id
        current = getattr(iteration_flag, 'current_value', None)
        maximum = getattr(iteration_flag, 'max_value', None)
        if isinstance(current, int):
            runtime['iteration'] = current
        if isinstance(maximum, int):
            runtime['max_iterations'] = maximum
        memory_pressure = getattr(turn_signals, 'memory_pressure', None)
        if isinstance(memory_pressure, str) and memory_pressure:
            runtime['memory_pressure'] = memory_pressure
        if runtime:
            snapshot['runtime'] = runtime

    @staticmethod
    def get_restored_context() -> str:
        """Load and format the pre-condensation snapshot for injection into recovery.

        Returns an empty string if no snapshot is available.
        """
        snapshot = load_snapshot()
        if not snapshot:
            return ''
        return format_snapshot_for_injection(snapshot)

    def get_initial_user_message(self, events: Iterable[Event]) -> MessageAction:
        from backend.core.schemas import ActionType
        from backend.ledger.event import EventSource

        for event in events:
            try:
                source = getattr(event, 'source', None)
                if source != EventSource.USER:
                    continue

                if isinstance(event, MessageAction):
                    return event

                if getattr(event, 'action', None) == ActionType.MESSAGE and hasattr(
                    event, 'content'
                ):
                    cloned = MessageAction(
                        content=str(getattr(event, 'content', '')),
                        file_urls=getattr(event, 'file_urls', None),
                        image_urls=getattr(event, 'image_urls', None),
                        wait_for_response=bool(
                            getattr(event, 'wait_for_response', False)
                        ),
                    )
                    cloned.source = source
                    if hasattr(event, 'id'):
                        cloned.id = event.id
                    if hasattr(event, 'timestamp'):
                        cloned.timestamp = event.timestamp
                    return cloned
            except Exception:
                continue
        raise ValueError('Initial user message not found')

    def build_messages(
        self,
        condensed_history: Iterable[Event],
        initial_user_message: MessageAction,
        llm_config,
    ) -> list[Message]:
        if not self.conversation_memory:
            raise RuntimeError('Conversation memory is not initialized')

        events = list(condensed_history)
        window_started = time.perf_counter()
        prompt_window = select_prompt_events(events, llm_config)
        events_for_prompt = prompt_window.events
        window_elapsed = time.perf_counter() - window_started
        if prompt_window.windowed:
            logger.info(
                'ContextMemoryManager.prompt_window selected %d/%d events '
                '(dropped=%d estimated_tokens=%d selected_tokens=%d budget=%s '
                'protected=%d reason=%s fingerprint=%s elapsed=%.3fs)',
                prompt_window.selected_events,
                prompt_window.original_events,
                prompt_window.dropped_events,
                prompt_window.estimated_tokens,
                prompt_window.selected_estimated_tokens,
                prompt_window.token_budget,
                prompt_window.protected_events,
                prompt_window.reason,
                prompt_window.cache_fingerprint,
                window_elapsed,
            )
        started = time.perf_counter()
        messages = self.conversation_memory.process_events(
            condensed_history=events_for_prompt,
            initial_user_action=initial_user_message,
            max_message_chars=getattr(llm_config, 'max_message_chars', None),
            vision_is_active=getattr(llm_config, 'vision_is_active', False),
        )
        elapsed = time.perf_counter() - started
        if elapsed >= 0.25 or len(events_for_prompt) >= 100 or prompt_window.windowed:
            logger.info(
                'ContextMemoryManager.build_messages processed %d/%d events into %d '
                'messages in %.3fs (window=%.3fs)',
                len(events_for_prompt),
                len(events),
                len(messages),
                elapsed,
                window_elapsed,
            )

        if not messages:
            return messages

        self._apply_prompt_cache_hints(messages, llm_config)
        return messages

    @staticmethod
    def _apply_prompt_cache_hints(messages: list[Message], llm_config: object) -> None:
        model = getattr(llm_config, 'model', None) or ''
        caching_on = bool(getattr(llm_config, 'caching_prompt', True))
        if not caching_on or not model_supports_prompt_cache_hints(str(model)):
            return

        first_message = messages[0]
        for item in first_message.content:
            if isinstance(item, TextContent):
                item.cache_prompt = True
                break

        for message in reversed(messages):
            if message.role != 'user':
                continue
            for item in message.content:
                if isinstance(item, TextContent):
                    item.cache_prompt = True
                    break
            break


__all__ = [
    'CondensedHistory',
    'ContextMemoryManager',
]
