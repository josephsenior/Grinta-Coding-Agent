"""Headless TUI smoke tests — run without a terminal."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, PropertyMock

import pytest
from rich.console import Console as RichConsole
from textual.widgets import Label, TextArea

from backend.cli.tui.app import HUD, GrintaScreen, InputBar
from backend.cli.tui.main import GrintaTUIApp


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
        stats = s.query_one('#hud-line-1', Label)
        assert stats is not None
        assert 'GRINTA' in str(stats.renderable)

        footer = s.query_one('#hud-bar', HUD)
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

        transcript = s.query_one('#main-display')
        assert transcript is not None


@pytest.mark.asyncio
async def test_tui_settings_command_dispatches(mock_config):
    """Verify /settings dispatches to the real TUI settings handler."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        called = {'value': False}

        async def _fake_settings() -> None:
            called['value'] = True

        s._open_settings_tui = _fake_settings  # type: ignore[method-assign]

        ta = s.query_one('#input', TextArea)
        ta.text = '/settings'
        await pilot.press('enter')
        await pilot.pause()

        assert called['value'] is True


@pytest.mark.asyncio
async def test_tui_sessions_command_dispatches_with_args(mock_config):
    """Verify /sessions forwards parsed args to the session handler."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        captured: list[str] = []

        async def _fake_sessions(args: list[str]) -> None:
            captured.extend(args)

        s._run_sessions_tui = _fake_sessions  # type: ignore[method-assign]

        ta = s.query_one('#input', TextArea)
        ta.text = '/sessions --limit 7'
        await pilot.press('enter')
        await pilot.pause()

        assert captured == ['--limit', '7']


@pytest.mark.asyncio
async def test_tui_resume_command_dispatches_with_args(mock_config):
    """Verify /resume forwards parsed args to the resume handler."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        captured: list[str] = []

        async def _fake_resume(args: list[str]) -> None:
            captured.extend(args)

        s._run_resume_tui = _fake_resume  # type: ignore[method-assign]

        ta = s.query_one('#input', TextArea)
        ta.text = '/resume 3'
        await pilot.press('enter')
        await pilot.pause()

        assert captured == ['3']


@pytest.mark.asyncio
async def test_tui_sessions_modal_resume_handoff(mock_config):
    """Verify sessions modal selection triggers direct resume flow."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        resumed: dict[str, str | None] = {'sid': None}

        async def _fake_push_screen_wait(_dialog) -> str | None:
            return 'session-abc123'

        async def _fake_resume_target(target: str) -> None:
            resumed['sid'] = target

        app.push_screen_wait = _fake_push_screen_wait  # type: ignore[method-assign]
        s._resume_session_target = _fake_resume_target  # type: ignore[method-assign]

        await s._run_sessions_tui([])

        assert resumed['sid'] == 'session-abc123'


@pytest.mark.asyncio
async def test_tui_inline_command_hint_updates(mock_config):
    """Verify slash command typing updates HUD hint line."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        ta.text = '/sessions --s'
        await pilot.pause()

        hint = s.query_one('#hud-line-3', Label)
        assert 'Hint:' in str(hint.renderable)


@pytest.mark.asyncio
async def test_tui_command_autocomplete_for_sessions(mock_config):
    """Verify autocomplete expands slash command prefixes."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        ta.text = '/sess'
        s.action_complete_command()
        await pilot.pause()

        assert ta.text == '/sessions '


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

        transcript = s.query_one('#main-display')
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

        # State now lives in the HUD bar
        stats = s.query_one('#hud-line-2', Label)
        assert 'Running' in str(stats.renderable)


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

        log = s.query_one('#main-display')
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
async def test_tui_drain_events_noop_when_empty(mock_config, monkeypatch):
    """Verify drain_events is safe to call with no pending events."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    
    # Prevent _bootstrap from failing and exiting the app
    from backend.cli.tui.app import GrintaScreen
    monkeypatch.setattr(GrintaScreen, '_bootstrap', MagicMock())
    
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
async def test_tui_stats_panel_exists(mock_config):
    """Verify stats panel in input bar is present."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        stats = s.query_one('#hud-bar')
        assert stats is not None
