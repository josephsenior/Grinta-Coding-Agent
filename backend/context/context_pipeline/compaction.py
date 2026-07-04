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
from backend.context.context_budget import (
    ContextBudget,
    estimate_boundary_event_tokens,
    record_post_compact_baseline,
)
from backend.context.context_pipeline.helpers import _synthetic_history_after_action
from backend.context.context_pipeline.types import (
    _CONSECUTIVE_CONDENSATION_KEY,
    _JUST_COMPACTED_KEY,
    _MAX_LLM_COMPACTION_ATTEMPTS,
    _POST_COMPACT_TRUE_TOKENS_KEY,
    _WILL_RETRIGGER_HYSTERESIS_KEY,
    _ContinuityGateDecision,
)
from backend.context.continuity_eval import compaction_passes_continuity_gate
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
    explicit: bool = False,
    budget: ContextBudget | None = None,
) -> bool:
    """Return True when compaction should not run again yet.

    * ``just_compacted`` — same-turn double ``prepare_step`` loop
    * post-compact snapshot — already compacted at this token level; wait until
      new events push the estimate above the last committed post-compact count

    Explicit ``/compact`` and CRITICAL memory pressure (``force=True``) bypass
    both guards.
    """
    _ = boundary_compact_cooldown
    if explicit or force:
        return False

    pipe = _pipeline_state(state)
    if bool(pipe.get(_JUST_COMPACTED_KEY)):
        return True

    post_compact = pipe.get(_POST_COMPACT_TRUE_TOKENS_KEY)
    if (
        budget is not None
        and isinstance(post_compact, int)
        and post_compact > 0
        and budget.estimated_tokens <= post_compact
    ):
        return True
    return False


def mark_just_compacted(state: State) -> None:
    pipe = _pipeline_state(state)
    pipe[_JUST_COMPACTED_KEY] = True
    _set_pipeline_state(state, pipe)


def increment_condensation_counter(state: State) -> None:
    pipe = _pipeline_state(state)
    count = pipe.get(_CONSECUTIVE_CONDENSATION_KEY, 0)
    if not isinstance(count, int):
        count = 0
    pipe[_CONSECUTIVE_CONDENSATION_KEY] = count + 1
    _set_pipeline_state(state, pipe)


def record_boundary_compact(
    state: State,
    history: list[Event],
    action: CondensationAction,
    *,
    budget: ContextBudget | None = None,
    llm_config: object | None = None,
) -> None:
    post_events = project_after_compact_boundary(
        _synthetic_history_after_action(history, action)
    )
    record_post_compact_baseline(state, post_events)
    if budget is not None:
        post_tokens = estimate_boundary_event_tokens(post_events, llm_config=llm_config)
        pipe = _pipeline_state(state)
        pipe[_POST_COMPACT_TRUE_TOKENS_KEY] = post_tokens
        if post_tokens >= budget.autocompact_threshold:
            pipe[_WILL_RETRIGGER_HYSTERESIS_KEY] = True
            logger.warning(
                'will_retrigger_next_turn: post_compact_tokens=%d '
                'autocompact_threshold=%d',
                post_tokens,
                budget.autocompact_threshold,
            )
        else:
            pipe.pop(_WILL_RETRIGGER_HYSTERESIS_KEY, None)
        _set_pipeline_state(state, pipe)


# --------------------------------------------------------------------------- #
# Continuity gate — validate that compaction preserves critical facts
# --------------------------------------------------------------------------- #


def passes_effectiveness_gate(
    history: list[Event],
    events: list[Event],
    action: CondensationAction,
    budget: ContextBudget,
    state: State,
    llm_config: object | None,
) -> bool:
    """Accept any LLM compaction that produced a non-empty summary."""
    _ = history, events, budget, state, llm_config
    return bool((action.summary or '').strip())


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
    """Evaluate continuity telemetry; always returns *action* (telemetry-only)."""
    decision = evaluate_continuity_gate(state, history, action)
    if not decision.passed:
        missing_items = ', '.join(decision.missing[:5]) if decision.missing else 'none'
        logger.warning(
            'Compaction continuity metric score=%.2f matched=%d/%d '
            'missing=%s (accepting anyway)',
            decision.score,
            decision.matched,
            decision.total,
            missing_items,
        )
    return action


# --------------------------------------------------------------------------- #
# Compaction Engine — LLM structured summary only
# --------------------------------------------------------------------------- #


class _CompactionEngine:
    """Stateless compaction runner — instantiated once by ContextPipeline.

    Uses only the structured-summary LLM compactor. No deterministic fallback.
    Persisted task/criteria state is re-injected separately after compaction.
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
            'ContextPipeline: LLM compaction triggered '
            '(should_autocompact=%s force=%s critical=%s dynamic_history_tokens=%d '
            'threshold=%d fixed_prompt_reserve=%d)',
            budget.should_autocompact,
            force,
            critical,
            budget.estimated_tokens,
            budget.autocompact_threshold,
            budget.fixed_prompt_reserve_tokens,
        )

        for attempt in range(1, _MAX_LLM_COMPACTION_ATTEMPTS + 1):
            try:
                action = await self._llm_structured_compaction(
                    events, state, budget=budget, llm_config=llm_config
                )
            except Exception as exc:
                logger.warning(
                    'ContextPipeline: LLM compaction attempt %d/%d failed: %s',
                    attempt,
                    _MAX_LLM_COMPACTION_ATTEMPTS,
                    exc,
                )
                continue
            if action is not None and (action.summary or '').strip():
                logger.info(
                    'ContextPipeline: LLM compaction succeeded after %d attempt(s)',
                    attempt,
                )
                return action
            logger.info(
                'ContextPipeline: LLM compaction attempt %d/%d produced no summary',
                attempt,
                _MAX_LLM_COMPACTION_ATTEMPTS,
            )

        logger.error(
            'ContextPipeline: LLM compaction exhausted %d attempt(s) without summary',
            _MAX_LLM_COMPACTION_ATTEMPTS,
        )
        return None

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
            raise RuntimeError(
                'LLM compaction unavailable: no structured compactor / llm_config'
            )
        compactor._pipeline_state = state  # type: ignore[attr-defined]
        from backend.context.view import View

        view = View(events=events)
        result = await compactor.get_compaction(view)
        if isinstance(result, Compaction):
            action = result.action
            if action is not None and (action.summary or '').strip():
                return action
            logger.info(
                'ContextPipeline: structured compactor returned no summary '
                '(pruned=%d events=%d max_size=%d)',
                len(action.pruned) if action is not None else 0,
                len(events),
                getattr(compactor, 'max_size', 0),
            )
        return None
