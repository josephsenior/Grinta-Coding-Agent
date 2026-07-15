"""Context pipeline — unified compaction + prompt assembly for every LLM step.

Replaces the old 5-level mixin chain (ContextPipelineBaseMixin,
ContextPipelineStateMixin, ContextPipelineGatesMixin,
ContextPipelineCompactionMixin, ContextPipelinePrepareMixin,
ContextPipelinePromptMixin) with a single flat class that delegates
stateless compaction logic to ``_CompactionEngine`` and module-level
helper functions.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Self

from backend.context.canonical_state import reduce_events_into_state
from backend.context.compactor.compact_boundary import project_after_compact_boundary
from backend.context.compactor.compaction_finalizer import finalize_compaction_artifacts
from backend.context.compactor.compactor import Compaction
from backend.context.compactor.condensed_history import CondensedHistory
from backend.context.compactor.microcompact import apply_microcompact
from backend.context.compactor.pre_condensation_snapshot import (
    delete_staging_snapshot,
    extract_snapshot,
    save_snapshot,
)
from backend.context.context_budget import ContextBudget
from backend.context.context_pipeline.compaction import (
    _CompactionEngine,
    dismiss_explicit_compaction_request,
    has_actionable_explicit_request,
    mark_just_compacted,
    record_boundary_compact,
    resolve_continuity_or_fallback,
    should_run_compaction,
    should_skip_compaction,
)
from backend.context.context_pipeline.goal_context import strip_verbatim_user_echo
from backend.context.context_pipeline.helpers import (
    _drop_stale_prompt_state_artifacts,
    _synthetic_history_after_action,
    clear_prewarm_signals,
    is_prewarm_stale,
)
from backend.context.context_pipeline.types import _JUST_COMPACTED_KEY
from backend.context.memory.session_context import bind_session_context
from backend.context.memory.session_memory import maybe_update
from backend.context.prompt.context_packet import build_context_packet_observation
from backend.context.prompt.prompt_window import (
    PromptWindowResult,
    prompt_events_fingerprint,
    select_prompt_events,
)
from backend.context.tool_result_storage import (
    apply_frozen_tool_replacements,
    apply_tool_result_budget,
)
from backend.core.constants import (
    DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS,
    DEFAULT_MICROCOMPACT_PRESERVE_RECENT,
)
from backend.core.logging.logger import app_logger as logger
from backend.inference.capabilities.context_limits import limits_from_config
from backend.ledger.action.agent import CondensationAction
from backend.ledger.event import Event

if TYPE_CHECKING:
    from backend.core.config.compactor_config import ContextPipelineConfig
    from backend.inference.llm_registry import LLMRegistry
    from backend.orchestration.state.state import State


class _EmptyState:
    extra_data: dict[str, Any] = {}

    def set_extra(self, *args: Any, **kwargs: Any) -> None:
        pass


class ContextPipeline:
    """Fixed-order context pipeline replacing compactor strategy roulette.

    Owns the compaction-to-prompt-assembly lifecycle for each agent step.
    One instance per ``ContextMemoryManager``.
    """

    def __init__(
        self,
        *,
        llm_registry: LLMRegistry,
        config: ContextPipelineConfig,
        preserve_recent: int = DEFAULT_MICROCOMPACT_PRESERVE_RECENT,
        condensation_recorder: Callable[[], None] | None = None,
    ) -> None:
        self._llm_registry = llm_registry
        self._config = config
        self._preserve_recent = preserve_recent
        self._condensation_recorder = condensation_recorder

        self._structured_compactor: Any = None
        self._structured_compactor_model_key: str | None = None
        self._compaction_engine = _CompactionEngine(
            llm_registry=llm_registry,
            config=config,
            get_structured_compactor=self._get_structured_compactor,
        )

    @classmethod
    def from_config(
        cls,
        config: ContextPipelineConfig,
        llm_registry: LLMRegistry,
        *,
        condensation_recorder: Callable[[], None] | None = None,
    ) -> Self:
        kwargs = config.model_dump(
            exclude={'type', 'llm_config', 'allow_llm_hot_path'},
        )
        return cls(
            llm_registry=llm_registry,
            config=config,
            condensation_recorder=condensation_recorder,
            **kwargs,
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    async def prepare_step(
        self,
        state: State,
        *,
        streaming_emitter: Any | None = None,
        compaction_start_emitter: Any | None = None,
    ) -> CondensedHistory:
        """Run compaction layers; always commit a boundary when over threshold.

        When ``streaming_emitter`` is provided, it is attached to the cached
        structured-summary compactor so that the LLM stream can be observed
        in real time by the TUI's compaction card.
        """
        started = time.perf_counter()
        bind_session_context(state=state)
        history = list(getattr(state, 'history', []))
        llm_config = self._llm_config(state)

        # If a streaming emitter is supplied, attach it to the cached
        # structured-summary compactor. Restore the previous emitter on
        # exit so we never leak the caller's emitter across steps.
        previous_emitter: Any = None
        compactor_owner: Any = None
        if streaming_emitter is not None:
            compactor_owner = self._get_structured_compactor(state)
            if compactor_owner is not None and hasattr(
                compactor_owner, 'streaming_emitter'
            ):
                previous_emitter = compactor_owner.streaming_emitter
                compactor_owner.streaming_emitter = streaming_emitter
        try:
            return await self._prepare_step_impl(
                state,
                history,
                llm_config,
                started,
                compaction_start_emitter,
            )
        finally:
            if compactor_owner is not None:
                compactor_owner.streaming_emitter = previous_emitter

    async def _prepare_step_impl(
        self,
        state: State,
        history: list,
        llm_config: Any,
        started: float,
        compaction_start_emitter: Any | None,
    ) -> CondensedHistory:
        self._extract_pre_condensation_snapshot(state, history)
        reduce_events_into_state(history, state=state, source='context_pipeline')
        post_boundary = self._project_layers_1_to_3(
            history, state, apply_tool_budget=False
        )
        maybe_update(state, post_boundary, llm_config=llm_config)

        turn_signals = getattr(state, 'turn_signals', None)
        prewarmed = getattr(turn_signals, 'prewarmed_compaction', None)
        if prewarmed is not None and isinstance(prewarmed, Compaction):
            if is_prewarm_stale(history, turn_signals):
                logger.warning(
                    'Discarding stale pre-warmed compaction '
                    '(prewarm_len=%s current_len=%d prewarm_latest_id=%s current_latest_id=%s)',
                    getattr(turn_signals, 'prewarm_history_len', None),
                    len(history),
                    getattr(turn_signals, 'prewarm_latest_event_id', None),
                    getattr(history[-1], 'id', None) if history else None,
                )
                clear_prewarm_signals(turn_signals)
            else:
                clear_prewarm_signals(turn_signals)
                action = prewarmed.action
                if (
                    isinstance(action, CondensationAction)
                    and (action.summary or '').strip()
                ):
                    budget = ContextBudget.from_events(
                        post_boundary,
                        llm_config=llm_config,
                        state=state,
                    )
                    if should_skip_compaction(
                        state,
                        events=post_boundary,
                        llm_config=llm_config,
                        history=history,
                    ):
                        delete_staging_snapshot(state=state)
                        return CondensedHistory(history, None)
                    resolved_action = resolve_continuity_or_fallback(
                        state, history, post_boundary, action, budget, llm_config
                    )
                    if resolved_action is not None:
                        await self._notify_compaction_started(compaction_start_emitter)
                        action = resolved_action
                        action.summary = strip_verbatim_user_echo(
                            action.summary or '', state=state
                        )
                        finalize_compaction_artifacts(state=state)
                        mark_just_compacted(state)
                        record_boundary_compact(
                            state,
                            history,
                            action,
                            llm_config=llm_config,
                            post_events=self._projected_post_boundary(
                                history, action, state
                            ),
                        )
                        logger.info(
                            'ContextPipeline used pre-warmed compaction in %.3fs',
                            time.perf_counter() - started,
                        )
                        return CondensedHistory([], action)

        events = post_boundary
        budget = ContextBudget.from_events(
            events,
            llm_config=llm_config,
            state=state,
        )
        explicit = has_actionable_explicit_request(state, history)

        self._log_budget_snapshot(
            stage='prepare_step',
            events=events,
            budget=budget,
            llm_config=llm_config,
            explicit=explicit,
            memory_pressure=getattr(turn_signals, 'memory_pressure', None),
        )

        if not should_run_compaction(
            state,
            events=events,
            budget=budget,
            history=history,
            llm_config=llm_config,
            explicit=explicit,
        ):
            delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)

        await self._notify_compaction_started(compaction_start_emitter)
        action = await self._compaction_engine.run(
            state,
            history,
            events,
            budget,
            llm_config=llm_config,
            force=explicit,
            critical=False,
        )
        if action is None or not (action.summary or '').strip():
            if explicit:
                dismiss_explicit_compaction_request(state, history)
            logger.error(
                'ContextPipeline: LLM compaction produced no action; history unchanged'
            )
            delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)

        resolved_action = resolve_continuity_or_fallback(
            state, history, events, action, budget, llm_config
        )
        if resolved_action is None:
            delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)
        action = resolved_action
        if action.summary:
            action.summary = strip_verbatim_user_echo(action.summary, state=state)

        finalize_compaction_artifacts(state=state)
        mark_just_compacted(state)
        record_boundary_compact(
            state,
            history,
            action,
            llm_config=llm_config,
            post_events=self._projected_post_boundary(history, action, state),
        )
        from backend.context.canonical_state.ops import (
            merge_compaction_summary_into_canonical,
        )

        merge_compaction_summary_into_canonical(
            state=state, summary=action.summary or ''
        )
        logger.info(
            'ContextPipeline committed compaction (pruned=%d elapsed=%.3fs)',
            len(action.pruned),
            time.perf_counter() - started,
        )
        return CondensedHistory([], action)

    @staticmethod
    async def _notify_compaction_started(emitter: Any | None) -> None:
        """Emit the UI lifecycle signal at the exact committed start point."""
        if emitter is None:
            return
        try:
            result = emitter()
            if hasattr(result, '__await__'):
                await result
        except Exception:
            logger.debug('Compaction start emitter failed', exc_info=True)

    def build_prompt_events(
        self,
        condensed_history: list[Event],
        *,
        state: State | None = None,
        llm_config: object | None = None,
        full_history: list[Event] | None = None,
    ) -> list[Event]:
        """Assemble LLM-facing events through layers 1–7."""
        return self.build_prompt_window(
            condensed_history,
            state=state,
            llm_config=llm_config,
            full_history=full_history,
        ).events

    def build_prompt_window(
        self,
        condensed_history: list[Event],
        *,
        state: State | None = None,
        llm_config: object | None = None,
        full_history: list[Event] | None = None,
    ) -> PromptWindowResult:
        """Assemble and return the already-accounted LLM prompt window."""
        history = full_history if full_history is not None else list(condensed_history)
        events = self._project_layers_1_to_3(
            history, state or _EmptyState(), apply_tool_budget=True
        )
        events = _drop_stale_prompt_state_artifacts(events)

        just_compacted = False
        if state is not None:
            pipe = getattr(state, 'extra_data', {}).get('context_pipeline_state', {})
            just_compacted = (
                bool(pipe.get(_JUST_COMPACTED_KEY)) if isinstance(pipe, dict) else False
            )
            if just_compacted:
                pipe = dict(pipe) if isinstance(pipe, dict) else {}
                pipe[_JUST_COMPACTED_KEY] = False
                state.set_extra(
                    'context_pipeline_state', pipe, source='ContextPipeline'
                )

        packet = build_context_packet_observation(
            events,
            history,
            state=state,
            llm_config=llm_config,
            just_compacted=just_compacted,
        )
        if packet is not None:
            events = [packet, *events]

        window = select_prompt_events(
            events,
            llm_config,
            state=state,
            emergency_only=True,
            tool_budget_applied=True,
        )
        if (
            window.windowed
            and window.original_events >= DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS
            and window.selected_events < DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS
        ):
            logger.warning(
                'Emergency prompt window would collapse to %d/%d events; '
                'returning unwindowed prompt and marking critical memory pressure',
                window.selected_events,
                window.original_events,
            )
            if state is not None and hasattr(state, 'set_memory_pressure'):
                try:
                    state.set_memory_pressure('CRITICAL', source='ContextPipeline')
                except Exception:
                    logger.debug(
                        'Failed to mark emergency memory pressure', exc_info=True
                    )
            return PromptWindowResult(
                events=events,
                original_events=window.original_events,
                selected_events=len(events),
                dropped_events=max(0, window.original_events - len(events)),
                estimated_tokens=window.estimated_tokens,
                selected_estimated_tokens=window.estimated_tokens,
                token_budget=window.token_budget,
                protected_events=0,
                windowed=False,
                reason='emergency_window_rejected',
                cache_fingerprint=prompt_events_fingerprint(events),
            )
        return window

    async def prewarm_compaction(self, state: State) -> Compaction | None:
        """Run LLM compaction off the hot path for foreground reuse."""
        if not self._config.allow_llm_hot_path:
            return None
        bind_session_context(state=state)
        history = list(getattr(state, 'history', []))
        events = self._project_layers_1_to_3(history, state, apply_tool_budget=False)
        if not events:
            return None
        llm_config = self._llm_config(state)
        budget = ContextBudget.from_events(
            events,
            llm_config=llm_config,
            state=state,
        )
        if should_skip_compaction(
            state,
            events=events,
            llm_config=llm_config,
            history=history,
        ):
            return None
        if not budget.should_autocompact:
            return None
        action = await self._compaction_engine._llm_structured_compaction(
            events, state, budget=budget, llm_config=llm_config
        )
        if action is None or not action.summary:
            return None
        return Compaction(action=action)

    def note_llm_step(self, state: State) -> None:
        """Reset compaction guard after a real LLM step."""
        from backend.context.context_pipeline.helpers import (
            clear_compact_guard_after_llm_step,
        )

        clear_compact_guard_after_llm_step(state)

    def should_emit_compaction_status(self, state: State) -> bool:
        """Check if the next ``prepare_step`` is likely to compact."""
        turn_signals = getattr(state, 'turn_signals', None)
        prewarmed = getattr(turn_signals, 'prewarmed_compaction', None)
        if prewarmed is not None and isinstance(prewarmed, Compaction):
            action = getattr(prewarmed, 'action', None)
            if isinstance(action, CondensationAction):
                return True
        history = list(getattr(state, 'history', []))
        if not history:
            return False
        llm_config = self._llm_config(state)
        events = self._project_layers_1_to_3(history, state, apply_tool_budget=False)
        budget = ContextBudget.from_events(
            events,
            llm_config=llm_config,
            state=state,
        )
        explicit = has_actionable_explicit_request(state, history)
        return should_run_compaction(
            state,
            events=events,
            budget=budget,
            history=history,
            llm_config=llm_config,
            explicit=explicit,
        )

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _project_layers_1_to_3(
        self,
        history: list[Event],
        state: State | _EmptyState,
        *,
        apply_tool_budget: bool = True,
    ) -> list[Event]:
        events = project_after_compact_boundary(history)
        events = apply_frozen_tool_replacements(events, state)
        if apply_tool_budget:
            events = apply_tool_result_budget(events)
        events = apply_microcompact(
            events,
            preserve_recent=self._preserve_recent,
            state=None if isinstance(state, _EmptyState) else state,
        )
        return events

    def _projected_post_boundary(
        self,
        history: list[Event],
        action: CondensationAction,
        state: State,
    ) -> list[Event]:
        """Project post-boundary events the same way ``prepare_step`` measures budget."""
        return self._project_layers_1_to_3(
            _synthetic_history_after_action(history, action),
            state,
            apply_tool_budget=False,
        )

    def _extract_pre_condensation_snapshot(
        self, state: State, history: list[Event]
    ) -> None:
        bind_session_context(state=state)
        try:
            snapshot = extract_snapshot(history)
            runtime: dict[str, object] = {}
            session_id = getattr(state, 'session_id', None)
            if isinstance(session_id, str) and session_id:
                runtime['session_id'] = session_id
            iteration_flag = getattr(state, 'iteration_flag', None)
            current = getattr(iteration_flag, 'current_value', None)
            if isinstance(current, int):
                runtime['iteration'] = current
            if runtime:
                snapshot['runtime'] = runtime
            if (
                snapshot.get('files_touched')
                or snapshot.get('recent_errors')
                or snapshot.get('decisions')
                or snapshot.get('user_messages')
                or snapshot.get('test_results')
                or snapshot.get('background_tasks')
            ):
                save_snapshot(snapshot, state=state)
        except Exception:
            logger.debug('Pre-condensation snapshot extraction failed', exc_info=True)

    def _log_budget_snapshot(
        self,
        *,
        stage: str,
        events: list[Event],
        budget: ContextBudget,
        llm_config: object | None,
        explicit: bool = False,
        memory_pressure: object | None = None,
    ) -> None:
        limits = limits_from_config(llm_config, unknown_default=True)
        model = str(getattr(llm_config, 'model', '') or '<unknown>')
        triggered = budget.should_autocompact or explicit
        if not triggered and budget.estimated_tokens < int(
            budget.autocompact_threshold * 0.75
        ):
            return
        logger.info(
            'Context budget snapshot stage=%s model=%s limit_source=%s '
            'context_window=%s usable_input=%s max_output=%s events=%d '
            'dynamic_history_tokens=%d effective_window=%d fixed_prompt_reserve=%d '
            'reserved_summary=%d autocompact_threshold=%d should_autocompact=%s '
            'explicit=%s memory_pressure=%s',
            stage,
            model,
            limits.source,
            limits.context_window_tokens,
            limits.usable_input_tokens,
            limits.max_output_tokens,
            len(events),
            budget.estimated_tokens,
            budget.effective_window,
            budget.fixed_prompt_reserve_tokens,
            budget.reserved_summary_tokens,
            budget.autocompact_threshold,
            budget.should_autocompact,
            explicit,
            memory_pressure or '',
        )

    def _llm_config(self, state: State) -> object | None:
        llm_config = getattr(self._config, 'llm_config', None)
        if llm_config is None:
            agent = getattr(state, 'agent', None)
            llm = getattr(agent, 'llm', None) if agent is not None else None
            return getattr(llm, 'config', None) if llm is not None else None
        from backend.core.config.llm_config import LLMConfig

        if isinstance(llm_config, LLMConfig):
            return llm_config
        return self._llm_registry.config.get_llm_config(llm_config)

    def _record_pressure_condensation(self) -> None:
        if self._condensation_recorder is None:
            return
        try:
            self._condensation_recorder()
        except Exception:
            logger.debug('Memory pressure record_condensation failed', exc_info=True)

    def _get_structured_compactor(self, state: State) -> Any:
        """Lazily bind compaction to the actual active agent LLM instance."""
        try:
            agent_llm = self._llm_registry.get_active_llm()
        except (AttributeError, RuntimeError):
            agent_llm = getattr(getattr(state, 'agent', None), 'llm', None)
        if agent_llm is None:
            return None
        llm_cfg = getattr(agent_llm, 'config', None)
        model_key = str(getattr(llm_cfg, 'model', '') or '')
        if (
            self._structured_compactor is not None
            and self._structured_compactor_model_key == model_key
            and getattr(self._structured_compactor, 'llm', None) is agent_llm
        ):
            return self._structured_compactor
        from backend.context.compactor.strategies.structured_summary_compactor import (
            StructuredSummaryCompactor,
        )

        compactor = StructuredSummaryCompactor(
            llm=agent_llm,
            max_size=102,
            keep_first=0,
        )
        self._structured_compactor = compactor
        self._structured_compactor_model_key = model_key
        if compactor.token_budget is None:
            max_input = getattr(
                getattr(agent_llm, 'config', None), 'max_input_tokens', None
            )
            if isinstance(max_input, int) and max_input > 0:
                compactor.token_budget = int(max_input * 0.80)
        return compactor


__all__ = ['ContextPipeline']
