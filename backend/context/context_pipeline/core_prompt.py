"""Split submodule — see package facade for public API."""

from __future__ import annotations

from typing import TYPE_CHECKING

import backend.context.context_pipeline as _cp
from backend.context.compactor.compactor import Compaction
from backend.context.context_pipeline.core_base import _EmptyState
from backend.context.context_pipeline.helpers import (
    _drop_stale_prompt_state_artifacts,
)
from backend.context.context_pipeline.types import (
    _CONSECUTIVE_CONDENSATION_KEY,
    _JUST_COMPACTED_KEY,
)
from backend.context.memory.session_context import bind_session_context
from backend.context.prompt.context_packet import (
    build_context_packet_observation,
)
from backend.context.prompt.prompt_window import select_prompt_events
from backend.core.constants import (
    DEFAULT_EMERGENCY_PROMPT_MIN_EVENTS,
)
from backend.core.logger import app_logger as logger
from backend.ledger.event import Event

if TYPE_CHECKING:
    from backend.orchestration.state.state import State


class ContextPipelinePromptMixin:
    """ContextPipeline methods (mixin)."""

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
        budget = _cp.ContextBudget.from_events(
            events, llm_config=llm_config, state=state
        )
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
