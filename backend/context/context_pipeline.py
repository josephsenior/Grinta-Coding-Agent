"""Unified context compaction pipeline — one ordered path for every LLM step."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from backend.context.compact_boundary import project_after_compact_boundary
from backend.context.compactor.compactor import Compaction
from backend.context.context_budget import ContextBudget
from backend.context.continuity_eval import compaction_passes_continuity_gate
from backend.context.microcompact import apply_microcompact
from backend.context.post_compact_restore import inject_post_compact_restore
from backend.context.pre_condensation_snapshot import (
    commit_snapshot,
    delete_staging_snapshot,
    extract_snapshot,
    load_snapshot,
    save_snapshot,
)
from backend.context.prompt_window import select_prompt_events
from backend.context.session_memory import (
    build_compaction_summary,
    maybe_update,
    session_memory_exists,
)
from backend.context.tool_result_storage import (
    apply_frozen_tool_replacements,
    apply_tool_result_budget,
)
from backend.context.working_set import build_working_set_observation, sync_snapshot_to_working_memory
from backend.core.constants import (
    DEFAULT_LLM_COMPACT_COOLDOWN_SECONDS,
    DEFAULT_MICROCOMPACT_PRESERVE_RECENT,
    DEFAULT_PROMPT_MIN_TAIL_TOKENS,
    DEFAULT_PROMPT_MIN_TOOL_LOOPS,
)
from backend.core.logger import app_logger as logger
from backend.ledger.action.agent import CondensationAction
from backend.ledger.event import Event

from backend.context.condensed_history import CondensedHistory

if TYPE_CHECKING:
    from backend.core.config.compactor_config import ContextPipelineConfig
    from backend.inference.llm_registry import LLMRegistry
    from backend.orchestration.state.state import State

_LAST_LLM_COMPACT_KEY = 'last_llm_compact_attempt'
_JUST_COMPACTED_KEY = 'just_compacted'


@dataclass
class PipelineStepResult:
    """Processed events for prompt build plus optional pending condensation."""

    events: list[Event]
    pending_action: CondensationAction | None = None
    compacted: bool = False


class ContextPipeline:
    """Fixed-order context pipeline replacing compactor strategy roulette."""

    def __init__(
        self,
        *,
        llm_registry: LLMRegistry,
        config: ContextPipelineConfig,
        preserve_recent: int = DEFAULT_MICROCOMPACT_PRESERVE_RECENT,
        llm_compact_cooldown_seconds: int = DEFAULT_LLM_COMPACT_COOLDOWN_SECONDS,
    ) -> None:
        self._llm_registry = llm_registry
        self._config = config
        self._preserve_recent = preserve_recent
        self._llm_compact_cooldown = llm_compact_cooldown_seconds
        self._structured_compactor = None

    @classmethod
    def from_config(
        cls,
        config: ContextPipelineConfig,
        llm_registry: LLMRegistry,
    ) -> ContextPipeline:
        from backend.core.pydantic_compat import model_dump_with_options

        kwargs = model_dump_with_options(
            config,
            exclude={'type', 'llm_config', 'allow_llm_hot_path'},
        )
        return cls(llm_registry=llm_registry, config=config, **kwargs)

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

    def _project_layers_1_to_3(
        self,
        history: list[Event],
        state: State,
        *,
        apply_tool_budget: bool = True,
    ) -> list[Event]:
        events = project_after_compact_boundary(history)
        events = apply_frozen_tool_replacements(events, state)
        if apply_tool_budget:
            events = apply_tool_result_budget(events)
        events = apply_microcompact(events, preserve_recent=self._preserve_recent)
        return events

    def _inject_working_set(self, events: list[Event], history: list[Event]) -> list[Event]:
        working_set = build_working_set_observation(history)
        if working_set is None:
            return events
        return [working_set, *events]

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
        history = list(getattr(state, 'history', []))
        llm_config = self._llm_config(state)

        self._extract_pre_condensation_snapshot(state, history)
        maybe_update(state, history, llm_config=llm_config)

        turn_signals = getattr(state, 'turn_signals', None)
        prewarmed = getattr(turn_signals, 'prewarmed_compaction', None)
        if prewarmed is not None and isinstance(prewarmed, Compaction):
            turn_signals.prewarmed_compaction = None  # type: ignore[union-attr]
            action = prewarmed.action
            if isinstance(action, CondensationAction):
                self._log_continuity_metric(history, action)
                commit_snapshot()
                sync_snapshot_to_working_memory(load_snapshot())
                self._mark_just_compacted(state)
                logger.info(
                    'ContextPipeline used pre-warmed compaction in %.3fs',
                    time.perf_counter() - started,
                )
                return CondensedHistory([], action)

        events = self._project_layers_1_to_3(history, state, apply_tool_budget=False)
        budget = ContextBudget.from_events(events, llm_config=llm_config, state=state)
        view = getattr(state, 'view', None)
        explicit = bool(getattr(view, 'unhandled_condensation_request', False))
        memory_pressure = getattr(turn_signals, 'memory_pressure', None)
        pressure_active = isinstance(memory_pressure, str) and bool(memory_pressure.strip())

        if not (budget.should_autocompact or explicit or pressure_active):
            delete_staging_snapshot()
            return CondensedHistory(history, None)

        action = await self._run_compaction(
            state,
            history,
            events,
            budget,
            llm_config=llm_config,
            force=explicit or pressure_active,
        )
        if action is None:
            delete_staging_snapshot()
            return CondensedHistory(history, None)

        self._log_continuity_metric(history, action)
        commit_snapshot()
        sync_snapshot_to_working_memory(load_snapshot())
        self._mark_just_compacted(state)
        if pressure_active:
            state.ack_memory_pressure(source='ContextPipeline')
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
        events = self._project_layers_1_to_3(history, state or _EmptyState(), apply_tool_budget=True)
        events = self._inject_working_set(events, history)

        just_compacted = False
        if state is not None:
            pipe = state.extra_data.get('context_pipeline_state', {})
            just_compacted = bool(pipe.get(_JUST_COMPACTED_KEY))
            if just_compacted:
                pipe = dict(pipe)
                pipe[_JUST_COMPACTED_KEY] = False
                state.set_extra('context_pipeline_state', pipe, source='ContextPipeline')

        events = inject_post_compact_restore(events, history, just_compacted=just_compacted)

        window = select_prompt_events(
            events,
            llm_config,
            emergency_only=True,
            tool_budget_applied=True,
        )
        return window.events

    async def _run_compaction(
        self,
        state: State,
        history: list[Event],
        events: list[Event],
        budget: ContextBudget,
        *,
        llm_config: object | None,
        force: bool,
    ) -> CondensationAction | None:
        if not events:
            return None

        if session_memory_exists():
            action = self._session_memory_compaction(events, llm_config=llm_config)
            if action is not None:
                post_events = project_after_compact_boundary(
                    _synthetic_history_after_action(history, action)
                )
                post_budget = ContextBudget.from_events(
                    post_events, llm_config=llm_config, state=state
                )
                if not post_budget.should_autocompact or force:
                    logger.info('ContextPipeline: session-memory compaction (5a)')
                    return action

        if self._config.allow_llm_hot_path and self._llm_cooldown_elapsed(state):
            action = await self._llm_structured_compaction(events, state)
            if action is not None and action.summary:
                logger.info('ContextPipeline: LLM structured compaction (5b)')
                self._record_llm_compact_attempt(state)
                return action

        logger.warning(
            'ContextPipeline: degraded boundary compaction (5c) — mandatory fallback'
        )
        return self._degraded_compaction(events, llm_config=llm_config)

    def _session_memory_compaction(
        self,
        events: list[Event],
        *,
        llm_config: object | None,
    ) -> CondensationAction | None:
        summary = build_compaction_summary()
        if not summary.strip():
            return None
        tail = _select_preserved_tail(events, llm_config=llm_config)
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
    ) -> CondensationAction | None:
        compactor = self._get_structured_compactor(state)
        if compactor is None:
            return None
        from backend.context.view import View

        view = View(events=events)
        try:
            result = await compactor.get_compaction(view)
        except Exception as exc:
            logger.warning('LLM structured compaction failed: %s', exc)
            return None
        if isinstance(result, Compaction):
            return result.action
        return None

    def _degraded_compaction(
        self,
        events: list[Event],
        *,
        llm_config: object | None,
    ) -> CondensationAction:
        tail = _select_preserved_tail(events, llm_config=llm_config)
        pruned = _pruned_ids(events, tail)
        summary = build_compaction_summary()
        if not summary.strip():
            from backend.context.compactor.strategies.amortized_pruning_compactor import (
                AmortizedPruningCompactor,
            )

            pruned_events = [event for event in events if getattr(event, 'id', None) in pruned]
            summary = AmortizedPruningCompactor._build_recovery_summary(pruned_events)
        return CondensationAction(
            pruned_event_ids=sorted(pruned),
            summary=summary,
            summary_offset=0,
        )

    def _get_structured_compactor(self, state: State):
        if self._structured_compactor is not None:
            return self._structured_compactor
        llm_config = self._config.llm_config
        if llm_config is None:
            return None
        from backend.context.compactor.strategies.structured_summary_compactor import (
            StructuredSummaryCompactor,
        )
        from backend.core.config.compactor_config import StructuredSummaryCompactorConfig
        from backend.core.config.llm_config import LLMConfig

        if isinstance(llm_config, LLMConfig):
            llm_cfg = llm_config
        else:
            llm_cfg = self._llm_registry.config.get_llm_config(llm_config)
        cfg = StructuredSummaryCompactorConfig(
            llm_config=llm_cfg,
            max_size=max(100, len(getattr(state, 'history', [])) // 2),
            keep_first=0,
        )
        self._structured_compactor = StructuredSummaryCompactor.from_config(
            cfg, self._llm_registry
        )
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

    def _log_continuity_metric(
        self, history: list[Event], action: CondensationAction
    ) -> None:
        if not action.summary:
            return
        restored_parts = [action.summary]
        try:
            from backend.context.working_set import get_durable_context_block

            durable = get_durable_context_block(history)
            if durable:
                restored_parts.append(durable)
        except Exception:
            pass
        snapshot_text = build_compaction_summary()
        if snapshot_text:
            restored_parts.append(snapshot_text)
        restored = '\n\n'.join(part for part in restored_parts if part.strip())
        passed, result = compaction_passes_continuity_gate(history, restored)
        if not passed:
            missing = ', '.join(
                f'{fact.category}:{fact.key[:40]}' for fact in result.missing[:8]
            )
            logger.warning(
                'Compaction continuity metric score=%.2f matched=%d/%d missing=%s '
                '(logged only; boundary committed)',
                result.score,
                result.matched,
                result.total,
                missing or 'none',
            )

    @staticmethod
    def _extract_pre_condensation_snapshot(state: State, history: list[Event]) -> None:
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
            ):
                save_snapshot(snapshot)
        except Exception:
            logger.debug('Pre-condensation snapshot extraction failed', exc_info=True)


class _EmptyState:
    extra_data: dict[str, Any] = {}

    def set_extra(self, *args, **kwargs) -> None:
        pass


def _select_preserved_tail(
    events: list[Event],
    *,
    llm_config: object | None,
) -> list[Event]:
    from backend.context.prompt_window import (
        _enforce_min_tail_tokens,
        _enforce_min_tool_loops,
        _history_token_budget,
        _protected_summary_events,
    )

    protected = _protected_summary_events(events)
    selected = list(events[-max(DEFAULT_PROMPT_MIN_TOOL_LOOPS * 4, 40) :])
    budget = _history_token_budget(llm_config) or 120_000
    selected = _enforce_min_tool_loops(
        selected,
        events,
        protected,
        min_tool_loops=DEFAULT_PROMPT_MIN_TOOL_LOOPS,
    )
    selected = _enforce_min_tail_tokens(
        selected,
        events,
        protected,
        budget=budget,
        min_tail_tokens=DEFAULT_PROMPT_MIN_TAIL_TOKENS,
    )
    return selected


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


__all__ = ['ContextPipeline', 'PipelineStepResult']
