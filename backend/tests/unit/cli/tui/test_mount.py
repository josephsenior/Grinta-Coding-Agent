"""Headless TUI — mount."""

from backend.tests.unit.cli.tui._shared import (
    GrintaTUIApp,
    HUD,
    Label,
    RichConsole,
    _get_screen,
    asyncio,
    pytest,
)

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
