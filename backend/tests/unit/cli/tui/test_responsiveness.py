"""Regression coverage for message-pump stalls and expensive transcript trees."""

from __future__ import annotations

import asyncio
from collections import deque
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult
from textual.message import Message
from textual.screen import Screen
from textual.widgets import TextArea

from backend.cli.tui.renderer import drain, prep
from backend.cli.tui.screen.lifecycle import ScreenLifecycleMixin
from backend.cli.tui.widgets.diff_lines import DiffLines
from backend.cli.tui.widgets.small import RendererDrainRequested
from backend.cli.tui.widgets.unified_diff_view import UnifiedDiffView
from backend.ledger.action import MessageAction, StreamingChunkAction


@pytest.mark.asyncio
async def test_screen_accepts_input_while_drain_is_waiting():
    entered, release, pinged = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = 0

    async def slow_drain():
        nonlocal calls
        calls += 1
        entered.set()
        await release.wait()

    class Ping(Message):
        pass

    class TestScreen(Screen):
        on_renderer_drain_requested = ScreenLifecycleMixin.on_renderer_drain_requested
        _drain_renderer_background = ScreenLifecycleMixin._drain_renderer_background
        _is_unmounted = False
        _welcome_visible = False
        _renderer = SimpleNamespace(drain_events_async=slow_drain)

        def compose(self) -> ComposeResult:
            yield TextArea(id='input')

        def on_ping(self, message: Ping) -> None:
            pinged.set()

    app: App[None] = App()
    async with app.run_test() as pilot:
        screen = TestScreen()
        await app.push_screen(screen)
        screen.query_one(TextArea).focus()
        screen.post_message(RendererDrainRequested())
        await asyncio.wait_for(entered.wait(), timeout=2)
        for _ in range(20):
            screen.post_message(RendererDrainRequested())
        screen.post_message(Ping())
        try:
            await asyncio.wait_for(pinged.wait(), timeout=2)
            await asyncio.wait_for(pilot.press('h', 'i'), timeout=2)
            assert screen.query_one(TextArea).text == 'hi'
            assert calls == 1
        finally:
            release.set()
        await pilot.pause()
        assert calls == 2


@pytest.mark.asyncio
async def test_large_diff_mounts_constant_widgets_and_renders_visible_rows(monkeypatch):
    from textual.geometry import Offset
    from textual.selection import Selection

    patch = '@@ -0,0 +1,2500 @@\n' + '\n'.join(f'+line {i}' for i in range(2500))
    calls: list[int] = []
    original = DiffLines._line_text

    def counted(self, y, width=None):
        calls.append(y)
        return original(self, y, width)

    monkeypatch.setattr(DiffLines, '_line_text', counted)

    class DiffApp(App):
        def compose(self) -> ComposeResult:
            yield UnifiedDiffView(patch=patch, max_lines=3000, fill=True)

    async with DiffApp().run_test(size=(100, 30)) as pilot:
        view = pilot.app.query_one(UnifiedDiffView)
        lines = view.query_one(DiffLines)
        await pilot.pause()
        assert len(view.query('*')) < 10
        assert len(set(calls)) < 100
        assert len(lines._rows) >= 2500
        view.scroll_end(animate=False, immediate=True)
        await pilot.pause()
        assert len(lines._rows) - 1 in calls
        assert 'line 2499' in lines.render_line(len(lines._rows) - 1).text
        row_index = len(lines._rows) - 1
        plain = lines._line_text(row_index).plain
        start = plain.index('line 2499')
        selection = Selection(Offset(start, row_index), Offset(start + 9, row_index))
        assert lines.get_selection(selection) == ('line 2499', '\n')
        await pilot.resize_terminal(65, 20)
        await pilot.pause()
        assert len(view.query('*')) < 10


def test_backpressure_preserves_final_messages_and_tool_results():
    from backend.ledger.observation import CmdOutputObservation

    events = deque(
        [
            MessageAction(content='Complete response'),
            CmdOutputObservation(
                content='important result', command='test', exit_code=0
            ),
        ]
    )
    original = list(events)
    orch = SimpleNamespace(_pending_events_dropped=0)
    drain._make_backpressure_room(orch, events, 1)
    assert list(events) == original
    assert orch._pending_events_dropped == 0


def test_coalescing_never_crosses_a_final_stream_snapshot():
    final = StreamingChunkAction(accumulated='first complete', is_final=True)
    next_chunk = StreamingChunkAction(accumulated='next response', is_final=False)
    assert drain._collapse_streaming_chunks([final, next_chunk]) == [final, next_chunk]
    events = deque([final, next_chunk])
    assert drain._coalesce_pending_backlog(events) == 0


def test_terminal_output_deltas_are_not_replaced_by_later_output():
    from backend.ledger.observation.terminal import TerminalObservation

    events = deque(
        [
            TerminalObservation(session_id='shell', content='first output'),
            TerminalObservation(session_id='shell', content='second output'),
        ]
    )
    assert drain._coalesce_pending_backlog(events) == 0
    assert [event.content for event in events] == ['first output', 'second output']


@pytest.mark.asyncio
async def test_background_stream_prep_reuses_fences_without_painting():
    orch = SimpleNamespace(
        _streaming_render_cache={}, _apply_live_response_render=MagicMock()
    )
    first = 'Intro\n```python\nprint(1)\n```\n'
    await prep.prep_streaming_response_async(orch, first)
    frozen = list(orch._streaming_render_state.committed_parts)
    await prep.prep_streaming_response_async(orch, first + 'More words')
    assert all(
        a is b
        for a, b in zip(
            frozen, orch._streaming_render_state.committed_parts, strict=True
        )
    )
    orch._apply_live_response_render.assert_not_called()


def test_incremental_prep_resets_when_provider_replaces_committed_text():
    first = '```python\nprint(1)\n```'
    _, state = prep.prep_streaming_renderable_incremental(first, None)
    replacement = '```python\nprint(2)\n```'
    _, updated = prep.prep_streaming_renderable_incremental(replacement, state)
    assert updated.committed_text == replacement
    assert state.committed_text == first
    assert updated.committed_parts[0] is not state.committed_parts[0]


def test_pruned_history_preserves_content_without_retaining_widget():
    import gc
    import weakref

    from rich.markdown import Markdown
    from textual.widgets import Static

    from backend.cli.tui.renderer.mixins.display import RendererDisplayMixin

    content = Markdown('A **complete** message')
    widget = Static(content)
    reference = weakref.ref(widget)
    orch = SimpleNamespace(_history=deque([widget]))
    RendererDisplayMixin._release_history_widget(orch, widget)
    assert orch._history[0] is content
    del widget
    gc.collect()
    assert reference() is None


@pytest.mark.asyncio
async def test_clear_during_preparation_does_not_resurrect_old_batch(monkeypatch):
    orch = SimpleNamespace(_render_generation=0, _process_event=MagicMock())

    async def prepare(event_orch, event):
        event_orch._render_generation += 1

    monkeypatch.setattr(drain, '_preprocess_event_async', prepare)
    events = [MessageAction(content='old'), MessageAction(content='also old')]
    assert await drain._process_events_with_frame_budget(orch, events) == 2
    orch._process_event.assert_not_called()


@pytest.mark.asyncio
async def test_cancelled_drain_propagates_cancellation_with_pending_events(monkeypatch):
    from threading import Lock

    orch = SimpleNamespace(
        _async_drain_active=False,
        _pending_events=deque([MessageAction(content='first')]),
        _pending_events_dropped=0,
        _pending_lock=Lock(),
        _tui=MagicMock(),
    )

    async def cancelled(*args):
        orch._pending_events.append(MessageAction(content='arrived during prep'))
        raise asyncio.CancelledError

    monkeypatch.setattr(drain, '_process_events_with_frame_budget', cancelled)
    monkeypatch.setattr(drain, '_force_immediate_drain', MagicMock())
    with pytest.raises(asyncio.CancelledError):
        await drain.drain_events_async(orch)
    assert not orch._async_drain_active
