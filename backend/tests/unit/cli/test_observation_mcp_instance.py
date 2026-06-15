"""Instance tests for MCP observation mixin."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.cli.event_rendering.observations.mcp import _ObsMcpMixin
from backend.cli.orient_tools import OrientLineModel


class _Host(_ObsMcpMixin):
    def __init__(self) -> None:
        self._pending_orient_line = None
        self.orient_lines: list[OrientLineModel] = []
        self.history: list[str] = []
        self._append_orient_line = self.orient_lines.append
        self._stop_reasoning = MagicMock()
        self._take_pending_activity_card = lambda *_a, **_k: None
        self._render_pending_activity_card = MagicMock()
        self._append_history = lambda text: self.history.append(str(text))


def test_render_mcp_observation_orient_tool() -> None:
    host = _Host()
    host._pending_orient_line = OrientLineModel(
        tool='web_search',
        icon='⚐',
        verb='Searched',
        target='pytest docs',
        result='…',
    )
    obs = SimpleNamespace(
        name='web_search_exa',
        content='{"items": [1, 2]}',
    )
    host._render_mcp_observation(obs)
    assert host._pending_orient_line is None
    assert len(host.orient_lines) == 1
    assert host.orient_lines[0].result == '2 results'


def test_render_mcp_observation_non_orient_appends_preview() -> None:
    host = _Host()
    obs = SimpleNamespace(
        name='custom_tool',
        content='{"summary": "done"}',
    )
    host._render_mcp_observation(obs)
    assert host.orient_lines == []
    assert host.history
