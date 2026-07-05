from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from rich.text import Text

from backend.cli.theme import CLR_REASONING_SNAP
from backend.cli.tui import app as tui_app
from backend.cli.tui.renderer import drain as _drain_mod
from backend.cli.tui.renderer.mixins import event_processor as _ep_mod
from backend.cli.tui.renderer.mixins import live as _live_mod
from backend.ledger.action import StreamingChunkAction


@pytest.mark.asyncio
async def test_tui_renderer_pending_events_are_bounded(monkeypatch):
    monkeypatch.setattr(_ep_mod, '_TUI_PENDING_EVENT_LIMIT', 3)
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
    assert renderer._pending_backpressure is True
    assert loop.call_soon_threadsafe.call_count == 5
    assert renderer._drain_scheduled is True


@pytest.mark.asyncio
async def test_tui_renderer_latches_drain_request_while_active():
    renderer = tui_app.TUIRenderer(
        console=SimpleNamespace(width=100),
        hud=SimpleNamespace(
            state=SimpleNamespace(mcp_servers=0), bundled_skill_count=0
        ),
        reasoning=SimpleNamespace(),
        tui=SimpleNamespace(),
        loop=asyncio.get_running_loop(),
    )
    renderer._async_drain_active = True

    await renderer.drain_events_async()

    assert renderer._drain_requested_while_active is True


@pytest.mark.asyncio
async def test_tui_renderer_history_is_bounded(monkeypatch):
    monkeypatch.setattr(
        'backend.cli.tui.constants._TUI_HISTORY_RENDER_LIMIT',
        3,
    )
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
async def test_tui_renderer_live_thinking_renders_in_main_panel_until_commit():
    display = MagicMock()
    fake_tui = SimpleNamespace(
        _config=None,
        _get_display=lambda: display,
        _get_sidebar=lambda: MagicMock(),
        query_one=MagicMock(),
        refresh=MagicMock(),
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

    assert display.clear.called
    assert display.write.called

    display.write.reset_mock()
    renderer.commit_live_thinking()

    assert display.write.called
    assert renderer._live_thinking_dirty is False
    assert renderer._live_thinking == ''


def test_tui_renderer_committed_thinking_uses_muted_reasoning_style():
    class Display:
        @staticmethod
        def should_follow_tail():
            return True

    class ThinkingWidget:
        _thoughts = ['dim thought']

        def finalize(self):
            pass

        def remove(self):
            pass

    fake_tui = SimpleNamespace(
        _config=None,
        _get_display=lambda: Display(),
        _get_sidebar=lambda: MagicMock(),
        query_one=MagicMock(),
        refresh=MagicMock(),
    )
    renderer = tui_app.TUIRenderer(
        console=SimpleNamespace(width=100),
        hud=SimpleNamespace(
            state=SimpleNamespace(mcp_servers=0), bundled_skill_count=0
        ),
        reasoning=SimpleNamespace(),
        tui=fake_tui,
        loop=MagicMock(),
    )
    renderer._live_thinking_widget = ThinkingWidget()
    renderer._live_thinking_dirty = True

    renderer.commit_live_thinking()

    snapshot = renderer._history[0]
    assert isinstance(snapshot, Text)
    assert any(span.style == CLR_REASONING_SNAP for span in snapshot.spans)


def test_live_follow_tail_rechecks_manual_scroll_before_repaint():
    callbacks = []

    class Display:
        _user_scrolled_away = False
        _suppress_scroll_sync = False
        scroll_calls = 0

        def call_after_refresh(self, callback):
            callbacks.append(callback)

        def scroll_end(self, **_kwargs):
            self.scroll_calls += 1

        def _release_programmatic_scroll(self):
            self._suppress_scroll_sync = False

    display = Display()
    renderer = tui_app.TUIRenderer(
        console=SimpleNamespace(width=100),
        hud=SimpleNamespace(
            state=SimpleNamespace(mcp_servers=0), bundled_skill_count=0
        ),
        reasoning=SimpleNamespace(),
        tui=SimpleNamespace(),
        loop=MagicMock(),
    )

    renderer._follow_transcript_tail_after_reflow(display)
    display._user_scrolled_away = True

    for callback in list(callbacks):
        callback()

    assert display.scroll_calls == 0
    assert display._suppress_scroll_sync is False


@pytest.mark.asyncio
async def test_tui_renderer_live_response_renders_in_main_panel_until_clear():
    display = MagicMock()
    fake_tui = SimpleNamespace(
        _config=None,
        _get_display=lambda: display,
        _get_sidebar=lambda: MagicMock(),
        query_one=MagicMock(),
        refresh=MagicMock(),
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

    renderer.update_live_response('partial answer')

    assert display.clear.called
    assert display.write.called
    assert renderer._live_response_dirty is True

    renderer.clear_live_response()

    assert renderer._live_response == ''
    assert renderer._live_response_dirty is False
    assert display.clear.call_count >= 2


@pytest.mark.asyncio
async def test_tui_renderer_coalesces_interim_streaming_chunks():
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

    renderer._on_event(StreamingChunkAction(chunk='a', accumulated='a', is_final=False))
    renderer._on_event(
        StreamingChunkAction(chunk='b', accumulated='ab', is_final=False)
    )
    renderer._on_event(
        StreamingChunkAction(chunk='c', accumulated='abc', is_final=False)
    )

    assert len(renderer._pending_events) == 1
    assert renderer._pending_events[0].accumulated == 'abc'
    assert renderer._pending_events_dropped == 0


def test_collapse_streaming_chunks_keeps_latest_snapshot_per_run():
    other = object()
    chunks = [
        StreamingChunkAction(chunk='a', accumulated='a', is_final=False),
        StreamingChunkAction(chunk='b', accumulated='ab', is_final=False),
        other,
        StreamingChunkAction(chunk='x', accumulated='x', is_final=False),
        StreamingChunkAction(chunk='y', accumulated='xy', is_final=True),
    ]

    collapsed = _drain_mod._collapse_streaming_chunks(chunks)

    assert len(collapsed) == 3
    assert collapsed[0].accumulated == 'ab'
    assert collapsed[1] is other
    assert collapsed[2].accumulated == 'xy'
    assert collapsed[2].is_final is True


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
    await asyncio.sleep(0.03)

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
