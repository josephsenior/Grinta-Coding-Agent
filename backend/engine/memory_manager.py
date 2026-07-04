from __future__ import annotations

import copy
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.context.compactor.condensed_history import CondensedHistory
from backend.context.compactor.pre_condensation_snapshot import (
    format_snapshot_for_injection,
    load_snapshot,
)
from backend.context.memory.conversation_memory import ContextMemory
from backend.context.prompt.prompt_window import event_fingerprint
from backend.context.prompt.user_turns import (
    collect_user_messages,
    merge_missing_user_turns,
)
from backend.core.logging.logger import app_logger as logger
from backend.core.message import Message
from backend.engine.memory_prompt_cache import apply_prompt_cache_hints
from backend.ledger.action import MessageAction

if TYPE_CHECKING:
    from backend.core.config import AgentConfig
    from backend.inference.llm_registry import LLMRegistry
    from backend.ledger.event import Event
    from backend.orchestration.state.state import State
    from backend.utils.prompt import PromptManager


@dataclass
class _BuildMessagesCache:
    event_ids: tuple[int | str, ...]
    event_fingerprints: tuple[str, ...]
    messages: list[Message]
    llm_config_key: str


class ContextMemoryManager:
    """Owns context memory and condensation."""

    def __init__(
        self,
        config: AgentConfig,
        llm_registry: LLMRegistry,
        condensation_recorder: Callable[[], None] | None = None,
    ) -> None:
        self._config = config
        self._llm_registry = llm_registry
        self._condensation_recorder = condensation_recorder
        self.conversation_memory: ContextMemory | None = None
        self._pipeline: Any = None
        self._build_messages_cache: _BuildMessagesCache | None = None

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

    def _normalized_pipeline_config(self):
        from backend.core.config.compactor_config import ContextPipelineConfig

        compactor_config = getattr(self._config, 'compactor_config', None)
        agent_llm = self._resolve_pipeline_llm_config()
        if compactor_config is None:
            pipeline_config = ContextPipelineConfig(llm_config=agent_llm)
        elif isinstance(compactor_config, ContextPipelineConfig):
            pipeline_config = compactor_config
        else:
            logger.info(
                'Agent compactor type %r maps to context_pipeline',
                getattr(compactor_config, 'type', type(compactor_config).__name__),
            )
            pipeline_config = ContextPipelineConfig(llm_config=agent_llm)
        if pipeline_config.llm_config is None and agent_llm is not None:
            pipeline_config = pipeline_config.model_copy(
                update={'llm_config': agent_llm}
            )
        return pipeline_config

    def initialize(self, prompt_manager: PromptManager) -> None:
        """Initialize context memory with prompt manager."""
        self.conversation_memory = ContextMemory(self._config, prompt_manager)
        self._pipeline = None
        try:
            from backend.context.context_pipeline import ContextPipeline

            self._pipeline = ContextPipeline.from_config(
                self._normalized_pipeline_config(),
                self._llm_registry,
                condensation_recorder=self._condensation_recorder,
            )
            logger.debug('Using context pipeline')
        except Exception as exc:  # pragma: no cover - condensation optional
            logger.warning('Failed to initialize context pipeline: %s', exc)

    def should_emit_compaction_status(self, state: State) -> bool:
        """Return True when foreground condensation is likely to emit an action."""
        if self._pipeline is None:
            return False
        return self._pipeline.should_emit_compaction_status(state)

    async def condense_history(
        self, state: State, *, event_stream: Any | None = None
    ) -> CondensedHistory:
        emitter = self._build_streaming_emitter(event_stream)
        if self._pipeline is None:
            history = list(getattr(state, 'history', []))
            logger.debug(
                'ContextMemoryManager.condense_history skipped: no pipeline (history_events=%d)',
                len(history),
            )
            return CondensedHistory(history, None)
        return await self._pipeline.prepare_step(state, streaming_emitter=emitter)

    @staticmethod
    def _build_streaming_emitter(event_stream: Any | None) -> Any | None:
        """Build a streaming emitter for the compactor from an EventStream.

        Returns ``None`` when no event stream is available or when the
        necessary action class is not importable.
        """
        if event_stream is None:
            return None
        try:
            from backend.ledger.action.message import StreamingChunkAction
            from backend.ledger.event import EventSource
        except Exception:
            return None

        def _emit(chunk: str, accumulated: str, is_final: bool) -> None:
            try:
                ev = StreamingChunkAction(
                    chunk=chunk,
                    accumulated=accumulated,
                    is_final=is_final,
                    tool_call_name='compaction',
                )
                ev.source = EventSource.AGENT
                event_stream.add_event(ev, EventSource.AGENT)
            except Exception as exc:  # noqa: BLE001
                logger.debug('compaction streaming emit failed: %s', exc)

        return _emit

    @staticmethod
    def get_restored_context(*, state: State | None = None) -> str:
        """Load and format the pre-condensation snapshot for injection into recovery.

        Returns an empty string if no snapshot is available.
        """
        from backend.context.memory.session_context import bind_session_context

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

    def get_user_messages_for_prompt(
        self,
        events: Iterable[Event],
        *,
        max_turns: int = 6,
    ) -> list[MessageAction]:
        """Return recent USER MessageActions for prompt assembly and tests."""
        return collect_user_messages(events, max_turns=max_turns)

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
        full_history = (
            list(getattr(state, 'history', []))
            if state is not None
            else list(condensed_list)
        )
        events_for_prompt = merge_missing_user_turns(
            list(events_for_prompt),
            full_history,
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
        event_ids = tuple(
            self._prompt_event_cache_key(event) for event in events_for_prompt
        )
        fingerprints = tuple(event_fingerprint(event) for event in events_for_prompt)
        self._build_messages_cache = _BuildMessagesCache(
            event_ids=event_ids,
            event_fingerprints=fingerprints,
            messages=copy.deepcopy(messages),
            llm_config_key=config_key,
        )
        apply_prompt_cache_hints(messages, llm_config)
        return messages

    def _resolve_prompt_events(
        self, condensed_list: list, state: State | None, llm_config
    ):
        if self._pipeline is None:
            raise RuntimeError('Context pipeline is not initialized')
        full_history = (
            list(getattr(state, 'history', [])) if state is not None else condensed_list
        )
        events_for_prompt = self._pipeline.build_prompt_events(
            condensed_list,
            state=state,
            llm_config=llm_config,
            full_history=full_history,
        )
        from backend.context.prompt.prompt_window import (
            PromptWindowResult,
            estimate_prompt_events_tokens,
        )

        prompt_window = PromptWindowResult(
            events=events_for_prompt,
            original_events=len(full_history),
            selected_events=len(events_for_prompt),
            dropped_events=max(0, len(full_history) - len(events_for_prompt)),
            estimated_tokens=estimate_prompt_events_tokens(full_history),
            selected_estimated_tokens=estimate_prompt_events_tokens(events_for_prompt),
            token_budget=None,
            protected_events=0,
            windowed=False,
            reason='pipeline',
            cache_fingerprint='',
        )
        return events_for_prompt, prompt_window

    def _process_events(
        self, events_for_prompt, initial_user_message, llm_config, prompt_window
    ) -> list[Message]:
        config_key = self._llm_build_config_key(llm_config)
        event_ids = tuple(
            self._prompt_event_cache_key(event) for event in events_for_prompt
        )
        tuple(event_fingerprint(event) for event in events_for_prompt)
        cache = self._build_messages_cache
        incremental = self._is_incremental(cache, config_key, event_ids, prompt_window)
        max_message_chars = getattr(llm_config, 'max_message_chars', None)
        vision_is_active = getattr(llm_config, 'vision_is_active', False)

        assert self.conversation_memory is not None
        if incremental and cache is not None:
            messages = self.conversation_memory.process_events_appending(
                condensed_history=events_for_prompt,
                initial_user_action=initial_user_message,
                prefix_messages=cache.messages,
                prefix_event_count=len(cache.event_ids),
                max_message_chars=max_message_chars,
                vision_is_active=vision_is_active,
            )
            logger.debug(
                'ContextMemoryManager.build_messages incremental tail=%d/%d events',
                len(event_ids) - len(cache.event_ids),
                len(event_ids),
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
    def _prompt_event_cache_key(event: Event) -> int | str:
        event_id = getattr(event, 'id', None)
        if isinstance(event_id, int):
            return event_id
        return event_fingerprint(event)

    @staticmethod
    def _is_incremental(cache, config_key, event_ids, prompt_window) -> bool:
        return (
            cache is not None
            and cache.llm_config_key == config_key
            and not prompt_window.windowed
            and len(event_ids) > len(cache.event_ids)
            and event_ids[: len(cache.event_ids)] == cache.event_ids
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


__all__ = [
    'CondensedHistory',
    'ContextMemoryManager',
]
