"""Event-classification helpers for :class:`_AppRendererEventProcessorMixin`.

These two predicates decide whether an event belongs to the live-thinking
stream (so the renderer should not yet commit its buffered response) and
whether the agent is currently running with full autonomy (used to decide
whether to surface confirm/clarification prompts to the user).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.ledger.action import AgentThinkAction, StreamingChunkAction
from backend.ledger.observation import AgentThinkObservation
from backend.orchestration.autonomy import normalize_autonomy_level

if TYPE_CHECKING:
    from backend.cli.tui._app_renderer_event_processor_mixin import (
        _AppRendererEventProcessorMixin,
    )


def _is_live_thinking_event(
    orch: '_AppRendererEventProcessorMixin',
    event: Any,
) -> bool:
    if isinstance(event, AgentThinkAction):
        if bool(getattr(event, 'suppress_cli', False)):
            return False
        thought = getattr(event, 'thought', '') or getattr(event, 'content', '')
        source_tool = getattr(event, 'source_tool', '') or ''
        kind = getattr(event, 'kind', '') or ''
        intent = orch._classify_thinking_text(
            thought, source_tool=source_tool, kind=kind
        )
        return intent.kind == 'thinking'
    if isinstance(event, AgentThinkObservation):
        thought = getattr(event, 'thought', '') or getattr(event, 'content', '')
        kind = getattr(event, 'kind', '') or ''
        intent = orch._classify_thinking_text(thought, kind=kind)
        return intent.kind == 'thinking'
    return isinstance(event, StreamingChunkAction)


def _is_full_autonomy(orch: '_AppRendererEventProcessorMixin') -> bool:
    controller = getattr(orch._tui, '_controller', None)
    ac = getattr(controller, 'autonomy_controller', None)
    if ac is not None:
        raw_level = getattr(ac, 'autonomy_level', '')
        return normalize_autonomy_level(raw_level) == 'full'
    hud = getattr(orch._tui, '_hud', None)
    state = getattr(hud, 'state', None)
    return normalize_autonomy_level(getattr(state, 'autonomy_level', '')) == 'full'
