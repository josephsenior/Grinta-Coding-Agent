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


class ContextPipelineCompactionMixin:
    """ContextPipeline methods (mixin)."""

    async def _run_compaction(
        self,
        state: State,
        history: list[Event],
        events: list[Event],
        budget: ContextBudget,
        *,
        llm_config: object | None,
        force: bool,
        critical: bool,
    ) -> CondensationAction | None:
        if not events:
            return None

        logger.info(
            'ContextPipeline: compaction triggered '
            '(should_autocompact=%s force=%s critical=%s dynamic_history_tokens=%d '
            'threshold=%d fixed_prompt_reserve=%d)',
            budget.should_autocompact,
            force,
            critical,
            budget.estimated_tokens,
            budget.autocompact_threshold,
            budget.fixed_prompt_reserve_tokens,
        )

        llm_allowed = self._config.allow_llm_hot_path and (
            critical or self._llm_cooldown_elapsed(state)
        )
        if llm_allowed:
            action = await self._llm_structured_compaction(
                events, state, budget=budget, llm_config=llm_config
            )
            if action is not None and action.summary:
                logger.info('ContextPipeline: LLM structured compaction (5b)')
                self._record_llm_compact_attempt(state)
                return action
        elif not self._config.allow_llm_hot_path:
            logger.debug('ContextPipeline: 5b skipped (allow_llm_hot_path=False)')
        else:
            logger.info('ContextPipeline: 5b skipped (llm compact cooldown)')

        if _cp.session_memory_exists(state=state):
            action = self._session_memory_compaction(
                state, events, budget=budget, llm_config=llm_config
            )
            if action is not None and self._action_meets_effectiveness(
                events, action, budget, state, llm_config
            ):
                logger.info('ContextPipeline: session-memory fallback compaction')
                return action
            logger.info(
                'ContextPipeline: session-memory fallback skipped '
                '(missing or ineffective action)'
            )

        logger.warning(
            'ContextPipeline: degraded boundary compaction (5c) — mandatory fallback'
        )
        return self._degraded_compaction(
            state,
            history,
            events,
            budget=budget,
            llm_config=llm_config,
        )

    def _session_memory_compaction(
        self,
        state: State,
        events: list[Event],
        *,
        budget: ContextBudget,
        llm_config: object | None,
    ) -> CondensationAction | None:
        summary = _cp.build_compaction_summary(state=state)
        if not summary.strip():
            return None
        tail = _cp._select_compaction_tail(
            events,
            budget,
            llm_config=llm_config,
            tail_ratio=_COMPACTION_TARGET_RATIO,
        )
        tail = _shrink_tail_for_token_reduction(
            events,
            tail,
            history=events,
            budget=budget,
            state=state,
            llm_config=llm_config,
            summary=summary,
        )
        pruned = _pruned_ids(events, tail)
        if not pruned:
            return None
        return CondensationAction(
            pruned_event_ids=sorted(pruned),
            summary=summary,
            summary_offset=0,
        )

    async def _llm_structured_compaction(
        self,
        events: list[Event],
        state: State,
        *,
        budget: ContextBudget | None = None,
        llm_config: object | None = None,
    ) -> CondensationAction | None:
        compactor = self._get_structured_compactor(state)
        if compactor is None:
            logger.info(
                'ContextPipeline: 5b skipped (no structured compactor / llm_config)'
            )
            return None
        if budget is not None:
            self._configure_structured_compactor_size(compactor, events, budget)
        from backend.context.view import View

        view = View(events=events)
        try:
            result = await compactor.get_compaction(view)
        except Exception as exc:
            logger.warning('LLM structured compaction failed: %s', exc)
            return None
        if isinstance(result, Compaction):
            action = result.action
            if action is not None and action.summary:
                if getattr(compactor, 'last_degraded', False):
                    logger.info(
                        'ContextPipeline: 5b degraded summary ignored; '
                        'falling back to deterministic compaction'
                    )
                    return None
                self._apply_structured_compactor_patch(compactor, state, events)
                return action
            logger.info(
                'ContextPipeline: 5b produced no summary (pruned=%d events=%d max_size=%d)',
                len(action.pruned) if action is not None else 0,
                len(events),
                getattr(compactor, 'max_size', 0),
            )
        return None

    @staticmethod
    def _apply_structured_compactor_patch(
        compactor: object,
        state: State,
        events: list[Event],
    ) -> None:
        patch = getattr(compactor, 'last_state_patch', None)
        if not isinstance(patch, dict) or not patch:
            return
        latest_id = _latest_event_id(events)
        try:
            canonical = load_canonical_state(state=state)
            canonical = apply_canonical_patch(
                canonical,
                patch,
                event_id=latest_id,
                source='structured_compactor',
            )
            save_canonical_state(canonical, state=state)
        except Exception:
            logger.debug('Structured compactor canonical patch failed', exc_info=True)

    def _degraded_compaction(
        self,
        state: State,
        history: list[Event],
        events: list[Event],
        *,
        budget: ContextBudget,
        llm_config: object | None,
    ) -> CondensationAction:
        tail = _cp._select_compaction_tail(
            events,
            budget,
            llm_config=llm_config,
            tail_ratio=DEFAULT_DEGRADED_COMPACT_TAIL_RATIO,
        )
        summary = _cp.build_compaction_summary(state=state)
        if not summary.strip():
            pruned_preview = _pruned_ids(events, tail)
            from backend.context.compactor.strategies.amortized_pruning_compactor import (
                AmortizedPruningCompactor,
            )

            pruned_events = [
                event
                for event in events
                if getattr(event, 'id', None) in pruned_preview
            ]
            summary = AmortizedPruningCompactor._build_recovery_summary(pruned_events)
        tail = _shrink_tail_for_token_reduction(
            events,
            tail,
            history=history,
            budget=budget,
            state=state,
            llm_config=llm_config,
            summary=summary,
        )
        pruned = _pruned_ids(events, tail)
        return CondensationAction(
            pruned_event_ids=sorted(pruned),
            summary=summary,
            summary_offset=0,
        )

    @staticmethod
    def _configure_structured_compactor_size(
        compactor: object,
        events: list[Event],
        budget: ContextBudget,
    ) -> None:
        """Align structured compactor sizing with pipeline budget targets."""
        event_count = len(events)
        if event_count < 2:
            compactor.max_size = 2  # type: ignore[attr-defined]
            compactor.keep_first = 0  # type: ignore[attr-defined]
            return
        target_tail = max(
            int(event_count * _COMPACTION_TARGET_RATIO),
            DEFAULT_PROMPT_MIN_TOOL_LOOPS * 2,
            8,
        )
        min_prune = DEFAULT_COMPACT_MIN_PRUNED_EVENTS
        desired_tail = min(target_tail, max(1, event_count - min_prune))
        # StructuredSummaryCompactor retains roughly max_size // 2 tail events.
        compactor.max_size = max(  # type: ignore[attr-defined]
            2 * desired_tail + 2,
            event_count - min_prune + 1,
            16,
        )
        compactor.max_size = min(compactor.max_size, event_count)  # type: ignore[attr-defined]
        compactor.keep_first = 0  # type: ignore[attr-defined]

    def _get_structured_compactor(self, state: State):
        if self._structured_compactor is not None:
            return self._structured_compactor
        llm_config = getattr(self._config, 'llm_config', None) or self._llm_config(
            state
        )
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
            self._structured_compactor = StructuredSummaryCompactor.from_config(
                cfg, self._llm_registry
            )
        except ValueError as exc:
            logger.warning('ContextPipeline: structured compactor unavailable: %s', exc)
            return None
        if self._structured_compactor.token_budget is None:
            agent_llm = getattr(getattr(state, 'agent', None), 'llm', None)
            max_input = getattr(
                getattr(agent_llm, 'config', None), 'max_input_tokens', None
            )
            if isinstance(max_input, int) and max_input > 0:
                self._structured_compactor.token_budget = int(max_input * 0.80)
        return self._structured_compactor
