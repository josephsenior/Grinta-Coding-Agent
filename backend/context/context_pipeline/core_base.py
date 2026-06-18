"""Split submodule — see package facade for public API."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Self

import backend.context.context_pipeline as _cp
from backend.context.compaction.compact_boundary import project_after_compact_boundary
from backend.context.compaction.microcompact import apply_microcompact
from backend.context.compaction.pre_condensation_snapshot import (
    extract_snapshot,
    save_snapshot,
)
from backend.context.context_budget import ContextBudget
from backend.context.memory.session_context import bind_session_context
from backend.context.tool_result_storage import (
    apply_frozen_tool_replacements,
    apply_tool_result_budget,
)
from backend.core.constants import (
    DEFAULT_BOUNDARY_COMPACT_COOLDOWN_SECONDS,
    DEFAULT_LLM_COMPACT_COOLDOWN_SECONDS,
    DEFAULT_MICROCOMPACT_PRESERVE_RECENT,
)
from backend.core.logger import app_logger as logger
from backend.inference.capabilities.context_limits import limits_from_config
from backend.ledger.event import Event

if TYPE_CHECKING:
    from backend.core.config.compactor_config import ContextPipelineConfig
    from backend.inference.llm_registry import LLMRegistry
    from backend.orchestration.state.state import State


class _EmptyState:
    extra_data: dict[str, Any] = {}

    def set_extra(self, *args, **kwargs) -> None:
        pass


class ContextPipelineBaseMixin:
    """ContextPipeline base initialization and layer helpers."""

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
    ) -> Self:
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
        budget = _cp.ContextBudget.from_events(
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


__all__ = ['ContextPipelineBaseMixin', '_EmptyState']
