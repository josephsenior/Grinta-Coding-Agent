"""Repro for live-response streaming syntax highlighting."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest
from rich.console import Console
from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.widgets import Static

from backend.cli.display.hud import HUDBar
from backend.cli.display.reasoning_display import ReasoningDisplay
from backend.cli.event_rendering.text_utils import sanitize_visible_transcript_text
from backend.cli.tui.app import TUIRenderer
from backend.cli.tui.renderer.prep import prep_streaming_response_async
from backend.cli.tui.widgets.activity_card import LiveResponse
from backend.ledger.action.message import StreamingChunkAction


def _has_syntax(node: object) -> bool:
    if isinstance(node, Syntax):
        return True
    renderables = getattr(node, 'renderables', None)
    if renderables:
        return any(_has_syntax(part) for part in renderables)
    return False


class _LiveTranscriptHost(App):
    def compose(self) -> ComposeResult:
        return []


PARTIAL = 'Here is code:\n```python\ndef foo():\n    return 1'


@pytest.mark.asyncio
async def test_streaming_preprocess_cache_key_matches_normalized_apply() -> None:
    raw = PARTIAL
    norm = sanitize_visible_transcript_text(raw)

    renderer = TUIRenderer(
        console=Console(),
        hud=HUDBar(),
        reasoning=ReasoningDisplay(),
        tui=MagicMock(),
        loop=asyncio.get_running_loop(),
    )

    async with _LiveTranscriptHost().run_test() as pilot:
        await pilot.pause()

        class _Display:
            def should_follow_tail(self) -> bool:
                return True

            def append_widget(self, widget: object) -> None:
                pilot.app.mount(widget)

            def follow_tail(self) -> None:
                return

        renderer._tui._get_display = lambda: _Display()

        await prep_streaming_response_async(renderer, norm)
        assert norm in renderer._streaming_render_cache

        renderer.update_live_response(norm)
        await pilot.pause()
        widget = renderer._live_response_widget
        assert isinstance(widget, LiveResponse)
        content = widget.query_one('#live-content', Static)
        assert _has_syntax(content.renderable)


@pytest.mark.asyncio
async def test_streaming_chunk_drain_path_highlights_open_fence() -> None:
    from backend.cli.tui.renderer.drain import _preprocess_event_async

    renderer = TUIRenderer(
        console=Console(),
        hud=HUDBar(),
        reasoning=ReasoningDisplay(),
        tui=MagicMock(),
        loop=asyncio.get_running_loop(),
    )

    async with _LiveTranscriptHost().run_test() as pilot:
        await pilot.pause()

        class _Display:
            def should_follow_tail(self) -> bool:
                return True

            def append_widget(self, widget: object) -> None:
                pilot.app.mount(widget)

            def follow_tail(self) -> None:
                return

        renderer._tui._get_display = lambda: _Display()

        action = StreamingChunkAction(accumulated=PARTIAL, is_final=False)
        await _preprocess_event_async(renderer, action)
        renderer._handle_streaming_chunk(action)
        await pilot.pause()

        widget = renderer._live_response_widget
        assert isinstance(widget, LiveResponse)
        content = widget.query_one('#live-content', Static)
        assert _has_syntax(content.renderable)
