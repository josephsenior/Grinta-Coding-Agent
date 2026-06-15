"""Tests for activity card expand/collapse policy."""

from __future__ import annotations

import pytest
from rich.console import Console as RichConsole

from backend.cli.display.hud import HUDBar
from backend.cli.display.reasoning_display import ReasoningDisplay
from backend.cli.tui.app import TUIRenderer
from backend.cli.tui.main import GrintaTUIApp
from backend.cli.tui.widgets.activity_card import ActivityCard as TUIActivityCard
from backend.ledger.action import CmdRunAction
from backend.ledger.observation import CmdOutputObservation
from backend.tests.unit.cli.tui._shared import _get_screen


@pytest.mark.asyncio
async def test_active_card_collapses_when_next_shell_starts(mock_config) -> None:
    console = RichConsole()
    loop = __import__('asyncio').get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        screen = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=screen,
            loop=loop,
        )

        renderer._process_event(CmdRunAction(command='pytest -q'))
        renderer._process_event(
            CmdOutputObservation('2 passed', command='pytest -q', exit_code=0)
        )
        await pilot.pause()

        first = next(
            card
            for card in screen.query(TUIActivityCard).results()
            if 'category-shell' in card.classes
        )
        first.expand()
        assert '-expanded' in first.classes

        renderer._process_event(CmdRunAction(command='npm test'))
        await pilot.pause()

        assert '-collapsed' in first.classes
        shell_cards = [
            card
            for card in screen.query(TUIActivityCard).results()
            if 'category-shell' in card.classes
        ]
        assert len(shell_cards) == 2
        assert '-expanded' in shell_cards[1].classes


@pytest.mark.asyncio
async def test_pinned_card_stays_expanded_when_next_shell_starts(mock_config) -> None:
    console = RichConsole()
    loop = __import__('asyncio').get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        screen = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=screen,
            loop=loop,
        )

        renderer._process_event(CmdRunAction(command='pytest -q'))
        renderer._process_event(
            CmdOutputObservation('2 passed', command='pytest -q', exit_code=0)
        )
        await pilot.pause()

        first = next(
            card
            for card in screen.query(TUIActivityCard).results()
            if 'category-shell' in card.classes
        )
        first.set_pinned(True)
        renderer._process_event(CmdRunAction(command='npm test'))
        await pilot.pause()

        assert first.is_pinned
        assert '-expanded' in first.classes
