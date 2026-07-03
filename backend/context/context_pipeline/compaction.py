"""Compaction engine, continuity gate, and pipeline state helpers.

Extracted from the old mixin chain to simplify the ContextPipeline class.
All functions here are stateless — they operate on ``state.extra_data``
or receive their dependencies as parameters.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from backend.context.canonical_state import (
    load_canonical_state,
    render_canonical_state_for_prompt,
    validate_canonical_state_for_compaction,
)
from backend.context.compactor.compact_boundary import project_after_compact_boundary
from backend.context.compactor.compactor import Compaction
from backend.context.context_budget import ContextBudget, record_post_compact_baseline
from backend.context.context_pipeline.helpers import (
    _pruned_ids,
    _select_compaction_tail,
    _shrink_tail_for_token_reduction,
    _synthetic_history_after_action,
)
from backend.context.context_pipeline.types import (
    _COMPACTION_TARGET_RATIO,
    _CONSECUTIVE_CONDENSATION_KEY,
    _INEFFECTIVE_COMPACT_STREAK_KEY,
    _INEFFECTIVE_COMPACT_UNTIL_KEY,
    _JUST_COMPACTED_KEY,
    _LAST_BOUNDARY_COMPACT_KEY,
    _LAST_LLM_COMPACT_KEY,
    _SKIP_COMPACTION_UNTIL_KEY,
    _ContinuityGateDecision,
)
from backend.context.continuity_eval import compaction_passes_continuity_gate
from backend.context.memory.session_memory import (
    build_compaction_summary,
    session_memory_exists,
)
from backend.core.constants import (
    DEFAULT_COMPACT_MIN_PRUNED_EVENTS,
    DEFAULT_COMPACT_MIN_TOKEN_REDUCTION,
    DEFAULT_DEGRADED_COMPACT_TAIL_RATIO,
)
from backend.core.logging.logger import app_logger as logger
from backend.ledger.action.agent import CondensationAction
from backend.ledger.event import Event

if TYPE_CHECKING:
    from backend.core.config.compactor_config import ContextPipelineConfig
    from backend.inference.llm_registry import LLMRegistry
    from backend.orchestration.state.state import State

# --------------------------------------------------------------------------- #
# Pipeline state helpers — read/write compaction tracking in state.extra_data
# --------------------------------------------------------------------------- #

_PIPELINE_STATE_KEY = 'context_pipeline_state'


def _pipeline_state(state: State) -> dict[str, Any]:
    raw = getattr(state, 'extra_data', {}).get(_PIPELINE_STATE_KEY, {})
    return dict(raw) if isinstance(raw, dict) else {}


def _set_pipeline_state(state: State, pipe: dict[str, Any]) -> None:
    state.set_extra(_PIPELINE_STATE_KEY, pipe, source='ContextPipeline')


def should_skip_compaction(
    state: State,
    boundary_compact_cooldown: int,
    *,
    force: bool,
) -> bool:
    if force:
        return False
    # Decay the consecutive-condensation counter if no real LLM step
    # has been recorded recently. This defends against error paths that
    # skip ``note_llm_step`` and would otherwise leave compaction
    # permanently disabled.
    from backend.context.context_pipeline.helpers import (
        maybe_decay_consecutive_condensation_counter,
    )

    maybe_decay_consecutive_condensation_counter(state)
    pipe = _pipeline_state(state)
    if pipe.get(_CONSECUTIVE_CONDENSATION_KEY, 0) >= 2:
        return True
    last = pipe.get(_LAST_BOUNDARY_COMPACT_KEY)
    if isinstance(last, (int, float)):
        if (time.time() - last) < boundary_compact_cooldown:
            return True
    skip_until = pipe.get(_SKIP_COMPACTION_UNTIL_KEY)
    if isinstance(skip_until, int):
        history = list(getattr(state, 'history', []))
        latest_id = getattr(history[-1], 'id', None) if history else None
        if isinstance(latest_id, int) and latest_id < skip_until:
            return True
    ineffective_until = pipe.get(_INEFFECTIVE_COMPACT_UNTIL_KEY)
    if isinstance(ineffective_until, (int, float)) and time.time() < ineffective_until:
        return True
    return False


def mark_just_compacted(state: State) -> None:
    pipe = _pipeline_state(state)
    pipe[_JUST_COMPACTED_KEY] = True
    _set_pipeline_state(state, pipe)


def clear_ineffective_compaction_backoff(state: State) -> None:
    pipe = _pipeline_state(state)
    pipe.pop(_SKIP_COMPACTION_UNTIL_KEY, None)
    pipe.pop(_INEFFECTIVE_COMPACT_STREAK_KEY, None)
    pipe.pop(_INEFFECTIVE_COMPACT_UNTIL_KEY, None)
    _set_pipeline_state(state, pipe)


def increment_condensation_counter(state: State) -> None:
    pipe = _pipeline_state(state)
    count = pipe.get(_CONSECUTIVE_CONDENSATION_KEY, 0)
    if not isinstance(count, int):
        count = 0
    pipe[_CONSECUTIVE_CONDENSATION_KEY] = count + 1
    _set_pipeline_state(state, pipe)


def record_llm_compact_attempt(state: State) -> None:
    pipe = _pipeline_state(state)
    pipe[_LAST_LLM_COMPACT_KEY] = time.time()
    _set_pipeline_state(state, pipe)


def llm_cooldown_elapsed(state: State, llm_compact_cooldown: int) -> bool:
    pipe = _pipeline_state(state)
    last = pipe.get(_LAST_LLM_COMPACT_KEY)
    if not isinstance(last, (int, float)):
        return True
    return (time.time() - last) >= llm_compact_cooldown


def record_boundary_compact(
    state: State,
    history: list[Event],
    action: CondensationAction,
) -> None:
    clear_ineffective_compaction_backoff(state)
    pipe = _pipeline_state(state)
    pipe[_LAST_BOUNDARY_COMPACT_KEY] = time.time()
    _set_pipeline_state(state, pipe)
    post_events = project_after_compact_boundary(
        _synthetic_history_after_action(history, action)
    )
    record_post_compact_baseline(state, post_events)


# --------------------------------------------------------------------------- #
# Continuity gate — validate that compaction preserves critical facts
# --------------------------------------------------------------------------- #


def action_meets_effectiveness(
    events: list[Event],
    action: CondensationAction,
    budget: ContextBudget,
    state: State,
    llm_config: object | None,
) -> bool:
    if len(action.pruned) < DEFAULT_COMPACT_MIN_PRUNED_EVENTS:
        return False
    pre_tokens = budget.estimated_tokens
    post_events = project_after_compact_boundary(
        _synthetic_history_after_action(events, action)
    )
    post_budget = ContextBudget.from_events(
        post_events, llm_config=llm_config, state=state
    )
    return (
        pre_tokens - post_budget.estimated_tokens
    ) >= DEFAULT_COMPACT_MIN_TOKEN_REDUCTION


def passes_effectiveness_gate(
    history: list[Event],
    events: list[Event],
    action: CondensationAction,
    budget: ContextBudget,
    state: State,
    llm_config: object | None,
) -> bool:
    if len(action.pruned) < DEFAULT_COMPACT_MIN_PRUNED_EVENTS:
        return False
    post_events = project_after_compact_boundary(
        _synthetic_history_after_action(history, action)
    )
    post_budget = ContextBudget.from_events(
        post_events, llm_config=llm_config, state=state
    )
    return (
        budget.estimated_tokens - post_budget.estimated_tokens
    ) >= DEFAULT_COMPACT_MIN_TOKEN_REDUCTION


def evaluate_continuity_gate(
    state: State,
    history: list[Event],
    action: CondensationAction,
) -> _ContinuityGateDecision:
    if not action.summary:
        return _ContinuityGateDecision(
            passed=True,
            canonical_ok=True,
            fingerprint='no_summary',
            missing=(),
            score=1.0,
            matched=0,
            total=0,
        )
    restored_parts = [action.summary]
    try:
        canonical = load_canonical_state(state=state)
        canonical_rendered = render_canonical_state_for_prompt(canonical)
        if canonical_rendered:
            restored_parts.append(canonical_rendered)
    except Exception:
        logger.debug('Canonical continuity render failed', exc_info=True)
    snapshot_text = build_compaction_summary(state=state)
    if snapshot_text:
        restored_parts.append(snapshot_text)
    restored = '\n\n'.join(part for part in restored_parts if part.strip())
    passed, result = compaction_passes_continuity_gate(history, restored)
    canonical_result = validate_canonical_state_for_compaction(
        load_canonical_state(state=state),
        history,
    )
    if not canonical_result.ok:
        logger.warning(
            'Compaction canonical continuity failed: missing=%s',
            ', '.join(canonical_result.missing),
        )
        return _ContinuityGateDecision(
            passed=False,
            canonical_ok=False,
            fingerprint='canonical:' + '|'.join(sorted(canonical_result.missing)),
            missing=tuple(canonical_result.missing),
            score=result.score,
            matched=result.matched,
            total=result.total,
        )
    if not passed:
        missing_items = tuple(
            f'{fact.category}:{fact.key[:80]}' for fact in result.missing[:8]
        )
        logger.warning(
            'Compaction continuity metric score=%.2f matched=%d/%d missing=%s '
            '(boundary rejected)',
            result.score,
            result.matched,
            result.total,
            ', '.join(missing_items) or 'none',
        )
        return _ContinuityGateDecision(
            passed=False,
            canonical_ok=True,
            fingerprint='continuity:' + '|'.join(sorted(missing_items)),
            missing=missing_items,
            score=result.score,
            matched=result.matched,
            total=result.total,
        )
    if result.missing:
        logger.info(
            'Compaction continuity telemetry score=%.2f matched=%d/%d missing=%d',
            result.score,
            result.matched,
            result.total,
            len(result.missing),
        )
    return _ContinuityGateDecision(
        passed=True,
        canonical_ok=True,
        fingerprint='ok',
        missing=(),
        score=result.score,
        matched=result.matched,
        total=result.total,
    )


def resolve_continuity_or_fallback(
    state: State,
    history: list[Event],
    events: list[Event],
    action: CondensationAction,
    budget: ContextBudget,
    llm_config: object | None,
) -> CondensationAction | None:
    decision = evaluate_continuity_gate(state, history, action)
    if not decision.passed:
        missing_items = ', '.join(
            f'{fact.category}:{fact.key[:80]}' for fact in decision.missing[:5]
        ) if decision.missing else 'none'
        logger.warning(
            'Compaction continuity metric score=%.2f matched=%d/%d '
            'missing=%s (accepting anyway)',
            decision.score, decision.matched, decision.total, missing_items,
        )
    return action


# --------------------------------------------------------------------------- #
# Compaction Engine — runs the 5a→5b→5c→5d fallback chain
# --------------------------------------------------------------------------- #


class _CompactionEngine:
    """Stateless compaction runner — instantiated once by ContextPipeline.

    Delegates to the structured compactor LLM, session memory, or deterministic
    truncation in order of preference.
    """

    def __init__(
        self,
        *,
        llm_registry: LLMRegistry,
        config: ContextPipelineConfig,
        get_structured_compactor: Any = None,
    ) -> None:
        self._llm_registry = llm_registry
        self._config = config
        self._get_structured_compactor_cb = get_structured_compactor

    async def run(
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

        llm_allowed = (
            self._config.allow_llm_hot_path
            and (
                critical
                or llm_cooldown_elapsed(
                    state, self._config.llm_compact_cooldown_seconds
                )
            )
            if hasattr(self._config, 'llm_compact_cooldown_seconds')
            else (
                self._config.allow_llm_hot_path
                and (critical or llm_cooldown_elapsed(state, 300))
            )
        )
        if llm_allowed:
            action = await self._llm_structured_compaction(
                events, state, budget=budget, llm_config=llm_config
            )
            if action is not None and action.summary:
                logger.info('ContextPipeline: LLM structured compaction (5b)')
                record_llm_compact_attempt(state)
                return action
        elif not self._config.allow_llm_hot_path:
            logger.debug('ContextPipeline: 5b skipped (allow_llm_hot_path=False)')
        else:
            logger.info('ContextPipeline: 5b skipped (llm compact cooldown)')

        if session_memory_exists(state=state):
            action = self._session_memory_compaction(
                state, events, budget=budget, llm_config=llm_config
            )
            if action is not None and action_meets_effectiveness(
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
            state, history, events, budget=budget, llm_config=llm_config
        )

    async def _llm_structured_compaction(
        self,
        events: list[Event],
        state: State,
        *,
        budget: ContextBudget | None = None,
        llm_config: object | None = None,
    ) -> CondensationAction | None:
        compactor = (
            self._get_structured_compactor_cb(state)
            if self._get_structured_compactor_cb
            else None
        )
        if compactor is None:
            logger.info(
                'ContextPipeline: 5b skipped (no structured compactor / llm_config)'
            )
            return None
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
                # Canonical task state is maintained deterministically by
                # reduce_events_into_state (pipeline.py); the prose compactor
                # no longer produces a canonical patch.
                return action
            logger.info(
                'ContextPipeline: 5b produced no summary (pruned=%d events=%d max_size=%d)',
                len(action.pruned) if action is not None else 0,
                len(events),
                getattr(compactor, 'max_size', 0),
            )
        return None

    def _session_memory_compaction(
        self,
        state: State,
        events: list[Event],
        *,
        budget: ContextBudget,
        llm_config: object | None,
    ) -> CondensationAction | None:
        summary = build_compaction_summary(state=state)
        if not summary.strip():
            return None
        tail = _select_compaction_tail(
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

    def _degraded_compaction(
        self,
        state: State,
        history: list[Event],
        events: list[Event],
        *,
        budget: ContextBudget,
        llm_config: object | None,
    ) -> CondensationAction:
        tail = _select_compaction_tail(
            events,
            budget,
            llm_config=llm_config,
            tail_ratio=DEFAULT_DEGRADED_COMPACT_TAIL_RATIO,
        )
        summary = build_compaction_summary(state=state)
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


