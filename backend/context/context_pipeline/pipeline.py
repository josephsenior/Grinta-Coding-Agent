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
from backend.context.compactor.compactor import Compaction
from backend.context.compactor.condensed_history import CondensedHistory
from backend.context.compactor.microcompact import apply_microcompact
from backend.context.compactor.pre_condensation_snapshot import (
    delete_staging_snapshot,
    extract_snapshot,
    save_snapshot,
)
from backend.context.compactor.compaction_finalizer import finalize_compaction_artifacts
from backend.context.context_budget import ContextBudget
from backend.context.context_pipeline.compaction import (
    _CompactionEngine,
    evaluate_continuity_gate,
    increment_condensation_counter,
    mark_just_compacted,
    passes_effectiveness_gate,
    record_boundary_compact,
    resolve_continuity_or_fallback,
    should_skip_compaction,
)
from backend.context.context_pipeline.helpers import (
    _drop_stale_prompt_state_artifacts,
    apply_ineffective_compaction_backoff,
)
from backend.context.context_pipeline.types import _JUST_COMPACTED_KEY
from backend.context.memory.session_context import bind_session_context
from backend.context.memory.session_memory import maybe_update
from backend.context.prompt.context_packet import build_context_packet_observation
from backend.context.prompt.prompt_window import select_prompt_events
from backend.context.tool_result_storage import (
    apply_frozen_tool_replacements,
    apply_tool_result_budget,
)
from backend.core.constants import (
    DEFAULT_BOUNDARY_COMPACT_COOLDOWN_SECONDS,
    DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS,
    DEFAULT_LLM_COMPACT_COOLDOWN_SECONDS,
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
        llm_compact_cooldown_seconds: int = DEFAULT_LLM_COMPACT_COOLDOWN_SECONDS,
        boundary_compact_cooldown_seconds: int = DEFAULT_BOUNDARY_COMPACT_COOLDOWN_SECONDS,
        condensation_recorder: Callable[[], None] | None = None,
    ) -> None:
        self._llm_registry = llm_registry
        self._config = config
        self._preserve_recent = preserve_recent
        self._llm_compact_cooldown = llm_compact_cooldown_seconds
        self._boundary_compact_cooldown = boundary_compact_cooldown_seconds
        self._condensation_recorder = condensation_recorder

        self._structured_compactor: Any = None
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

    async def prepare_step(self, state: State) -> CondensedHistory:
        """Run compaction layers; always commit a boundary when over threshold."""
        started = time.perf_counter()
        bind_session_context(state=state)
        history = list(getattr(state, 'history', []))
        llm_config = self._llm_config(state)

        self._extract_pre_condensation_snapshot(state, history)
        reduce_events_into_state(history, state=state, source='context_pipeline')
        post_boundary = self._project_layers_1_to_3(
            history, state, apply_tool_budget=False
        )
        maybe_update(state, post_boundary, llm_config=llm_config)

        turn_signals = getattr(state, 'turn_signals', None)
        prewarmed = getattr(turn_signals, 'prewarmed_compaction', None)
        if prewarmed is not None and isinstance(prewarmed, Compaction):
            turn_signals.prewarmed_compaction = None
            action = prewarmed.action
            if isinstance(action, CondensationAction):
                budget = ContextBudget.from_events(
                    post_boundary, llm_config=llm_config, state=state
                )
                if not passes_effectiveness_gate(
                    history, post_boundary, action, budget, state, llm_config
                ):
                    logger.warning(
                        'Pre-warmed compaction ineffective (pruned=%d); discarding',
                        len(action.pruned),
                    )
                    self._set_skip_compaction(state)
                else:
                    resolved_action = resolve_continuity_or_fallback(
                        state, history, post_boundary, action, budget, llm_config
                    )
                    if resolved_action is None:
                        self._set_skip_compaction(state)
                    else:
                        action = resolved_action
                        finalize_compaction_artifacts(state=state)
                        mark_just_compacted(state)
                        record_boundary_compact(state, history, action)
                        increment_condensation_counter(state)
                        logger.info(
                            'ContextPipeline used pre-warmed compaction in %.3fs',
                            time.perf_counter() - started,
                        )
                        return CondensedHistory([], action)

        events = post_boundary
        budget = ContextBudget.from_events(
            events, llm_config=llm_config, state=state
        )
        view = getattr(state, 'view', None)
        explicit = bool(getattr(view, 'unhandled_condensation_request', False))
        memory_pressure = getattr(turn_signals, 'memory_pressure', None)
        pressure_active = isinstance(memory_pressure, str) and bool(
            memory_pressure.strip()
        )
        critical_pressure = memory_pressure == 'CRITICAL'
        force = explicit or critical_pressure

        self._log_budget_snapshot(
            stage='prepare_step',
            events=events,
            budget=budget,
            llm_config=llm_config,
            explicit=explicit,
            memory_pressure=memory_pressure,
        )

        near_token_budget = budget.estimated_tokens >= int(
            budget.autocompact_threshold * 0.85
        )
        if (
            pressure_active
            and not budget.should_autocompact
            and not explicit
            and not critical_pressure
            and not near_token_budget
        ):
            logger.info(
                'ContextPipeline: non-critical memory pressure ignored for '
                'context compaction because prompt budget is below near-threshold '
                '(estimated=%d threshold=%d pressure=%s)',
                budget.estimated_tokens,
                budget.autocompact_threshold,
                memory_pressure,
            )
            delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)

        if not (budget.should_autocompact or explicit or pressure_active):
            delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)

        if should_skip_compaction(
            state, self._boundary_compact_cooldown, force=force
        ):
            delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)

        action = await self._compaction_engine.run(
            state,
            history,
            events,
            budget,
            llm_config=llm_config,
            force=force,
            critical=critical_pressure,
        )
        if action is None:
            delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)

        if not passes_effectiveness_gate(
            history, events, action, budget, state, llm_config
        ):
            logger.warning(
                'Compaction ineffective (pruned=%d); skipping boundary commit',
                len(action.pruned),
            )
            self._set_skip_compaction(state)
            delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)

        resolved_action = resolve_continuity_or_fallback(
            state, history, events, action, budget, llm_config
        )
        if resolved_action is None:
            self._set_skip_compaction(state)
            delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)
        action = resolved_action

        finalize_compaction_artifacts(state=state)
        mark_just_compacted(state)
        record_boundary_compact(state, history, action)
        increment_condensation_counter(state)
        if pressure_active:
            state.ack_memory_pressure(source='ContextPipeline')
            self._record_pressure_condensation()
        logger.info(
            'ContextPipeline committed compaction (pruned=%d elapsed=%.3fs)',
            len(action.pruned),
            time.perf_counter() - started,
        )
        return CondensedHistory([], action)

    def build_prompt_events(
        self,
        condensed_history: list[Event],
        *,
        state: State | None = None,
        llm_config: object | None = None,
        full_history: list[Event] | None = None,
    ) -> list[Event]:
        """Assemble LLM-facing events through layers 1–7."""
        history = full_history if full_history is not None else list(condensed_history)
        events = self._project_layers_1_to_3(
            history, state or _EmptyState(), apply_tool_budget=True
        )
        events = _drop_stale_prompt_state_artifacts(events)

        just_compacted = False
        if state is not None:
            pipe = getattr(state, 'extra_data', {}).get('context_pipeline_state', {})
            just_compacted = bool(pipe.get(_JUST_COMPACTED_KEY)) if isinstance(pipe, dict) else False
            if just_compacted:
                pipe = dict(pipe) if isinstance(pipe, dict) else {}
                pipe[_JUST_COMPACTED_KEY] = False
                state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')

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
            return events
        return window.events

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
            events, llm_config=llm_config, state=state
        )
        action = await self._compaction_engine._llm_structured_compaction(
            events, state, budget=budget, llm_config=llm_config
        )
        if action is None or not action.summary:
            return None
        return Compaction(action=action)

    def note_llm_step(self, state: State) -> None:
        """Reset condensation-loop counters after a real LLM step."""
        pipe = dict(getattr(state, 'extra_data', {}).get('context_pipeline_state', {}))
        from backend.context.context_pipeline.types import _CONSECUTIVE_CONDENSATION_KEY
        pipe[_CONSECUTIVE_CONDENSATION_KEY] = 0
        state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')

    def should_emit_compaction_status(self, state: State) -> bool:
        """Check if the next ``prepare_step`` is likely to compact."""
        history = list(getattr(state, 'history', []))
        if not history:
            return False
        llm_config = self._llm_config(state)
        events = self._project_layers_1_to_3(history, state, apply_tool_budget=False)
        budget = ContextBudget.from_events(
            events, llm_config=llm_config, state=state
        )
        view = getattr(state, 'view', None)
        explicit = bool(getattr(view, 'unhandled_condensation_request', False))
        turn_signals = getattr(state, 'turn_signals', None)
        memory_pressure = getattr(turn_signals, 'memory_pressure', None)
        return bool(
            budget.should_autocompact
            or explicit
            or (isinstance(memory_pressure, str) and memory_pressure.strip())
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

    def _extract_pre_condensation_snapshot(self, state: State, history: list[Event]) -> None:
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
                or snapshot.get('latest_directive')
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
        triggered = budget.should_autocompact or explicit or bool(memory_pressure)
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

    def _set_skip_compaction(self, state: State) -> None:
        apply_ineffective_compaction_backoff(state)

    def _get_structured_compactor(self, state: State) -> Any:
        """Lazily create and cache a StructuredSummaryCompactor."""
        if self._structured_compactor is not None:
            return self._structured_compactor
        llm_config = getattr(self._config, 'llm_config', None) or self._llm_config(state)
        if llm_config is None:
            return None
        from backend.context.compactor.strategies.structured_summary_compactor import (
            StructuredSummaryCompactor,
        )
        from backend.core.config.compactor_config import (
            StructuredSummaryCompactorConfig,
        )
        from backend.core.config.llm_config import LLMConfig

        if isinstance(llm_config, LLMConfig):
            llm_cfg = llm_config
        elif isinstance(llm_config, str):
            llm_cfg = self._llm_registry.config.get_llm_config(llm_config)
        else:
            return None
        cfg = StructuredSummaryCompactorConfig(
            llm_config=llm_cfg,
            max_size=40,
            keep_first=0,
        )
        try:
            compactor = StructuredSummaryCompactor.from_config(cfg, self._llm_registry)
        except ValueError as exc:
            logger.warning('ContextPipeline: structured compactor unavailable: %s', exc)
            return None
        self._structured_compactor = compactor
        if compactor.token_budget is None:
            agent_llm = getattr(getattr(state, 'agent', None), 'llm', None)
            max_input = getattr(
                getattr(agent_llm, 'config', None), 'max_input_tokens', None
            )
            if isinstance(max_input, int) and max_input > 0:
                compactor.token_budget = int(max_input * 0.80)
        return compactor


__all__ = ['ContextPipeline']
