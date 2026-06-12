"""Unified context compaction pipeline — one ordered path for every LLM step."""

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
from backend.context.compact_boundary import project_after_compact_boundary
from backend.context.compaction_finalizer import finalize_compaction_artifacts
from backend.context.compactor.compactor import Compaction
from backend.context.condensed_history import CondensedHistory
from backend.context.context_budget import ContextBudget, record_post_compact_baseline
from backend.context.context_packet import (
    CONTEXT_PACKET_MARKER,
    build_context_packet_observation,
)
from backend.context.continuity_eval import compaction_passes_continuity_gate
from backend.context.microcompact import apply_microcompact
from backend.context.pre_condensation_snapshot import (
    delete_staging_snapshot,
    extract_snapshot,
    save_snapshot,
)
from backend.context.prompt_window import select_prompt_events
from backend.context.session_context import bind_session_context
from backend.context.session_memory import (
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
from backend.inference.context_limits import limits_from_config
from backend.ledger.action.agent import CondensationAction
from backend.ledger.event import Event

if TYPE_CHECKING:
    from backend.core.config.compactor_config import ContextPipelineConfig
    from backend.inference.llm_registry import LLMRegistry
    from backend.orchestration.state.state import State

_LAST_LLM_COMPACT_KEY = 'last_llm_compact_attempt'
_LAST_BOUNDARY_COMPACT_KEY = 'last_boundary_compact_at'
_JUST_COMPACTED_KEY = 'just_compacted'
_SKIP_COMPACTION_UNTIL_KEY = 'skip_compaction_until_event_id'
_INEFFECTIVE_COMPACT_STREAK_KEY = 'ineffective_compact_streak'
_INEFFECTIVE_COMPACT_UNTIL_KEY = 'ineffective_compact_until'
_CONSECUTIVE_CONDENSATION_KEY = 'consecutive_condensation_steps'
_CONTINUITY_REJECTION_FP_KEY = 'last_continuity_rejection_fingerprint'
_CONTINUITY_REJECTION_STREAK_KEY = 'continuity_rejection_streak'
_DETERMINISTIC_FALLBACK_THRESHOLD = 2
_COMPACTION_TARGET_RATIO = 0.7


@dataclass
class PipelineStepResult:
    """Processed events for prompt build plus optional pending condensation."""

    events: list[Event]
    pending_action: CondensationAction | None = None
    compacted: bool = False


@dataclass(frozen=True)
class _ContinuityGateDecision:
    passed: bool
    canonical_ok: bool
    fingerprint: str
    missing: tuple[str, ...]
    score: float
    matched: int
    total: int


class ContextPipeline:
    """Fixed-order context pipeline replacing compactor strategy roulette."""

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

    @classmethod
    def from_config(
        cls,
        config: ContextPipelineConfig,
        llm_registry: LLMRegistry,
        *,
        condensation_recorder: Callable[[], None] | None = None,
    ) -> ContextPipeline:
        from backend.core.pydantic_compat import model_dump_with_options

        kwargs = model_dump_with_options(
            config,
            exclude={'type', 'llm_config', 'allow_llm_hot_path'},
        )
        return cls(
            llm_registry=llm_registry,
            config=config,
            condensation_recorder=condensation_recorder,
            **kwargs,
        )

    def _record_pressure_condensation(self) -> None:
        if self._condensation_recorder is None:
            return
        try:
            self._condensation_recorder()
        except Exception:
            logger.debug('Memory pressure record_condensation failed', exc_info=True)

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
        events = apply_microcompact(events, preserve_recent=self._preserve_recent)
        return events

    def should_emit_compaction_status(self, state: State) -> bool:
        history = list(getattr(state, 'history', []))
        if not history:
            return False
        llm_config = self._llm_config(state)
        events = self._project_layers_1_to_3(history, state, apply_tool_budget=False)
        budget = ContextBudget.from_events(events, llm_config=llm_config, state=state)
        view = getattr(state, 'view', None)
        explicit = bool(getattr(view, 'unhandled_condensation_request', False))
        turn_signals = getattr(state, 'turn_signals', None)
        memory_pressure = getattr(turn_signals, 'memory_pressure', None)
        return bool(
            budget.should_autocompact
            or explicit
            or (isinstance(memory_pressure, str) and memory_pressure.strip())
        )

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
            turn_signals.prewarmed_compaction = None  # type: ignore[union-attr]
            action = prewarmed.action
            if isinstance(action, CondensationAction):
                budget = ContextBudget.from_events(
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
                        finalize_compaction_artifacts(state=state)
                        self._mark_just_compacted(state)
                        self._record_boundary_compact(state, history, action)
                        self._increment_condensation_counter(state)
                        logger.info(
                            'ContextPipeline used pre-warmed compaction in %.3fs',
                            time.perf_counter() - started,
                        )
                        return CondensedHistory([], action)

        events = post_boundary
        budget = ContextBudget.from_events(events, llm_config=llm_config, state=state)
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

        if self._should_skip_compaction(state, force=force):
            delete_staging_snapshot(state=state)
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
            delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)

        if not self._passes_effectiveness_gate(
            history, events, action, budget, state, llm_config
        ):
            logger.warning(
                'Compaction ineffective (pruned=%d); skipping boundary commit',
                len(action.pruned),
            )
            self._set_skip_compaction(state)
            delete_staging_snapshot(state=state)
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
            delete_staging_snapshot(state=state)
            return CondensedHistory(history, None)
        action = resolved_action

        finalize_compaction_artifacts(state=state)
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
            pipe = state.extra_data.get('context_pipeline_state', {})
            just_compacted = bool(pipe.get(_JUST_COMPACTED_KEY))
            if just_compacted:
                pipe = dict(pipe)
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
            return events
        return window.events

    async def prewarm_compaction(self, state: State) -> Compaction | None:
        """Run 5b compaction off the hot path for foreground reuse."""
        if not self._config.allow_llm_hot_path:
            return None
        bind_session_context(state=state)
        history = list(getattr(state, 'history', []))
        events = self._project_layers_1_to_3(history, state, apply_tool_budget=False)
        if not events:
            return None
        llm_config = self._llm_config(state)
        budget = ContextBudget.from_events(events, llm_config=llm_config, state=state)
        action = await self._llm_structured_compaction(
            events, state, budget=budget, llm_config=llm_config
        )
        if action is None or not action.summary:
            return None
        return Compaction(action=action)

    def note_llm_step(self, state: State) -> None:
        """Reset condensation-loop counters after a real LLM step."""
        pipe = dict(state.extra_data.get('context_pipeline_state', {}))
        pipe[_CONSECUTIVE_CONDENSATION_KEY] = 0
        state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')

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

        if session_memory_exists(state=state):
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

    def _llm_cooldown_elapsed(self, state: State) -> bool:
        pipe = state.extra_data.get('context_pipeline_state', {})
        last = pipe.get(_LAST_LLM_COMPACT_KEY)
        if not isinstance(last, (int, float)):
            return True
        return (time.time() - last) >= self._llm_compact_cooldown

    def _record_llm_compact_attempt(self, state: State) -> None:
        pipe = dict(state.extra_data.get('context_pipeline_state', {}))
        pipe[_LAST_LLM_COMPACT_KEY] = time.time()
        state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')

    def _mark_just_compacted(self, state: State) -> None:
        pipe = dict(state.extra_data.get('context_pipeline_state', {}))
        pipe[_JUST_COMPACTED_KEY] = True
        state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')

    def _pipeline_state(self, state: State) -> dict[str, Any]:
        raw = state.extra_data.get('context_pipeline_state', {})
        return dict(raw) if isinstance(raw, dict) else {}

    def _should_skip_compaction(self, state: State, *, force: bool) -> bool:
        if force:
            return False
        pipe = self._pipeline_state(state)
        if pipe.get(_CONSECUTIVE_CONDENSATION_KEY, 0) >= 2:
            return True
        last = pipe.get(_LAST_BOUNDARY_COMPACT_KEY)
        if isinstance(last, (int, float)):
            if (time.time() - last) < self._boundary_compact_cooldown:
                return True
        skip_until = pipe.get(_SKIP_COMPACTION_UNTIL_KEY)
        if isinstance(skip_until, int):
            history = list(getattr(state, 'history', []))
            latest_id = getattr(history[-1], 'id', None) if history else None
            if isinstance(latest_id, int) and latest_id < skip_until:
                return True
        ineffective_until = pipe.get(_INEFFECTIVE_COMPACT_UNTIL_KEY)
        if (
            isinstance(ineffective_until, (int, float))
            and time.time() < ineffective_until
        ):
            return True
        return False

    def _set_skip_compaction(self, state: State) -> None:
        apply_ineffective_compaction_backoff(state)

    def _clear_ineffective_compaction_backoff(self, state: State) -> None:
        pipe = self._pipeline_state(state)
        pipe.pop(_SKIP_COMPACTION_UNTIL_KEY, None)
        pipe.pop(_INEFFECTIVE_COMPACT_STREAK_KEY, None)
        pipe.pop(_INEFFECTIVE_COMPACT_UNTIL_KEY, None)
        pipe.pop(_CONTINUITY_REJECTION_FP_KEY, None)
        pipe.pop(_CONTINUITY_REJECTION_STREAK_KEY, None)
        state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')

    def _increment_condensation_counter(self, state: State) -> None:
        pipe = self._pipeline_state(state)
        count = pipe.get(_CONSECUTIVE_CONDENSATION_KEY, 0)
        if not isinstance(count, int):
            count = 0
        pipe[_CONSECUTIVE_CONDENSATION_KEY] = count + 1
        state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')

    def _record_boundary_compact(
        self,
        state: State,
        history: list[Event],
        action: CondensationAction,
    ) -> None:
        self._clear_ineffective_compaction_backoff(state)
        pipe = self._pipeline_state(state)
        pipe[_LAST_BOUNDARY_COMPACT_KEY] = time.time()
        state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')
        post_events = project_after_compact_boundary(
            _synthetic_history_after_action(history, action)
        )
        record_post_compact_baseline(state, post_events)

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
        post_budget = ContextBudget.from_events(
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
        post_budget = ContextBudget.from_events(
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
        audit = build_compaction_summary(state=state)
        if audit.strip():
            summary_parts.append('Compaction audit evidence:\n' + audit.strip()[:4000])
        summary = '\n\n'.join(part for part in summary_parts if part.strip())
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

    @staticmethod
    def _extract_pre_condensation_snapshot(state: State, history: list[Event]) -> None:
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


class _EmptyState:
    extra_data: dict[str, Any] = {}

    def set_extra(self, *args, **kwargs) -> None:
        pass


def _latest_event_id(events: list[Event]) -> int | None:
    ids = [getattr(event, 'id', None) for event in events]
    int_ids = [event_id for event_id in ids if isinstance(event_id, int)]
    return max(int_ids) if int_ids else None


def _drop_stale_prompt_state_artifacts(events: list[Event]) -> list[Event]:
    """Remove old prompt-only state blocks before injecting the fresh packet."""
    markers = (
        CONTEXT_PACKET_MARKER,
        '<POST_COMPACT_RESTORE>',
        '<RESTORED_CONTEXT>',
    )
    filtered: list[Event] = []
    for event in events:
        content = getattr(event, 'content', None)
        if isinstance(content, str) and any(marker in content for marker in markers):
            continue
        filtered.append(event)
    return filtered


def apply_ineffective_compaction_backoff(state: State) -> None:
    """Backoff compaction after an ineffective prune (shared with orchestrator)."""
    pipe = dict(getattr(state, 'extra_data', {}).get('context_pipeline_state', {}))
    history = list(getattr(state, 'history', []))
    latest_id = getattr(history[-1], 'id', None) if history else None
    if not isinstance(latest_id, int):
        return
    streak = pipe.get(_INEFFECTIVE_COMPACT_STREAK_KEY, 0)
    if not isinstance(streak, int):
        streak = 0
    streak += 1
    skip_events = min(
        DEFAULT_INEFFECTIVE_COMPACT_SKIP_EVENTS * streak,
        DEFAULT_INEFFECTIVE_COMPACT_MAX_SKIP_EVENTS,
    )
    pipe[_SKIP_COMPACTION_UNTIL_KEY] = latest_id + skip_events
    pipe[_INEFFECTIVE_COMPACT_STREAK_KEY] = streak
    pipe[_INEFFECTIVE_COMPACT_UNTIL_KEY] = (
        time.time() + DEFAULT_INEFFECTIVE_COMPACT_BACKOFF_SECONDS * min(streak, 4)
    )
    state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')
    logger.info(
        'Compaction backoff: skip until event id>=%d (%d new events) for %.0fs (streak=%d)',
        pipe[_SKIP_COMPACTION_UNTIL_KEY],
        skip_events,
        pipe[_INEFFECTIVE_COMPACT_UNTIL_KEY] - time.time(),
        streak,
    )


def _projected_compaction_token_reduction(
    events: list[Event],
    tail: list[Event],
    *,
    history: list[Event],
    budget: ContextBudget,
    state: State,
    llm_config: object | None,
    summary: str,
) -> int:
    pruned = _pruned_ids(events, tail)
    if len(pruned) < DEFAULT_COMPACT_MIN_PRUNED_EVENTS:
        return 0
    action = CondensationAction(
        pruned_event_ids=sorted(pruned),
        summary=summary or 'summary',
        summary_offset=0,
    )
    post_events = project_after_compact_boundary(
        _synthetic_history_after_action(history, action)
    )
    post_budget = ContextBudget.from_events(
        post_events, llm_config=llm_config, state=state
    )
    return budget.estimated_tokens - post_budget.estimated_tokens


def _shrink_tail_for_token_reduction(
    events: list[Event],
    tail: list[Event],
    *,
    history: list[Event],
    budget: ContextBudget,
    state: State,
    llm_config: object | None,
    summary: str,
    min_reduction: int = DEFAULT_COMPACT_MIN_TOKEN_REDUCTION,
) -> list[Event]:
    """Drop oldest non-protected tail events until projected token savings meet the gate."""
    from backend.context.prompt_window import _protected_summary_events

    protected = _protected_summary_events(events)
    protected_ids = {id(event) for event in protected}
    current = list(tail)
    summary_text = summary.strip() or 'summary'

    while len(current) > len(protected):
        reduction = _projected_compaction_token_reduction(
            events,
            current,
            history=history,
            budget=budget,
            state=state,
            llm_config=llm_config,
            summary=summary_text,
        )
        if reduction >= min_reduction:
            break
        removed = False
        for index, event in enumerate(current):
            if id(event) in protected_ids:
                continue
            current.pop(index)
            removed = True
            break
        if not removed:
            break
    return current


def _select_compaction_tail(
    events: list[Event],
    budget: ContextBudget,
    *,
    llm_config: object | None,
    tail_ratio: float = _COMPACTION_TARGET_RATIO,
) -> list[Event]:
    from backend.context.prompt_window import (
        _enforce_min_tool_loops,
        _protected_summary_events,
        estimate_prompt_events_tokens,
    )

    protected = _protected_summary_events(events)
    protected_ids = {id(event) for event in protected}
    target_tokens = int(budget.autocompact_threshold * tail_ratio)
    min_tail_floor = min(DEFAULT_PROMPT_MIN_TAIL_TOKENS, target_tokens)
    tail: list[Event] = list(protected)
    tail_ids = set(protected_ids)
    tail_tokens = estimate_prompt_events_tokens(tail)

    for event in reversed(events):
        if id(event) in tail_ids:
            continue
        event_tokens = estimate_prompt_events_tokens([event])
        if tail_tokens + event_tokens > target_tokens and tail_tokens >= min_tail_floor:
            break
        tail.insert(0, event)
        tail_ids.add(id(event))
        tail_tokens += event_tokens
        if tail_tokens >= target_tokens:
            break

    tail = _enforce_min_tool_loops(
        tail,
        events,
        protected,
        min_tool_loops=DEFAULT_PROMPT_MIN_TOOL_LOOPS,
    )
    if estimate_prompt_events_tokens(tail) < min_tail_floor:
        kept_ids = {id(item) for item in tail}
        for event in reversed(events):
            if id(event) in kept_ids:
                continue
            tail.insert(0, event)
            kept_ids.add(id(event))
            if estimate_prompt_events_tokens(tail) >= min_tail_floor:
                break
    del llm_config
    return tail


def _pruned_ids(events: list[Event], tail: list[Event]) -> set[int]:
    tail_ids = {
        event_id
        for event in tail
        if isinstance((event_id := getattr(event, 'id', None)), int)
    }
    pruned: set[int] = set()
    for event in events:
        event_id = getattr(event, 'id', None)
        if isinstance(event_id, int) and event_id not in tail_ids:
            pruned.add(event_id)
    return pruned


def _synthetic_history_after_action(
    history: list[Event], action: CondensationAction
) -> list[Event]:
    return [*history, action]


__all__ = [
    'ContextPipeline',
    'PipelineStepResult',
    'apply_ineffective_compaction_backoff',
]
