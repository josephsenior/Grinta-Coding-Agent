"""MCP event handlers for the TUI renderer."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.cli.event_rendering.unified_renderer import ActivityRenderer
from backend.cli.tool_display.orient_tools import (
    ORIENT_MCP_TOOL_NAMES,
    OrientLineModel,
    mcp_action_model,
    mcp_observation_model,
)
from backend.cli.tui.renderer.helpers.mcp import mcp_content_is_error
from backend.ledger.action import MCPAction
from backend.ledger.observation import MCPObservation

if TYPE_CHECKING:
    from backend.cli.tui.renderer.mixins.event_processor import (
        RendererEventProcessorMixin,
    )


def _handle_mcp_action(orch: 'RendererEventProcessorMixin', event: MCPAction) -> None:
    orient = mcp_action_model(event)
    if orient is not None:
        orch._pending_mcp_card = orient
        orch._pending_exploration_meta = None
        return
    card = ActivityRenderer.mcp_activity_card(event.name, event.arguments)
    widget = orch._write_record_card(card, processing=True)
    orch._pending_mcp_card = widget
    orch._pending_exploration_meta = card.meta_lines or None


def _handle_mcp_observation(
    orch: 'RendererEventProcessorMixin', event: MCPObservation
) -> None:
    content = event.content or ''
    if event.name in ORIENT_MCP_TOOL_NAMES:
        pending = (
            orch._pending_mcp_card
            if isinstance(orch._pending_mcp_card, OrientLineModel)
            else None
        )
        model = mcp_observation_model(event, pending)
        if model is not None:
            orch._write_orient_line(model)
        orch._pending_mcp_card = None
        orch._pending_exploration_meta = None
        return
    is_error = mcp_content_is_error(content)
    card = ActivityRenderer.mcp_activity_card(
        event.name,
        event.arguments,
        result=content,
        success=not is_error,
        error=content if is_error else None,
    )
    if card.meta_lines:
        meta = list(card.meta_lines)
    else:
        meta = getattr(orch, '_pending_exploration_meta', None)
    if meta:
        card.meta_lines = meta
    orch._render_exploration_card(
        card,
        content=content,
        pending_attr='_pending_mcp_card',
        force_err=is_error,
    )
    orch._pending_mcp_card = None
    orch._pending_exploration_meta = None
