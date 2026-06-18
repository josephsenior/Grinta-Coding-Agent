"""Split submodule — see package facade for public API."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.context.canonical_state import (
    apply_canonical_patch,
    load_canonical_state,
    reduce_events_into_state,
    render_canonical_state_for_prompt,
    save_canonical_state,
    validate_canonical_state_for_compaction,
)
from backend.context.compaction.compact_boundary import project_after_compact_boundary
from backend.context.compaction.compaction_finalizer import finalize_compaction_artifacts
from backend.context.compactor.compactor import Compaction
from backend.context.compaction.condensed_history import CondensedHistory
from backend.context.context_budget import ContextBudget, record_post_compact_baseline
from backend.context.prompt.context_packet import (
    CONTEXT_PACKET_MARKER,
    build_context_packet_observation,
)
from backend.context.continuity_eval import compaction_passes_continuity_gate
from backend.context.compaction.microcompact import apply_microcompact
from backend.context.compaction.pre_condensation_snapshot import (
    delete_staging_snapshot,
    extract_snapshot,
    save_snapshot,
)
from backend.context.prompt.prompt_window import select_prompt_events
from backend.context.memory.session_context import bind_session_context
from backend.context.memory.session_memory import (
    build_compaction_summary,
    maybe_update,
    session_memory_exists,
)
from backend.context.tool_result_storage import (
    apply_frozen_tool_replacements,
    apply_tool_result_budget,
)
from backend.core.constants import (
    DEFAULT_BOUNDARY_COMPACT_COOLDOWN_SECONDS,
    DEFAULT_COMPACT_MIN_PRUNED_EVENTS,
    DEFAULT_COMPACT_MIN_TOKEN_REDUCTION,
    DEFAULT_DEGRADED_COMPACT_TAIL_RATIO,
    DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS,
    DEFAULT_INEFFECTIVE_COMPACT_BACKOFF_SECONDS,
    DEFAULT_INEFFECTIVE_COMPACT_MAX_SKIP_EVENTS,
    DEFAULT_INEFFECTIVE_COMPACT_SKIP_EVENTS,
    DEFAULT_LLM_COMPACT_COOLDOWN_SECONDS,
    DEFAULT_MICROCOMPACT_PRESERVE_RECENT,
    DEFAULT_PROMPT_MIN_TAIL_TOKENS,
    DEFAULT_PROMPT_MIN_TOOL_LOOPS,
)
from backend.core.logger import app_logger as logger
from backend.inference.capabilities.context_limits import limits_from_config
from backend.ledger.action.agent import CondensationAction
from backend.ledger.event import Event


from backend.context.context_pipeline.helpers import (
    _drop_stale_prompt_state_artifacts,
    _latest_event_id,
    _pruned_ids,
    _projected_compaction_token_reduction,
    _select_compaction_tail,
    _shrink_tail_for_token_reduction,
    _synthetic_history_after_action,
    apply_ineffective_compaction_backoff,
)
from backend.context.context_pipeline.types import (
    PipelineStepResult,
    _COMPACTION_TARGET_RATIO,
    _ContinuityGateDecision,
    _CONSECUTIVE_CONDENSATION_KEY,
    _CONTINUITY_REJECTION_FP_KEY,
    _CONTINUITY_REJECTION_STREAK_KEY,
    _DETERMINISTIC_FALLBACK_THRESHOLD,
    _INEFFECTIVE_COMPACT_STREAK_KEY,
    _INEFFECTIVE_COMPACT_UNTIL_KEY,
    _JUST_COMPACTED_KEY,
    _LAST_BOUNDARY_COMPACT_KEY,
    _LAST_LLM_COMPACT_KEY,
    _SKIP_COMPACTION_UNTIL_KEY,
)

import backend.context.context_pipeline as _cp

if TYPE_CHECKING:
    from backend.core.config.compactor_config import ContextPipelineConfig
    from backend.inference.llm_registry import LLMRegistry
    from backend.orchestration.state.state import State


class ContextPipelinePrepareMixin:
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
        budget = _cp.ContextBudget.from_events(events, llm_config=llm_config, state=state)
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
