"""Action renderers — mcp domain."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.cli._typing import ActionRenderersHost

    _ActionRenderersBase = ActionRenderersHost
else:
    _ActionRenderersBase = object


from backend.cli._typing import ActionRenderersHost
from backend.cli.display.layout_tokens import (
    ACTIVITY_CARD_TITLE_MCP,
)
from backend.cli.display.tool_call_display import friendly_verb_for_tool
from backend.cli.event_rendering.actions.dispatch import _ORIENT_MCP_NAMES
from backend.cli.event_rendering.text_utils import (
    sync_reasoning_after_tool_line as _sync_reasoning_after_tool_line,
)
from backend.cli.tool_display.orient_tools import (
    mcp_action_model,
)
from backend.ledger.action import (  # noqa: E402
    MCPAction,
)


class _ActionMcpMixin(_ActionRenderersBase):
    def _render_mcp_action(self, action: MCPAction) -> None:
        name = getattr(action, 'name', 'tool')
        raw_args = getattr(action, 'arguments', None) or {}
        if name in _ORIENT_MCP_NAMES:
            model = mcp_action_model(action)
            if model is not None:
                self._queue_orient_line(model)
            thought = getattr(action, 'thought', '') or ''
            _sync_reasoning_after_tool_line(self._reasoning, f'{name}', thought)
            self.refresh()
            return
        self._flush_pending_tool_cards()
        # Non-orient MCP tools use the existing card mechanism
        verb = friendly_verb_for_tool(name, raw_args)
        args_str = ', '.join(
            f'{k}={repr(v)[:40]}' for k, v in list(raw_args.items())[:2]
        )
        if len(args_str) > 80:
            args_str = args_str[:77] + '…'
        detail = f'{name}({args_str})' if args_str else name
        self._buffer_pending_activity(
            title=ACTIVITY_CARD_TITLE_MCP,
            verb=verb,
            detail=detail,
            kind='mcp',
            badge_label='mcp',
        )
        thought = getattr(action, 'thought', '') or ''
        _sync_reasoning_after_tool_line(self._reasoning, f'MCP {name}', thought)
        self.refresh()
