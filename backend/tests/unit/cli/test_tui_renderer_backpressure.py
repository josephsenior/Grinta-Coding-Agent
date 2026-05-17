from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rich.text import Text

from backend.cli.tui import app as tui_app


@pytest.mark.asyncio
async def test_tui_renderer_pending_events_are_bounded(monkeypatch):
    monkeypatch.setattr(tui_app, '_TUI_PENDING_EVENT_LIMIT', 3)
    loop = MagicMock()
    renderer = tui_app.TUIRenderer(
        console=SimpleNamespace(width=100),
        hud=SimpleNamespace(
            state=SimpleNamespace(mcp_servers=0), bundled_skill_count=0
        ),
        reasoning=SimpleNamespace(),
        tui=SimpleNamespace(),
        loop=loop,
    )

    for event in range(5):
        renderer._on_event(event)

    assert list(renderer._pending_events) == [2, 3, 4]
    assert renderer._pending_events_dropped == 2
    assert loop.call_soon_threadsafe.call_count == 5


@pytest.mark.asyncio
async def test_tui_renderer_history_is_bounded(monkeypatch):
    monkeypatch.setattr(tui_app, '_TUI_HISTORY_RENDER_LIMIT', 3)
    display = MagicMock()
    sidebar = MagicMock()
    fake_tui = SimpleNamespace(
        _config=None,
        _get_display=lambda: display,
        _get_sidebar=lambda: sidebar,
        _scroll_to_bottom=MagicMock(),
    )
    renderer = tui_app.TUIRenderer(
        console=SimpleNamespace(width=100),
        hud=SimpleNamespace(
            state=SimpleNamespace(mcp_servers=0), bundled_skill_count=0
        ),
        reasoning=SimpleNamespace(),
        tui=fake_tui,
        loop=asyncio.get_running_loop(),
    )

    renderer.add_to_history(Text('one'))
    renderer.add_to_history(Text('two'))
    renderer.add_to_history(Text('three'))

    assert len(renderer._history) <= 3
    assert renderer._history_items_dropped > 0
    assert display.update.called
