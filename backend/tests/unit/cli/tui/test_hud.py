"""Headless TUI — hud."""

from backend.tests.unit.cli.tui import _shared
from backend.tests.unit.cli.tui._shared import *  # noqa: F403

for _name in dir(_shared):
    if _name.startswith('_') and not _name.startswith('__'):
        globals()[_name] = getattr(_shared, _name)

from backend.tests.unit.cli.tui._shared import _get_screen


@pytest.mark.asyncio
async def test_tui_hud_bar_shows_workspace_path(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._config = mock_config
        s._render_hud_bar()
        await pilot.pause()

        stats = s.query_one('#hud-line-1-ws', Label)
        rendered = str(stats.renderable)
        assert 'Ws:' in rendered
        assert any(sep in rendered for sep in ('/', '\\', '~'))


@pytest.mark.asyncio
async def test_tui_update_hud_state(mock_config, monkeypatch):
    """Verify update_hud folds runtime info into the two-line HUD."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._hud.update_agent_state('Running')
        s.update_hud()
        await pilot.pause()

        stats = s.query_one('#hud-line-1', Label)
        activity = s.query_one('#hud-line-2', Label)
        assert 'Running' in str(stats.renderable)
        assert 'Help' in str(activity.renderable)


@pytest.mark.asyncio
async def test_tui_hud_bar_shows_accumulated_and_context_tokens(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._hud.state.total_tokens = 430
        s._hud.state.context_tokens = 430
        s._hud.state.context_limit = 8192
        s._render_hud_bar()
        await pilot.pause()

        stats = s.query_one('#hud-line-2', Label)
        rendered = str(stats.renderable)
        assert 'Ctx: 430/8.2K' in rendered
        assert '%' in rendered


@pytest.mark.asyncio
async def test_tui_hud_reasoning_select_syncs_from_config(mock_config, monkeypatch):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    mock_config.get_llm_config.return_value.reasoning_effort = 'high'
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)
    monkeypatch.setattr(
        GrintaScreen,
        '_hud_reasoning_select_options',
        lambda self: [
            ('Default', ''),
            ('Low', 'low'),
            ('Medium', 'medium'),
            ('High', 'high'),
        ],
    )

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._config = mock_config
        s._render_hud_bar()
        await pilot.pause()

        reasoning = s.query_one('#hud-reasoning', Select)
        assert reasoning.value == 'high'


@pytest.mark.asyncio
async def test_tui_hud_reasoning_sync_does_not_apply_setting(mock_config, monkeypatch):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    mock_config.get_llm_config.return_value.reasoning_effort = 'high'
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)
    monkeypatch.setattr(
        GrintaScreen,
        '_hud_reasoning_select_options',
        lambda self: [('XHigh', 'xhigh'), ('High', 'high')],
    )
    update_calls = []
    monkeypatch.setattr(
        'backend.cli.settings.update_model',
        lambda *args, **kwargs: update_calls.append((args, kwargs)),
    )

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s.notify = MagicMock()  # type: ignore[method-assign]
        s._config = mock_config
        s._render_hud_bar()
        await pilot.pause()
        await pilot.pause()

        reasoning = s.query_one('#hud-reasoning', Select)
        assert reasoning.value == 'high'
        assert update_calls == []
        s.notify.assert_not_called()


@pytest.mark.asyncio
async def test_tui_hud_reasoning_effort_persists(mock_config, monkeypatch):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)
    monkeypatch.setattr(
        GrintaScreen,
        '_hud_reasoning_select_options',
        lambda self: [('Default', ''), ('Low', 'low'), ('High', 'high')],
    )

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._config = mock_config
        s._apply_hud_reasoning_effort('low')
        await pilot.pause()

        from backend.cli.settings import get_persisted_reasoning_effort

        assert get_persisted_reasoning_effort() == 'low'


@pytest.mark.asyncio
async def test_tui_hud_autonomy_selector_updates_controller(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        controller = SimpleNamespace(
            autonomy_controller=SimpleNamespace(autonomy_level='balanced')
        )
        s._controller = controller  # type: ignore[assignment]
        autonomy = s.query_one('#hud-autonomy', Select)
        autonomy.value = 'full'
        await pilot.pause()

        assert controller.autonomy_controller.autonomy_level == 'full'
        assert s._hud.state.autonomy_level == 'full'


@pytest.mark.asyncio
async def test_tui_hud_autonomy_sync_uses_agent_config_without_applying_default(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    agent_config = SimpleNamespace(mode='agent', autonomy_level='full')
    mock_config.get_agent_config.return_value = agent_config
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s.notify = MagicMock()  # type: ignore[method-assign]
        s._hud.update_autonomy('balanced')
        s._render_hud_bar()
        await pilot.pause()
        await pilot.pause()

        autonomy = s.query_one('#hud-autonomy', Select)
        assert autonomy.value == 'full'
        assert s._hud.state.autonomy_level == 'full'
        assert agent_config.autonomy_level == 'full'
        s.notify.assert_not_called()
