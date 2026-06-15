"""Headless TUI — input_sanitize."""

from backend.tests.unit.cli.tui import _shared
from backend.tests.unit.cli.tui._shared import *  # noqa: F403
for _name in dir(_shared):
    if _name.startswith("_") and not _name.startswith("__"):
        globals()[_name] = getattr(_shared, _name)

def test_tui_strips_leaked_mouse_reports_from_input_text() -> None:
    leaked = '[<35;73;29M[<35;73;30Mhello\x1b[<35;74;31M'
    assert _strip_terminal_control_literals(leaked) == 'hello'

def test_tui_strips_leaked_mouse_reports_without_sgr_marker() -> None:
    leaked = 'PS> [444444;32;15M[555;31;16Mhello'
    assert _strip_terminal_control_literals(leaked) == 'PS> hello'

@pytest.mark.asyncio
async def test_tui_input_removes_leaked_mouse_reports_live(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        ta.text = '[<35;73;29Mhello[<35;73;30M'
        await pilot.pause()

        assert ta.text == 'hello'
