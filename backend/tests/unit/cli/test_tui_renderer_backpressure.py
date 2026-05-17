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
    assert renderer._drain_scheduled is True


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
    assert display.write.called


@pytest.mark.asyncio
async def test_tui_renderer_live_thinking_uses_preview_until_commit():
    display = MagicMock()
    preview = MagicMock()
    fake_tui = SimpleNamespace(
        _config=None,
        _get_display=lambda: display,
        _get_sidebar=lambda: MagicMock(),
        _get_thinking_preview=lambda: preview,
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

    renderer.update_live_thinking('step 1')

    assert preview.update.called
    assert display.write.called is False

    renderer.commit_live_thinking()

    assert display.write.called
    assert renderer._live_thinking_dirty is False
    assert renderer._live_thinking == ''


@pytest.mark.asyncio
async def test_tui_renderer_schedules_single_drain_message_per_backlog():
    fake_tui = SimpleNamespace(post_message=MagicMock())
    renderer = tui_app.TUIRenderer(
        console=SimpleNamespace(width=100),
        hud=SimpleNamespace(
            state=SimpleNamespace(mcp_servers=0), bundled_skill_count=0
        ),
        reasoning=SimpleNamespace(),
        tui=fake_tui,
        loop=asyncio.get_running_loop(),
    )

    renderer._on_event('first')
    renderer._on_event('second')
    renderer._on_event('third')
    await asyncio.sleep(0)

    assert fake_tui.post_message.call_count == 1


@pytest.mark.asyncio
async def test_tui_renderer_wait_for_activity_drains_pending_events():
    display = MagicMock()
    sidebar = MagicMock()
    fake_tui = SimpleNamespace(
        _config=None,
        _get_display=lambda: display,
        _get_sidebar=lambda: sidebar,
        _scroll_to_bottom=MagicMock(),
        _render_hud_bar=MagicMock(),
        _write_log=MagicMock(),
        post_message=MagicMock(),
    )
    renderer = tui_app.TUIRenderer(
        console=SimpleNamespace(width=100),
        hud=SimpleNamespace(
            state=SimpleNamespace(mcp_servers=0, cost_usd=0), bundled_skill_count=0
        ),
        reasoning=SimpleNamespace(),
        tui=fake_tui,
        loop=asyncio.get_running_loop(),
    )

    renderer._on_event(object())
    await asyncio.sleep(0)

    state = await renderer.wait_for_activity(wait_timeout_sec=0.1)

    assert state is None
    assert not renderer._pending_events
    assert renderer._drain_scheduled is False
    assert fake_tui._write_log.called
