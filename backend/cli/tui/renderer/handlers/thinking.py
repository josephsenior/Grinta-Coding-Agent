"""Agent thinking action/observation handlers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.ledger.action import AgentThinkAction, SystemHintAction
from backend.ledger.observation import AgentThinkObservation

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _handle_agent_think_action(
    orch: 'RendererEventProcessorMixin', event: AgentThinkAction
) -> None:
    from backend.engine.response_processing import arguments_from_tool_call_metadata

    source_tool = getattr(event, 'source_tool', '') or ''
    thought = getattr(event, 'thought', '') or getattr(event, 'content', '')
    kind = getattr(event, 'kind', '') or ''
    tool_args = (
        arguments_from_tool_call_metadata(getattr(event, 'tool_call_metadata', None))
        if source_tool in ('grep', 'glob')
        else None
    )
    orch._render_thinking_payload(
        thought,
        source_tool=source_tool,
        kind=kind,
        tool_args=tool_args,
    )


def _handle_system_hint_action(
    orch: 'RendererEventProcessorMixin', event: SystemHintAction
) -> None:
    source_tool = getattr(event, 'source_tool', '') or ''
    thought = getattr(event, 'thought', '') or ''
    kind = getattr(event, 'kind', '') or ''
    orch._render_thinking_payload(
        thought,
        source_tool=source_tool,
        kind=kind,
    )


def _handle_agent_think_observation(
    orch: 'RendererEventProcessorMixin', event: AgentThinkObservation
) -> None:
    thought = getattr(event, 'thought', '') or getattr(event, 'content', '')
    kind = getattr(event, 'kind', '') or ''
    orch._render_thinking_payload(thought, kind=kind)
