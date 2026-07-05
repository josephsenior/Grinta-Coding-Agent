"""Compaction engine, continuity gate, and pipeline state helpers.

Extracted from the old mixin chain to simplify the ContextPipeline class.
All functions here are stateless — they operate on ``state.extra_data``
or receive their dependencies as parameters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.context.canonical_state import (
    load_canonical_state,
    render_canonical_state_for_prompt,
    validate_canonical_state_for_compaction,
)
from backend.context.compactor.compact_boundary import (
    find_last_condensation_action,
    find_pending_condensation_request,
    project_after_compact_boundary,
)
from backend.context.compactor.compactor import Compaction
from backend.context.context_budget import (
    ContextBudget,
    estimate_boundary_event_tokens,
)
from backend.context.context_pipeline.helpers import _synthetic_history_after_action
from backend.context.context_pipeline.types import (
    _EXPLICIT_COMPACT_DISMISSED_REQUEST_ID_KEY,
    _JUST_COMPACTED_KEY,
    _MAX_LLM_COMPACTION_ATTEMPTS,
    _POST_COMPACT_TRUE_TOKENS_KEY,
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


def has_actionable_explicit_request(state: State, history: list[Event]) -> bool:
    """True when history has an explicit request that has not already failed."""
    request = find_pending_condensation_request(history)
    if request is None:
        return False
    dismissed = _pipeline_state(state).get(_EXPLICIT_COMPACT_DISMISSED_REQUEST_ID_KEY)
    return dismissed != request.id


def dismiss_explicit_compaction_request(state: State, history: list[Event]) -> None:
    """Stop retrying an explicit request after compaction exhausts its attempts."""
    request = find_pending_condensation_request(history)
    if request is None:
        return
    pipe = _pipeline_state(state)
    pipe[_EXPLICIT_COMPACT_DISMISSED_REQUEST_ID_KEY] = request.id
    _set_pipeline_state(state, pipe)
    logger.warning(
        'ContextPipeline: explicit compaction request %d dismissed after failure',
        request.id,
    )


def should_skip_compaction(
    state: State,
    *,
    events: list[Event],
    llm_config: object,
    history: list[Event],
    explicit: bool = False,
) -> bool:
    """Return True when compaction should not run again yet.

    Guards (bypassed only by explicit ``/compact``):

    * ``just_compacted`` — same-turn double ``prepare_step`` loop
    * pending boundary — snapshot recorded but ``CondensationAction`` not in history
    * post-compact snapshot — boundary tokens still at or below last commit
    """
    if explicit:
        return False

    pipe = _pipeline_state(state)
    if bool(pipe.get(_JUST_COMPACTED_KEY)):
        return True

    post_compact = pipe.get(_POST_COMPACT_TRUE_TOKENS_KEY)
    if not isinstance(post_compact, int) or post_compact <= 0:
        return False

    if find_last_condensation_action(history) is None:
        logger.info(
            'ContextPipeline: skipping compaction (post_compact_snapshot=%d '
            'but CondensationAction not yet in history)',
            post_compact,
        )
        return True

    boundary_tokens = estimate_boundary_event_tokens(events, llm_config=llm_config)
    if boundary_tokens <= post_compact:
        logger.info(
            'ContextPipeline: skipping compaction (boundary_tokens=%d '
            'post_compact_snapshot=%d)',
            boundary_tokens,
            post_compact,
        )
        return True
    return False


def should_run_compaction(
    state: State,
    *,
    events: list[Event],
    budget: ContextBudget,
    history: list[Event],
    llm_config: object,
    explicit: bool = False,
) -> bool:
    """Return True when LLM compaction should run this step."""
    if should_skip_compaction(
        state,
        events=events,
        llm_config=llm_config,
        history=history,
        explicit=explicit,
    ):
        return False
    return bool(budget.should_autocompact or explicit)


def mark_just_compacted(state: State) -> None:
    pipe = _pipeline_state(state)
    pipe[_JUST_COMPACTED_KEY] = True
    _set_pipeline_state(state, pipe)


def record_boundary_compact(
    state: State,
    history: list[Event],
    action: CondensationAction,
    *,
    llm_config: object | None = None,
    post_events: list[Event] | None = None,
) -> None:
    if post_events is None:
        post_events = project_after_compact_boundary(
            _synthetic_history_after_action(history, action)
        )
    post_tokens = estimate_boundary_event_tokens(post_events, llm_config=llm_config)
    pipe = _pipeline_state(state)
    pipe[_POST_COMPACT_TRUE_TOKENS_KEY] = post_tokens
    _set_pipeline_state(state, pipe)
    logger.info(
        'ContextPipeline: recorded post-compact snapshot (boundary_tokens=%d)',
        post_tokens,
    )


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
    from backend.context.compactor.pre_condensation_snapshot import (
        extract_snapshot,
        format_snapshot_for_injection,
    )

    snapshot = extract_snapshot(history)
    restored_parts = [action.summary]
    try:
        canonical = load_canonical_state(state=state)
        files_touched = snapshot.get('files_touched', {})
        if (
            isinstance(files_touched, dict)
            and files_touched
            and not canonical.active_files
        ):
            from backend.context.canonical_state.ops import (
                reduce_snapshot_into_state,
                save_canonical_state,
            )
            from backend.context.canonical_state.private import _latest_event_id

            canonical = reduce_snapshot_into_state(
                snapshot,
                canonical,
                latest_event_id=_latest_event_id(history),
                source='continuity_gate',
            )
            save_canonical_state(canonical, state=state)
        canonical_rendered = render_canonical_state_for_prompt(canonical)
        if canonical_rendered:
            restored_parts.append(canonical_rendered)
    except Exception:
        logger.debug('Canonical continuity render failed', exc_info=True)
    try:
        snapshot_text = format_snapshot_for_injection(snapshot, state=state)
        if snapshot_text.strip():
            restored_parts.append(snapshot_text)
    except Exception:
        logger.debug('Snapshot continuity render failed', exc_info=True)
    restored = '\n\n'.join(part for part in restored_parts if part.strip())
    passed, result = compaction_passes_continuity_gate(history, restored)
    canonical_result = validate_canonical_state_for_compaction(
        load_canonical_state(state=state),
        history,
    )
    task_plan_source, ac_source = _continuity_source_labels(history)
    goal_context_chars = _goal_context_char_count(state)
    fuzzy_missing = tuple(
        f'{fact.category}:{fact.key[:80]}' for fact in result.missing[:8]
    )
    logger.info(
        'Compaction continuity telemetry canonical_missing=%s fuzzy_missing=%s '
        'goal_context_chars=%d task_plan_source=%s ac_source=%s score=%.2f',
        ', '.join(canonical_result.missing) or 'none',
        ', '.join(fuzzy_missing) or 'none',
        goal_context_chars,
        task_plan_source,
        ac_source,
        result.score,
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


def _continuity_source_labels(history: list[Event]) -> tuple[str, str]:
    from backend.context.compactor.pre_condensation_snapshot import extract_snapshot

    snapshot = extract_snapshot(history)
    task_source = 'none'
    task_plan = snapshot.get('task_plan')
    if isinstance(task_plan, dict) and task_plan.get('tasks'):
        task_source = 'events'
    else:
        try:
            from backend.core.task_tracker import TaskTracker

            if TaskTracker().load_from_file():
                task_source = 'json'
        except Exception:
            pass

    ac_source = 'none'
    acceptance = snapshot.get('acceptance_criteria')
    if isinstance(acceptance, dict) and acceptance.get('criteria'):
        ac_source = 'events'
    else:
        try:
            from backend.core.criteria.acceptance_criteria_store import (
                AcceptanceCriteriaStore,
            )

            if AcceptanceCriteriaStore().load_from_file():
                ac_source = 'json'
        except Exception:
            pass
    return task_source, ac_source


def _goal_context_char_count(state: State) -> int:
    try:
        from backend.context.context_pipeline.goal_context import (
            build_goal_context_for_compaction,
        )

        return len(build_goal_context_for_compaction(state=state) or '')
    except Exception:
        return 0


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
