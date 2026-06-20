"""Split submodule — see package facade for public API."""

from __future__ import annotations

from typing import TYPE_CHECKING

import backend.context.context_pipeline as _cp
from backend.context.canonical_state import (
    load_canonical_state,
    render_canonical_state_for_prompt,
    validate_canonical_state_for_compaction,
)
from backend.context.compactor.compact_boundary import project_after_compact_boundary
from backend.context.context_budget import ContextBudget
from backend.context.context_pipeline.helpers import (
    _pruned_ids,
    _shrink_tail_for_token_reduction,
    _synthetic_history_after_action,
)
from backend.context.context_pipeline.types import (
    _COMPACTION_TARGET_RATIO,
    _CONTINUITY_REJECTION_FP_KEY,
    _CONTINUITY_REJECTION_STREAK_KEY,
    _DETERMINISTIC_FALLBACK_THRESHOLD,
    _ContinuityGateDecision,
)
from backend.context.continuity_eval import compaction_passes_continuity_gate
from backend.core.constants import (
    DEFAULT_COMPACT_MIN_PRUNED_EVENTS,
    DEFAULT_COMPACT_MIN_TOKEN_REDUCTION,
)
from backend.core.logging.logger import app_logger as logger
from backend.ledger.action.agent import CondensationAction
from backend.ledger.event import Event

if TYPE_CHECKING:
    from backend.orchestration.state.state import State


class ContextPipelineGatesMixin:
    """ContextPipeline methods (mixin)."""

    def _action_meets_effectiveness(
        self,
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
            _synthetic_history_after_action(
                events,
                action,
            )
        )
        post_budget = _cp.ContextBudget.from_events(
            post_events, llm_config=llm_config, state=state
        )
        return (
            pre_tokens - post_budget.estimated_tokens
        ) >= DEFAULT_COMPACT_MIN_TOKEN_REDUCTION

    def _passes_effectiveness_gate(
        self,
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
        post_budget = _cp.ContextBudget.from_events(
            post_events, llm_config=llm_config, state=state
        )
        token_reduction = budget.estimated_tokens - post_budget.estimated_tokens
        return token_reduction >= DEFAULT_COMPACT_MIN_TOKEN_REDUCTION

    def _passes_continuity_gate(
        self, state: State, history: list[Event], action: CondensationAction
    ) -> bool:
        return self._evaluate_continuity_gate(state, history, action).passed

    def _resolve_continuity_or_fallback(
        self,
        state: State,
        history: list[Event],
        events: list[Event],
        action: CondensationAction,
        budget: ContextBudget,
        llm_config: object | None,
    ) -> CondensationAction | None:
        gate_passed = self._passes_continuity_gate(state, history, action)
        if gate_passed:
            self._clear_continuity_rejection(state)
            return action
        decision = self._evaluate_continuity_gate(state, history, action)
        if decision.passed:
            decision = _ContinuityGateDecision(
                passed=False,
                canonical_ok=True,
                fingerprint='continuity:forced_false',
                missing=(),
                score=decision.score,
                matched=decision.matched,
                total=decision.total,
            )
        fallback = self._deterministic_fallback_after_rejection(
            state,
            history,
            events,
            budget,
            llm_config,
            decision,
        )
        return fallback

    def _evaluate_continuity_gate(
        self, state: State, history: list[Event], action: CondensationAction
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
        snapshot_text = _cp.build_compaction_summary(state=state)
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

    def _deterministic_fallback_after_rejection(
        self,
        state: State,
        history: list[Event],
        events: list[Event],
        budget: ContextBudget,
        llm_config: object | None,
        decision: _ContinuityGateDecision,
    ) -> CondensationAction | None:
        streak = self._record_continuity_rejection(state, decision)
        if not decision.canonical_ok or streak < _DETERMINISTIC_FALLBACK_THRESHOLD:
            return None
        fallback = self._build_deterministic_canonical_compaction(
            state,
            history,
            events,
            budget,
            llm_config,
        )
        if fallback is None:
            return None
        if not self._passes_effectiveness_gate(
            history, events, fallback, budget, state, llm_config
        ):
            return None
        logger.warning(
            'Compaction continuity rejected twice for same fingerprint; '
            'committing deterministic canonical fallback (pruned=%d)',
            len(fallback.pruned),
        )
        self._clear_continuity_rejection(state)
        return fallback

    def _build_deterministic_canonical_compaction(
        self,
        state: State,
        history: list[Event],
        events: list[Event],
        budget: ContextBudget,
        llm_config: object | None,
    ) -> CondensationAction | None:
        try:
            canonical = load_canonical_state(state=state)
            summary_parts = [
                render_canonical_state_for_prompt(canonical, char_budget=6000)
            ]
        except Exception:
            logger.debug('Canonical fallback summary render failed', exc_info=True)
            summary_parts = []
        audit = _cp.build_compaction_summary(state=state)
        if audit.strip():
            summary_parts.append('Compaction audit evidence:\n' + audit.strip()[:4000])
        summary = '\n\n'.join(part for part in summary_parts if part.strip())
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
            history=history,
            budget=budget,
            state=state,
            llm_config=llm_config,
            summary=summary,
        )
        pruned = _pruned_ids(events, tail)
        if len(pruned) < DEFAULT_COMPACT_MIN_PRUNED_EVENTS:
            return None
        return CondensationAction(
            pruned_event_ids=sorted(pruned),
            summary=summary,
            summary_offset=0,
        )

    def _record_continuity_rejection(
        self,
        state: State,
        decision: _ContinuityGateDecision,
    ) -> int:
        pipe = self._pipeline_state(state)
        previous = pipe.get(_CONTINUITY_REJECTION_FP_KEY)
        streak = pipe.get(_CONTINUITY_REJECTION_STREAK_KEY, 0)
        if previous != decision.fingerprint or not isinstance(streak, int):
            streak = 0
        streak += 1
        pipe[_CONTINUITY_REJECTION_FP_KEY] = decision.fingerprint
        pipe[_CONTINUITY_REJECTION_STREAK_KEY] = streak
        state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')
        logger.info(
            'Compaction continuity rejection recorded (streak=%d fingerprint=%s)',
            streak,
            decision.fingerprint[:160],
        )
        return streak

    def _clear_continuity_rejection(self, state: State) -> None:
        pipe = self._pipeline_state(state)
        changed = False
        for key in (_CONTINUITY_REJECTION_FP_KEY, _CONTINUITY_REJECTION_STREAK_KEY):
            if key in pipe:
                pipe.pop(key, None)
                changed = True
        if changed:
            state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')
