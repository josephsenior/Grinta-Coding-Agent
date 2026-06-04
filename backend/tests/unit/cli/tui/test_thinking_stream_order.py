from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, PropertyMock

import pytest
from rich.console import Console as RichConsole

from backend.cli.hud import HUDBar
from backend.cli.reasoning_display import ReasoningDisplay
from backend.cli.tui.app import GrintaScreen, TUIRenderer
from backend.cli.tui.main import GrintaTUIApp
from backend.cli.tui.widgets.activity_card import (
    ActivityCard as TUIActivityCard,
)
from backend.cli.tui.widgets.activity_card import ThinkingIndicator
from backend.ledger.action import FileWriteAction, StreamingChunkAction
from textual.widgets import Static


@pytest.fixture
def mock_config():
    config = MagicMock()
    type(config).project_root = PropertyMock(return_value=None)

    llm_config = MagicMock()
    llm_config.model = 'openai/gpt-4o'
    llm_config.base_url = None
    config.get_llm_config.return_value = llm_config
    config.get_llm_config_from_agent.return_value = llm_config
    return config


def _plain_text(widget: ThinkingIndicator) -> str:
    body = widget.query_one('#thinking-body', Static)
    return str(body.renderable)


@pytest.mark.asyncio
async def test_thinking_stream_freezes_before_later_activity(
    mock_config,
    monkeypatch,
) -> None:
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        screen = app.screen
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=screen,  # type: ignore[arg-type]
            loop=loop,
        )
        screen._renderer = renderer  # type: ignore[attr-defined]

        renderer._process_event(
            StreamingChunkAction(thinking_accumulated='First thought.')
        )
        await pilot.pause()
        renderer._process_event(
            StreamingChunkAction(
                thinking_accumulated='First thought.\nStill thinking.'
            )
        )
        await pilot.pause()
        renderer._process_event(
            FileWriteAction(path='tests/test_order.py', content='def test_ok():\n    pass\n')
        )
        await pilot.pause()
        renderer._process_event(
            StreamingChunkAction(thinking_accumulated='Second thought.')
        )
        await pilot.pause()

        display = screen.query_one('#main-display')
        visible = [
            child
            for child in display.children
            if isinstance(child, (ThinkingIndicator, TUIActivityCard))
        ]

        assert [type(child) for child in visible] == [
            ThinkingIndicator,
            TUIActivityCard,
            ThinkingIndicator,
        ]
        assert 'Still thinking.' in _plain_text(visible[0])
        assert 'tests/test_order.py' in str(
            visible[1].query_one('#collapsed-row').renderable
        )
        assert 'Second thought.' in _plain_text(visible[2])
