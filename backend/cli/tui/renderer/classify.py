"""Event-classification helpers for :class:`RendererEventProcessorMixin`.

These two predicates decide whether an event belongs to the live-thinking
stream (so the renderer should not yet commit its buffered response) and
whether the agent is currently running with full autonomy (used to decide
whether to surface confirm/clarification prompts to the user).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from backend.core.autonomy import normalize_autonomy_level
from backend.ledger.action import (
    AgentThinkAction,
    StreamingChunkAction,
    SystemHintAction,
)
from backend.ledger.observation import AgentThinkObservation

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _thinking_intent_matches(
    orch: 'RendererEventProcessorMixin',
    event: Any,
    *,
    use_source_tool: bool,
    check_suppress: bool,
    use_content_fallback: bool,
) -> bool:
    if check_suppress and bool(getattr(event, 'suppress_cli', False)):
        return False
    thought = getattr(event, 'thought', '') or ''
    if use_content_fallback:
        thought = thought or getattr(event, 'content', '')
    kind = getattr(event, 'kind', '') or ''
    if use_source_tool:
        source_tool = getattr(event, 'source_tool', '') or ''
        intent = orch._classify_thinking_text(
            thought, source_tool=source_tool, kind=kind
        )
    else:
        intent = orch._classify_thinking_text(thought, kind=kind)
    return intent.kind == 'thinking'


def _is_live_thinking_event(
    orch: 'RendererEventProcessorMixin',
    event: Any,
) -> bool:
    if isinstance(event, AgentThinkAction):
        return _thinking_intent_matches(
            orch,
            event,
            use_source_tool=True,
            check_suppress=True,
            use_content_fallback=True,
        )
    if isinstance(event, SystemHintAction):
        return _thinking_intent_matches(
            orch,
            event,
            use_source_tool=True,
            check_suppress=True,
            use_content_fallback=False,
        )
    if isinstance(event, AgentThinkObservation):
        return _thinking_intent_matches(
            orch,
            event,
            use_source_tool=False,
            check_suppress=False,
            use_content_fallback=True,
        )
    return isinstance(event, StreamingChunkAction)


def _is_full_autonomy(orch: 'RendererEventProcessorMixin') -> bool:
    controller = getattr(orch._tui, '_controller', None)
    ac = getattr(controller, 'autonomy_controller', None)
    if ac is not None:
        return normalize_autonomy_level(getattr(ac, 'autonomy_level', '')) == 'full'
    return False
