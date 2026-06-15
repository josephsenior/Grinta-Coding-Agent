"""Observation renderers — mcp domain."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from backend.cli._typing import ObservationRenderersHost

    _ObservationRenderersBase = ObservationRenderersHost
else:
    _ObservationRenderersBase = object


from backend.cli._typing import ObservationRenderersHost
from backend.cli.display.tool_call_display import (
    mcp_result_syntax_extras,
    mcp_result_user_preview,
)
from backend.cli.display.transcript import (
    format_activity_result_secondary,
)
from backend.cli.orient_tools import (
    ORIENT_MCP_TOOL_NAMES,
    OrientLineModel,
    mcp_observation_model,
)
from backend.ledger.observation import (
    MCPObservation,
)

logger = logging.getLogger(__name__)


class _ObsMcpMixin(_ObservationRenderersBase):
    def _render_mcp_observation(self, obs: MCPObservation) -> None:
        self._stop_reasoning()
        content = getattr(obs, 'content', '')
        name = getattr(obs, 'name', '')
        if name in ORIENT_MCP_TOOL_NAMES:
            pending = getattr(self, '_pending_orient_line', None)
            pending_model = pending if isinstance(pending, OrientLineModel) else None
            model = mcp_observation_model(obs, pending_model)
            if model is not None:
                self._pending_orient_line = None
                self._append_orient_line(model)
            return
        friendly = mcp_result_user_preview(content)
        extras = mcp_result_syntax_extras(content)
        pending = cast(Any, self._take_pending_activity_card('mcp'))
        if pending is not None:
            self._render_pending_activity_card(
                pending,
                result_message=friendly or None,
                result_kind='neutral',
                extra_lines=extras,
            )
        elif friendly:
            self._append_history(
                format_activity_result_secondary(friendly, kind='neutral')
            )

    @staticmethod
    def _orient_mcp_result(name: str, content: str) -> str | None:
        """Extract result metric from orient MCP tool responses."""
        s = (content or '').strip()
        if not s:
            return None
        try:
            data = json.loads(s)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None
        if isinstance(data, dict):
            # Check for error payload
            error = data.get('error') or data.get('isError')
            if error:
                return 'failed'
            # Try to extract count from various payload shapes
            for key in ('total_count', 'count', 'matches', 'total'):
                v = data.get(key)
                if isinstance(v, int):
                    if v == 0:
                        return 'no results' if name in ('web_search',) else 'no results'
                    return f'{v} results'
            # Check items/results array
            for key in ('items', 'results', 'entries', 'documents', 'content'):
                items = data.get(key)
                if isinstance(items, list):
                    count = len(items)
                    if count == 0:
                        return 'no results'
                    return f'{count} results'
        if isinstance(data, list):
            count = len(data)
            if count == 0:
                return 'no results'
            return f'{count} results'
        return None
