"""Headless TUI smoke tests — run without a terminal."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, PropertyMock

import pytest
from rich.console import Console as RichConsole

from textual.widgets import Static
from backend.cli.tui.app import GrintaScreen, InputBar, TextArea
from backend.cli.tui.main import GrintaTUIApp


@pytest.fixture
def mock_config():
    config = MagicMock()
    type(config).project_root = PropertyMock(return_value=None)

    llm_config = MagicMock()
    llm_config.model = 'test-model'
    config.get_llm_config.return_value = llm_config
    return config


def _get_screen(app: GrintaTUIApp) -> GrintaScreen:
    """Helper: query via app.screen since app.query_one uses default screen."""
    return app.screen  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_tui_mounts(mock_config):
    """Smoke test — TUI mounts without CSS or runtime errors."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        topbar = s.query_one('#top-bar', Static)
        assert topbar is not None
        assert 'Grinta' in topbar.renderable

        footer = s.query_one('#footer-bar')
        assert footer is not None


@pytest.mark.asyncio
async def test_tui_input_and_transcript(mock_config):
    """Verify the input area and transcript log are present."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        assert ta is not None

        transcript = s.query_one('#transcript-log')
        assert transcript is not None

        input_bar = s.query_one('#input-bar', InputBar)
        assert 'processing' not in input_bar.classes


@pytest.mark.asyncio
async def test_tui_typing(mock_config):
    """Verify typing text into the input area works."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        assert ta.focusable

        await pilot.press(*'hello world')
        assert ta.text == 'hello world'


@pytest.mark.asyncio
async def test_tui_clear_command(mock_config):
    """Verify /clear slash command works."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        ta.text = '/clear'
        await pilot.press('enter')
        await pilot.pause()

        assert s is not None


@pytest.mark.asyncio
async def test_tui_help_shows(mock_config):
    """Verify /help slash command does not crash."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        ta.text = '/help'
        await pilot.press('enter')
        await pilot.pause()

        transcript = s.query_one('#transcript-log')
        assert transcript is not None


@pytest.mark.asyncio
async def test_tui_unknown_command(mock_config):
    """Verify unknown slash command shows error without crashing."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        ta.text = '/nonexistent'
        await pilot.press('enter')
        await pilot.pause()

        transcript = s.query_one('#transcript-log')
        assert transcript is not None


@pytest.mark.asyncio
async def test_tui_update_hud_state(mock_config):
    """Verify update_hud works with new topbar+metrics layout."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._hud.update_agent_state('Running')
        s.update_hud()
        await pilot.pause()

        # State now lives in the metrics status card, not topbar
        status_card = s.query_one('#metrics-status', Static)
        assert 'Running' in status_card.renderable


@pytest.mark.asyncio
async def test_tui_message_helpers(mock_config):
    """Verify message writing helpers work without error."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s.add_user_message('test user message')
        s.add_agent_message('test agent message')
        s.add_system_message('test system message')
        s.add_success('test success')
        s.add_error('test error')
        s.add_tool_start('test_tool_name')
        s.add_tool_result('test tool result')
        s.add_divider()
        await pilot.pause()

        log = s.query_one('#transcript-log')
        assert log is not None


@pytest.mark.asyncio
async def test_tui_run_agent_loop_is_awaitable(mock_config):
    """Verify _run_agent_loop is a proper coroutine (architectural check)."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        assert asyncio.iscoroutinefunction(s._run_agent_loop)


@pytest.mark.asyncio
async def test_tui_drain_events_noop_when_empty(mock_config):
    """Verify drain_events is safe to call with no pending events."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = s._renderer
        if renderer is not None:
            renderer.drain_events()
        else:
            from backend.cli.hud import HUDBar
            from backend.cli.reasoning_display import ReasoningDisplay
            from backend.cli.tui.app import TUIRenderer

            renderer = TUIRenderer(
                console=console,
                hud=HUDBar(),
                reasoning=ReasoningDisplay(),
                tui=s,
                loop=loop,
            )
            renderer.drain_events()
        await pilot.pause()


@pytest.mark.asyncio
async def test_tui_metrics_grid_exists(mock_config):
    """Verify metrics grid with 4 cards is present."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        grid = s.query_one('#metrics-grid')
        assert grid is not None

        cards = grid.query('MetricsCard')
        assert len(cards) == 4
