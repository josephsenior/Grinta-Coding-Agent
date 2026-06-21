"""Headless TUI — welcome."""

import pytest

from backend.cli.tui.widgets.welcome import WelcomeWidget
from backend.tests.unit.cli.tui import _shared
from backend.tests.unit.cli.tui._shared import *  # noqa: F403

for _name in dir(_shared):
    if _name.startswith('_') and not _name.startswith('__'):
        globals()[_name] = getattr(_shared, _name)

from backend.tests.unit.cli.tui._shared import _get_screen


def test_welcome_select_current_before_mount() -> None:
    widget = WelcomeWidget()
    assert widget.select_current() == widget._suggestions[0]


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
async def test_tui_welcome_arrow_navigation_works_with_input_focus(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._show_welcome()
        await pilot.pause(1.1)

        welcome = s.query_one(WelcomeWidget)
        assert welcome.select_current() == 'Explain this codebase'

        await pilot.press('down')
        await pilot.pause()
        assert (
            welcome.select_current()
            == 'Analyze this repository and produce an implementation plan'
        )

        await pilot.press('up')
        await pilot.pause()
        assert welcome.select_current() == 'Explain this codebase'


@pytest.mark.asyncio
async def test_tui_welcome_click_submits_selected_suggestion(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        submit_mock = MagicMock()
        s.action_submit_input = submit_mock  # type: ignore[method-assign]
        s._show_welcome()
        await pilot.pause(1.1)

        welcome = s.query_one(WelcomeWidget)
        items = list(welcome.query('.welcome-item'))
        assert len(items) == 5

        clicked = await pilot.click(items[1], offset=(1, 0))
        await pilot.pause()

        ta = s.query_one('#input', TextArea)
        assert clicked
        assert ta.text == 'Analyze this repository and produce an implementation plan'
        assert s._welcome_visible is False
        submit_mock.assert_called_once()


@pytest.mark.asyncio
async def test_tui_welcome_persists_until_real_transcript_content(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._show_welcome()
        await pilot.pause(0.2)
        assert s._welcome_visible is True

        await s.on_renderer_drain_requested(RendererDrainRequested())
        await pilot.pause()
        assert s._welcome_visible is True

        s._get_display().mount(Static('boot complete'))
        await pilot.pause()
        await s.on_renderer_drain_requested(RendererDrainRequested())
        await pilot.pause()
        assert s._welcome_visible is False


@pytest.mark.asyncio
async def test_tui_welcome_persists_after_slash_command(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._show_welcome()
        await pilot.pause(0.2)
        assert s._welcome_visible is True
        assert s._get_welcome_widget() is not None

        s.show_help = MagicMock()  # type: ignore[method-assign]
        await pilot.press('/', 'h', 'e', 'l', 'p')
        await pilot.press('enter')
        await pilot.pause()

        assert s._welcome_visible is True
        assert s._get_welcome_widget() is not None
        s.show_help.assert_called_once()


@pytest.mark.asyncio
async def test_tui_welcome_restored_after_modal_dismiss(mock_config, monkeypatch):
    from backend.cli.tui.dialogs import GrintaHelpDialog

    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._show_welcome()
        await pilot.pause(0.2)
        widget = s._get_welcome_widget()
        assert widget is not None
        widget.remove()
        s._welcome_visible = False

        await app.push_screen(GrintaHelpDialog())
        await pilot.pause()
        await pilot.press('escape')
        await pilot.pause()

        assert s._welcome_visible is True
        assert s._get_welcome_widget() is not None


@pytest.mark.asyncio
async def test_hydrate_skips_when_welcome_visible(mock_config):
    from backend.cli.tui.renderer.drain import hydrate_recent_transcript

    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        s._show_welcome()
        await pilot.pause()

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._event_stream = MagicMock()
        renderer._event_stream.search_events.return_value = [
            SimpleNamespace(id=0),
        ]

        loaded = await hydrate_recent_transcript(renderer)
        assert loaded == 0
        renderer._event_stream.search_events.assert_not_called()
