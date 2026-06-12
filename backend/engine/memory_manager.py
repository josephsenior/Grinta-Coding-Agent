from __future__ import annotations

import copy
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.context import ContextMemory
from backend.context.compact_boundary import (
    boundary_info,
    project_after_compact_boundary,
)
from backend.context.compactor import Compactor
from backend.context.compaction_finalizer import finalize_compaction_artifacts
from backend.context.condensed_history import CondensedHistory
from backend.context.pre_condensation_snapshot import (
    delete_staging_snapshot,
    extract_snapshot,
    format_snapshot_for_injection,
    load_snapshot,
    save_snapshot,
)
from backend.context.prompt_window import event_fingerprint, select_prompt_events
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
    from backend.ledger.event import Event
    from backend.utils.prompt import PromptManager


_MIN_HISTORY_EVENTS_FOR_FORCED_COMPACTION = 30


@dataclass
class _BuildMessagesCache:
    event_fingerprints: tuple[str, ...]
    messages: list[Message]
    llm_config_key: str


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
        self._pipeline: Any = None
        self._build_messages_cache: _BuildMessagesCache | None = None

    @staticmethod
    def _is_pipeline_config(compactor_config: object | None) -> bool:
        from backend.core.config.compactor_config import ContextPipelineConfig

        return isinstance(compactor_config, ContextPipelineConfig)

    def _resolve_pipeline_llm_config(self) -> object | None:
        """Return the effective LLM config for context-pipeline compaction."""
        getter = getattr(self._config, 'get_llm_config', None)
        if callable(getter):
            try:
                agent_llm = getter()
                if agent_llm is not None:
                    return agent_llm
            except Exception:
                logger.debug('Agent LLM config lookup failed', exc_info=True)
        registry_config = getattr(self._llm_registry, 'config', None)
        if registry_config is None:
            return None
        getter = getattr(registry_config, 'get_llm_config_from_agent_config', None)
        if callable(getter):
            try:
                agent_llm = getter(self._config)
                if agent_llm is not None:
                    return agent_llm
            except Exception:
                logger.debug('Registry agent LLM config lookup failed', exc_info=True)
        getter = getattr(registry_config, 'get_llm_config', None)
        if callable(getter):
            try:
                return getter('llm')
            except Exception:
                logger.debug('Default LLM config lookup failed', exc_info=True)
        return None

    def initialize(self, prompt_manager: PromptManager) -> None:
        """Initialize context memory with prompt manager."""
        self.conversation_memory = ContextMemory(self._config, prompt_manager)
        compactor_config = getattr(self._config, 'compactor_config', None)
        if self._is_pipeline_config(compactor_config):
            try:
                from backend.context.context_pipeline import ContextPipeline
                from backend.core.config.compactor_config import ContextPipelineConfig

                agent_llm = self._resolve_pipeline_llm_config()
                if (
                    isinstance(compactor_config, ContextPipelineConfig)
                    and compactor_config.llm_config is None
                    and agent_llm is not None
                ):
                    compactor_config = compactor_config.model_copy(
                        update={'llm_config': agent_llm}
                    )
                self._pipeline = ContextPipeline.from_config(
                    compactor_config,
                    self._llm_registry,
                )
                self.compactor = None
                logger.debug('Using context pipeline')
            except Exception as exc:  # pragma: no cover - condensation optional
                logger.warning('Failed to initialize context pipeline: %s', exc)
                self._pipeline = None
                self.compactor = None
            return
        self._pipeline = None
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
        if self._pipeline is not None:
            return self._pipeline.should_emit_compaction_status(state)
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
        if self._pipeline is not None:
            return await self._pipeline.prepare_step(state)

        from backend.context.session_context import bind_session_context

        bind_session_context(state=state)
        started = time.perf_counter()
        history = list(getattr(state, 'history', []))
        if not self.compactor:
            logger.debug(
                'ContextMemoryManager.condense_history skipped: no compactor (history_events=%d elapsed=%.3fs)',
                len(history),
                time.perf_counter() - started,
            )
            return CondensedHistory(history, None)

        snapshot_started = time.perf_counter()
        self._extract_pre_condensation_snapshot(state, history)
        snapshot_elapsed = time.perf_counter() - snapshot_started

        condensation_result = await self._get_condensation_result(
            state, history, snapshot_elapsed
        )

        postprocess_started = time.perf_counter()
        condensation_result = await self._maybe_force_compaction_for_explicit_request(
            state, condensation_result
        )
        condensation_result = await self._maybe_force_compaction_under_memory_pressure(
            state, history, condensation_result
        )
        memory_pressure = self._memory_pressure_signal(state)

        if isinstance(condensation_result, View):
            delete_staging_snapshot(state=state)
            logger.info(
                'ContextMemoryManager.condense_history finished with View (events=%d postprocess=%.3fs elapsed=%.3fs)',
                len(condensation_result.events),
                time.perf_counter() - postprocess_started,
                time.perf_counter() - started,
            )
            return CondensedHistory(condensation_result.events, None)

        return await self._finalize_compaction(
            state,
            condensation_result,
            history,
            memory_pressure,
            started,
            postprocess_started,
        )

    async def _get_condensation_result(
        self, state: State, history: list, snapshot_elapsed: float
    ) -> Any:
        turn_signals = getattr(state, 'turn_signals', None)
        prewarmed = getattr(turn_signals, 'prewarmed_compaction', None)
        if prewarmed is not None:
            return await self._use_prewarmed_result(
                prewarmed, turn_signals, history, state
            )
        compaction_started = time.perf_counter()
        assert self.compactor is not None
        result = await self.compactor.compacted_history(state)
        logger.info(
            'ContextMemoryManager.condense_history compactor returned %s (history_events=%d snapshot=%.3fs compactor=%.3fs)',
            type(result).__name__,
            len(history),
            snapshot_elapsed,
            time.perf_counter() - compaction_started,
        )
        return result

    async def _use_prewarmed_result(
        self,
        prewarmed: Any,
        turn_signals: Any,
        history: list,
        state: State,
    ) -> Any:
        turn_signals.prewarmed_compaction = None
        prewarm_len = getattr(turn_signals, 'prewarm_history_len', None)
        prewarm_latest_id = getattr(turn_signals, 'prewarm_latest_event_id', None)
        turn_signals.prewarm_history_len = None
        turn_signals.prewarm_latest_event_id = None
        current_len = len(history)
        current_latest_id = getattr(history[-1], 'id', None) if history else None
        prewarm_stale = prewarm_len is not None and (
            prewarm_len != current_len or prewarm_latest_id != current_latest_id
        )
        if prewarm_stale:
            logger.warning(
                'Discarding stale pre-warmed condensation (prewarm_len=%s current_len=%s prewarm_latest_id=%s current_latest_id=%s); recomputing compaction.',
                prewarm_len,
                current_len,
                prewarm_latest_id,
                current_latest_id,
            )
            assert self.compactor is not None
            return await self.compactor.compacted_history(state)
        logger.info('Utilizing background pre-warmed condensation result.')
        action = getattr(prewarmed, 'action', None)
        if action:
            action.is_prewarmed = True
        return prewarmed

    async def _finalize_compaction(
        self,
        state: State,
        condensation_result: Any,
        history: list,
        memory_pressure: bool | str | None,
        started: float,
        postprocess_started: float,
    ) -> CondensedHistory:
        action = condensation_result.action
        finalize_compaction_artifacts(state=state)

        if self._is_noop_condensation_action(
            action
        ) and not self._has_unhandled_condensation_request(state):
            logger.info('Ignoring no-op condensation action without explicit request')
            if memory_pressure:
                state.ack_memory_pressure(source='ContextMemoryManager')
            logger.info(
                'ContextMemoryManager.condense_history finished with ignored no-op (history_events=%d elapsed=%.3fs)',
                len(history),
                time.perf_counter() - started,
            )
            return CondensedHistory(history, None)

        if memory_pressure:
            state.ack_memory_pressure(source='ContextMemoryManager')
        self._release_post_compaction_resources(state, action)
        logger.info(
            'ContextMemoryManager.condense_history finished with pending action %s (postprocess=%.3fs elapsed=%.3fs)',
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
            try:
                from backend.context.canonical_state import (
                    reduce_snapshot_into_state,
                    save_canonical_state,
                )

                latest_id = getattr(history[-1], 'id', None) if history else None
                canonical = reduce_snapshot_into_state(
                    snapshot,
                    latest_event_id=latest_id if isinstance(latest_id, int) else None,
                    source='memory_manager',
                    persist_state=state,
                )
                save_canonical_state(canonical, state=state)
            except Exception:
                logger.debug('Canonical state update failed', exc_info=True)
            if (
                snapshot.get('files_touched')
                or snapshot.get('recent_errors')
                or snapshot.get('decisions')
                or snapshot.get('runtime')
                or snapshot.get('latest_directive')
                or snapshot.get('test_results')
                or snapshot.get('background_tasks')
            ):
                save_snapshot(snapshot, state=state)
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
    def get_restored_context(*, state: State | None = None) -> str:
        """Load and format the pre-condensation snapshot for injection into recovery.

        Returns an empty string if no snapshot is available.
        """
        from backend.context.session_context import bind_session_context

        bind_session_context(state=state)
        snapshot = load_snapshot(state=state)
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

    @staticmethod
    def _llm_build_config_key(llm_config: object) -> str:
        return '|'.join(
            str(value)
            for value in (
                getattr(llm_config, 'model', ''),
                getattr(llm_config, 'max_message_chars', None),
                getattr(llm_config, 'vision_is_active', False),
                getattr(llm_config, 'prompt_history_windowing_enabled', True),
                getattr(llm_config, 'prompt_history_token_budget', None),
                getattr(llm_config, 'prompt_history_max_events', None),
            )
        )

    def invalidate_build_messages_cache(self) -> None:
        """Clear incremental build cache after history-shaping events."""
        self._build_messages_cache = None

    def _release_post_compaction_resources(self, state: State, action: object) -> None:
        """Release caches superseded by a compaction pass."""
        self.invalidate_build_messages_cache()
        if self.conversation_memory is not None:
            evicted = self.conversation_memory.release_post_compaction_render_cache()
            if evicted:
                logger.debug(
                    'Released %d post-compaction render-cache entries',
                    evicted,
                )

        event_stream = getattr(state, 'event_stream', None)
        event_store = (
            event_stream
            if event_stream is not None and hasattr(event_stream, 'prune_old_events')
            else None
        )
        if event_store is not None:
            try:
                pruned = event_store.prune_old_events(keep_recent=1000)
                if pruned:
                    logger.info(
                        'Post-compaction event-store prune removed %d stale files',
                        pruned,
                    )
            except Exception:
                logger.debug('Post-compaction event-store prune failed', exc_info=True)

        pruned_ids = getattr(action, 'pruned', None)
        if isinstance(pruned_ids, (list, tuple, set)) and pruned_ids:
            logger.debug(
                'Compaction pruned %d event id(s) from active history',
                len(pruned_ids),
            )

    def build_messages(
        self,
        condensed_history: Iterable[Event],
        initial_user_message: MessageAction,
        llm_config,
        *,
        state: State | None = None,
    ) -> list[Message]:
        if not self.conversation_memory:
            raise RuntimeError('Conversation memory is not initialized')

        condensed_list = list(condensed_history)
        window_started = time.perf_counter()
        events_for_prompt, prompt_window = self._resolve_prompt_events(
            condensed_list, state, llm_config
        )
        window_elapsed = time.perf_counter() - window_started

        messages = self._process_events(
            events_for_prompt, initial_user_message, llm_config, prompt_window
        )

        self._log_build_messages(
            metrics={
                'events_for_prompt': len(events_for_prompt),
                'original_events': prompt_window.original_events,
                'messages': len(messages),
                'elapsed': time.perf_counter() - window_started,
                'window_elapsed': window_elapsed,
                'windowed': prompt_window.windowed,
                'prompt_window': prompt_window,
            }
        )

        if not messages:
            self._build_messages_cache = None
            return messages

        config_key = self._llm_build_config_key(llm_config)
        fingerprints = tuple(event_fingerprint(event) for event in events_for_prompt)
        self._build_messages_cache = _BuildMessagesCache(
            event_fingerprints=fingerprints,
            messages=copy.deepcopy(messages),
            llm_config_key=config_key,
        )
        self._apply_prompt_cache_hints(messages, llm_config)
        return messages

    def _resolve_prompt_events(
        self, condensed_list: list, state: State | None, llm_config
    ):
        if self._pipeline is not None:
            full_history = (
                list(getattr(state, 'history', []))
                if state is not None
                else condensed_list
            )
            events_for_prompt = self._pipeline.build_prompt_events(
                condensed_list,
                state=state,
                llm_config=llm_config,
                full_history=full_history,
            )
            from backend.context.prompt_window import (
                PromptWindowResult,
                estimate_prompt_events_tokens,
            )

            prompt_window = PromptWindowResult(
                events=events_for_prompt,
                original_events=len(full_history),
                selected_events=len(events_for_prompt),
                dropped_events=max(0, len(full_history) - len(events_for_prompt)),
                estimated_tokens=estimate_prompt_events_tokens(full_history),
                selected_estimated_tokens=estimate_prompt_events_tokens(
                    events_for_prompt
                ),
                token_budget=None,
                protected_events=0,
                windowed=False,
                reason='pipeline',
                cache_fingerprint='',
            )
        else:
            events = project_after_compact_boundary(condensed_list)
            info = boundary_info(condensed_list)
            if info is not None:
                logger.debug(
                    'Prompt projection after compact boundary id=%d pruned=%d post_boundary=%d',
                    info.boundary_event_id,
                    info.pruned_event_count,
                    info.post_boundary_event_count,
                )
            prompt_window = select_prompt_events(events, llm_config, state=state)
            events_for_prompt = prompt_window.events
        return events_for_prompt, prompt_window

    def _process_events(
        self, events_for_prompt, initial_user_message, llm_config, prompt_window
    ) -> list[Message]:
        config_key = self._llm_build_config_key(llm_config)
        fingerprints = tuple(event_fingerprint(event) for event in events_for_prompt)
        cache = self._build_messages_cache
        incremental = self._is_incremental(
            cache, config_key, fingerprints, prompt_window
        )
        max_message_chars = getattr(llm_config, 'max_message_chars', None)
        vision_is_active = getattr(llm_config, 'vision_is_active', False)

        assert self.conversation_memory is not None
        if incremental and cache is not None:
            messages = self.conversation_memory.process_events_appending(
                condensed_history=events_for_prompt,
                initial_user_action=initial_user_message,
                prefix_messages=cache.messages,
                prefix_event_count=len(cache.event_fingerprints),
                max_message_chars=max_message_chars,
                vision_is_active=vision_is_active,
            )
            logger.debug(
                'ContextMemoryManager.build_messages incremental tail=%d/%d events',
                len(fingerprints) - len(cache.event_fingerprints),
                len(fingerprints),
            )
        else:
            messages = self.conversation_memory.process_events(
                condensed_history=events_for_prompt,
                initial_user_action=initial_user_message,
                max_message_chars=max_message_chars,
                vision_is_active=vision_is_active,
            )
        return messages

    @staticmethod
    def _is_incremental(cache, config_key, fingerprints, prompt_window) -> bool:
        return (
            cache is not None
            and cache.llm_config_key == config_key
            and not prompt_window.windowed
            and len(fingerprints) > len(cache.event_fingerprints)
            and fingerprints[: len(cache.event_fingerprints)]
            == cache.event_fingerprints
        )

    def _log_build_messages(self, metrics: dict) -> None:
        prompt_window = metrics['prompt_window']
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
                metrics['window_elapsed'],
            )
        if (
            metrics['elapsed'] >= 0.25
            or metrics['events_for_prompt'] >= 100
            or prompt_window.windowed
        ):
            logger.info(
                'ContextMemoryManager.build_messages processed %d/%d events into %d '
                'messages in %.3fs (window=%.3fs)',
                metrics['events_for_prompt'],
                metrics['original_events'],
                metrics['messages'],
                metrics['elapsed'],
                metrics['window_elapsed'],
            )

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
