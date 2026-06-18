"""Tests for session-tier shell panel and record-tier collapse behavior."""

from __future__ import annotations

import pytest
from rich.console import Console as RichConsole

from backend.cli.display.hud import HUDBar
from backend.cli.display.reasoning_display import ReasoningDisplay
from backend.cli.tui.app import TUIRenderer
from backend.cli.tui.main import GrintaTUIApp
from backend.cli.tui.widgets.record_panel import RecordPanel
from backend.cli.tui.widgets.scan_line import ShellCard
from backend.ledger.action import CmdRunAction, MCPAction
from backend.ledger.observation import CmdOutputObservation, MCPObservation
from backend.tests.unit.cli.tui._shared import _get_screen


@pytest.mark.asyncio
async def test_shell_session_panels_stay_open_when_next_shell_starts(
    mock_config,
) -> None:
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

        renderer._process_event(CmdRunAction(command='npm test'))
        await pilot.pause()

        shell_cards = [
            card
            for card in screen.query(ShellCard).results()
            if card.command in ('pytest -q', 'npm test')
        ]
        assert len(shell_cards) == 2
        assert shell_cards[0].command == 'pytest -q'
        assert shell_cards[1].command == 'npm test'


@pytest.mark.asyncio
async def test_shell_session_panel_keeps_body_visible_after_completion(
    mock_config,
) -> None:
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

        card = next(
            c
            for c in screen.query(ShellCard).results()
            if c.command == 'pytest -q'
        )
        assert card.exit_code == 0
        assert card.output == '2 passed'


@pytest.mark.asyncio
async def test_record_panel_stays_collapsed_until_user_expands(mock_config) -> None:
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

        renderer._process_event(MCPAction(name='docs_tool', arguments={'q': 'api'}))
        renderer._process_event(
            MCPObservation(
                name='docs_tool',
                arguments={'q': 'api'},
                content='long result payload for the record body',
            )
        )
        await pilot.pause()

        panel = next(
            p
            for p in screen.query(RecordPanel).results()
            if 'category-mcp' in p.classes
        )
        assert '-collapsed' in panel.classes
        panel.expand()
        assert '-expanded' in panel.classes
        panel.collapse()
        assert '-collapsed' in panel.classes
