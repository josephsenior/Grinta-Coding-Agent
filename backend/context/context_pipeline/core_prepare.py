"""Split submodule — see package facade for public API."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import backend.context.context_pipeline as _cp
from backend.context.canonical_state import (
    reduce_events_into_state,
)
from backend.context.compactor.compactor import Compaction
from backend.context.compactor.condensed_history import CondensedHistory
from backend.context.context_pipeline.core_compact import ContextPipelineCompactionMixin
from backend.context.memory.session_context import bind_session_context
from backend.core.logging.logger import app_logger as logger
from backend.ledger.action.agent import CondensationAction

if TYPE_CHECKING:
    from backend.orchestration.state.state import State


class ContextPipelinePrepareMixin(ContextPipelineCompactionMixin):
    """ContextPipeline methods (mixin)."""

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
        _cp.maybe_update(state, post_boundary, llm_config=llm_config)

        turn_signals = getattr(state, 'turn_signals', None)
        prewarmed = getattr(turn_signals, 'prewarmed_compaction', None)
        if prewarmed is not None and isinstance(prewarmed, Compaction):
            turn_signals.prewarmed_compaction = None  # type: ignore[union-attr]
            action = prewarmed.action
            if isinstance(action, CondensationAction):
                budget = _cp.ContextBudget.from_events(
                    post_boundary, llm_config=llm_config, state=state
                )
                if not self._passes_effectiveness_gate(
                    history, post_boundary, action, budget, state, llm_config
                ):
                    logger.warning(
                        'Pre-warmed compaction ineffective (pruned=%d); discarding',
                        len(action.pruned),
                    )
                    self._set_skip_compaction(state)
                else:
                    resolved_action = self._resolve_continuity_or_fallback(
                        state,
                        history,
                        post_boundary,
                        action,
                        budget,
                        llm_config,
                    )
                    if resolved_action is None:
                        self._set_skip_compaction(state)
                    else:
                        action = resolved_action
                        _cp.finalize_compaction_artifacts(state=state)
                        self._mark_just_compacted(state)
                        self._record_boundary_compact(state, history, action)
                        self._increment_condensation_counter(state)
                        logger.info(
                            'ContextPipeline used pre-warmed compaction in %.3fs',
                            time.perf_counter() - started,
                        )
                        return CondensedHistory([], action)

        events = post_boundary
        budget = _cp.ContextBudget.from_events(
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
            _cp.delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)

        if not (budget.should_autocompact or explicit or pressure_active):
            _cp.delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)

        if self._should_skip_compaction(state, force=force):
            _cp.delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)

        action = await self._run_compaction(
            state,
            history,
            events,
            budget,
            llm_config=llm_config,
            force=force,
            critical=critical_pressure,
        )
        if action is None:
            _cp.delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)

        if not self._passes_effectiveness_gate(
            history, events, action, budget, state, llm_config
        ):
            logger.warning(
                'Compaction ineffective (pruned=%d); skipping boundary commit',
                len(action.pruned),
            )
            self._set_skip_compaction(state)
            _cp.delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)

        resolved_action = self._resolve_continuity_or_fallback(
            state,
            history,
            events,
            action,
            budget,
            llm_config,
        )
        if resolved_action is None:
            self._set_skip_compaction(state)
            _cp.delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)
        action = resolved_action

        _cp.finalize_compaction_artifacts(state=state)
        self._mark_just_compacted(state)
        self._record_boundary_compact(state, history, action)
        self._increment_condensation_counter(state)
        if pressure_active:
            state.ack_memory_pressure(source='ContextPipeline')
            self._record_pressure_condensation()
        logger.info(
            'ContextPipeline committed compaction (pruned=%d elapsed=%.3fs)',
            len(action.pruned),
            time.perf_counter() - started,
        )
        return CondensedHistory([], action)
