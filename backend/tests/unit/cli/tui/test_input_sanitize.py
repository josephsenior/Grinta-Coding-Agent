"""Headless TUI — input_sanitize."""

from backend.tests.unit.cli.tui._shared import (
    GrintaTUIApp,
    RichConsole,
    TextArea,
    _get_screen,
    _strip_terminal_control_literals,
    asyncio,
    pytest,
)

def test_tui_strips_leaked_mouse_reports_from_input_text() -> None:
    leaked = '[<35;73;29M[<35;73;30Mhello\x1b[<35;74;31M'
    assert _strip_terminal_control_literals(leaked) == 'hello'

def test_tui_strips_leaked_mouse_reports_without_sgr_marker() -> None:
    leaked = 'PS> [444444;32;15M[555;31;16Mhello'
    assert _strip_terminal_control_literals(leaked) == 'PS> hello'

def test_tui_strips_screenshot_style_mouse_stream() -> None:
    leaked = (
        'PS C:\\Users\\GIGABYTE\\Desktop\\New folder (3)> '
        '[555;57;27M[555;57;26M[555;58;24M[555555;60;27Mpython'
    )
    assert _strip_terminal_control_literals(leaked) == (
        'PS C:\\Users\\GIGABYTE\\Desktop\\New folder (3)> python'
    )

@pytest.mark.asyncio
async def test_tui_headless_exit_restores_terminal_modes(mock_config, monkeypatch):
    from backend.cli.terminal_restore import terminal_restore_guard

    restore_calls: list[int] = []
    monkeypatch.setattr(
        'backend.cli.terminal_restore.restore_terminal_modes',
        lambda **_: restore_calls.append(1),
    )

    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    with terminal_restore_guard(app):
        async with app.run_test(size=(120, 36)):
            pass

    assert restore_calls

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

@pytest.mark.asyncio
async def test_tui_input_poll_strips_leaked_mouse_reports(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        ta.text = (
            'PS C:\\Users\\GIGABYTE\\Desktop\\New folder> '
            + '[555;76;29M[222;1;38M' * 10
        )
        await pilot.pause(0.2)

        assert '[555;76;29M' not in ta.text
        assert ta.text == 'PS C:\\Users\\GIGABYTE\\Desktop\\New folder> '
