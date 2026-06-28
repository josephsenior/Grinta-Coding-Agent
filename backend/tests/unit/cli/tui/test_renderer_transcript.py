"""Headless TUI — renderer transcript/scroll/mode."""

from backend.tests.unit.cli.tui._shared import (
    GrintaScreen,
    GrintaTUIApp,
    HUDBar,
    InputBar,
    MagicMock,
    ReasoningDisplay,
    RichConsole,
    Select,
    SimpleNamespace,
    Static,
    TUIRenderer,
    TextArea,
    _await_at_bottom,
    _fill_scrollable_transcript,
    _get_screen,
    asyncio,
    pytest,
)

from backend.cli.tui.widgets.activity_card import OrientLine
from backend.cli.tui.widgets.scan_line import (
    EditCard,
)

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
async def test_tui_transcript_autoscrolls_on_rapid_append(mock_config, monkeypatch):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()

        display = _get_screen(app).query_one('#main-display')
        display._suppress_mount_animation = True
        for idx in range(80):
            display.append_widget(Static(f'transcript line {idx}'))
        await pilot.pause()
        display.force_scroll_end()
        await _await_at_bottom(display, pilot)
        assert display.max_scroll_y > 0

        for idx in range(30):
            display.append_widget(Static(f'burst line {idx}'))
        await _await_at_bottom(display, pilot)

        assert display._user_scrolled_away is False

@pytest.mark.asyncio
async def test_tui_live_response_follows_tail_when_not_user_scrolled(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        display = s.query_one('#main-display')
        await _fill_scrollable_transcript(display, pilot)

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        renderer.update_live_response('Starting response.')
        await pilot.pause()
        display.force_scroll_end()
        await pilot.pause()

        renderer.update_live_response(
            'Starting response.\n' + '\n'.join(f'new line {idx}' for idx in range(20))
        )
        await pilot.pause()
        await _await_at_bottom(display, pilot)

        assert display._user_scrolled_away is False
        assert display._was_at_bottom()

@pytest.mark.asyncio
async def test_tui_live_response_respects_user_scrolled_away(mock_config, monkeypatch):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        display = s.query_one('#main-display')
        await _fill_scrollable_transcript(display, pilot)

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer
        renderer.update_live_response('Starting response.')
        await pilot.pause()
        display.force_scroll_end()
        await pilot.pause()

        display.user_scroll_home(animate=False)
        for _ in range(12):
            display._sync_scroll_state_from_position()
            if (
                display._user_scrolled_away
                and display.max_scroll_y > 0
                and display.scroll_y < display.max_scroll_y - 1.0
            ):
                break
            await pilot.pause()

        assert display._user_scrolled_away is True
        assert not display._was_at_bottom()

        renderer.update_live_response(
            'Starting response.\n' + '\n'.join(f'new line {idx}' for idx in range(20))
        )
        for _ in range(12):
            display._sync_scroll_state_from_position()
            if display._user_scrolled_away and not display._was_at_bottom():
                break
            await pilot.pause()

        assert display._user_scrolled_away is True
        assert not display._was_at_bottom()

@pytest.mark.asyncio
async def test_tui_content_growth_does_not_mark_user_scrolled_away(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()

        display = _get_screen(app).query_one('#main-display')
        display._suppress_mount_animation = True
        await _fill_scrollable_transcript(display, pilot, count=40)

        display._sync_scroll_state_from_position()
        assert display._user_scrolled_away is False

        display.append_widget(Static('new tail content'))
        await pilot.pause()
        await _await_at_bottom(display, pilot)
        assert display._user_scrolled_away is False

@pytest.mark.asyncio
async def test_tui_user_scroll_wins_over_active_follow_tail(mock_config, monkeypatch):
    """A user scroll must register even while a follow-tail scroll is in flight.

    During streaming, _schedule_follow_tail keeps _suppress_scroll_sync True
    almost continuously. Genuine user scroll input must still mark the
    transcript as scrolled-away and must not be yanked back to the tail.
    """
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()

        display = _get_screen(app).query_one('#main-display')
        display._suppress_mount_animation = True
        await _fill_scrollable_transcript(display, pilot)

        # Simulate an in-flight programmatic follow-tail scroll.
        display._suppress_scroll_sync = True

        display.user_scroll_home(animate=False)
        for _ in range(20):
            display._sync_scroll_state_from_position()
            if (
                display._user_scrolled_away
                and display.max_scroll_y > 0
                and display.scroll_y < display.max_scroll_y - 1.0
            ):
                break
            await pilot.pause()

        assert display._user_scrolled_away is True
        assert display.max_scroll_y > 0
        assert display.scroll_y < display.max_scroll_y - 1.0

@pytest.mark.asyncio
async def test_tui_page_keys_scroll_transcript_while_turn_running(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        display = s.query_one('#main-display')
        display._suppress_mount_animation = True
        await _fill_scrollable_transcript(display, pilot)
        display.force_scroll_end()
        await _await_at_bottom(display, pilot)

        s._turn_in_flight = True
        s.query_one('#input', TextArea).focus()
        # Scroll to top so follow-tail is clearly disabled during an active turn.
        s.action_scroll_home()
        for _ in range(12):
            display._sync_scroll_state_from_position()
            if display._user_scrolled_away and not display._was_at_bottom():
                break
            await pilot.pause()

        assert display._user_scrolled_away is True
        assert not display._was_at_bottom()

@pytest.mark.asyncio
async def test_tui_backpressure_suppresses_mount_animation(mock_config, monkeypatch):
    """set_backpressure(True) skips append_widget's mount offset animation."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()

        display = _get_screen(app).query_one('#main-display')

        display.set_backpressure(True)
        assert display._under_backpressure is True
        widget = Static('burst content')
        display.append_widget(widget)
        await pilot.pause()
        # No offset animation was applied while under backpressure.
        offset = tuple(getattr(part, 'value', part) for part in widget.styles.offset)
        assert offset == (0, 0)

        display.set_backpressure(False)
        assert display._under_backpressure is False

@pytest.mark.asyncio
async def test_tui_mode_switch_supports_chat_plan_agent(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    agent_config = SimpleNamespace(mode='agent')
    mock_config.get_agent_config.return_value = agent_config
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        mode_select = s.query_one('#hud-mode', Select)
        for mode in ('chat', 'plan', 'agent'):
            mode_select.value = mode
            await pilot.pause()
            assert agent_config.mode == mode

@pytest.mark.asyncio
async def test_tui_mode_switch_updates_default_agent_config(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    mock_config.default_agent = 'Orchestrator'
    configs = {
        'Orchestrator': SimpleNamespace(mode='agent'),
        'agent': SimpleNamespace(mode='agent'),
    }
    mock_config.get_agent_config.side_effect = lambda name='agent': configs[name]
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s._apply_mode('chat')
        await pilot.pause()

        assert configs['Orchestrator'].mode == 'chat'
        assert configs['agent'].mode == 'agent'

@pytest.mark.asyncio
async def test_tui_mode_switch_updates_running_agent_config(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    agent_config = SimpleNamespace(mode='agent')
    mock_config.get_agent_config.return_value = agent_config
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        running_config = SimpleNamespace(mode='agent')
        planner = SimpleNamespace(
            _config=running_config,
            build_toolset=MagicMock(return_value=['read']),
        )
        agent = SimpleNamespace(
            config=running_config,
            planner=planner,
            tools=['old'],
        )
        s._controller = SimpleNamespace(
            agent=agent,
            state=SimpleNamespace(extra_data={'active_run_mode': 'agent'}),
        )

        s._apply_mode('chat')
        await pilot.pause()

        assert agent_config.mode == 'chat'
        assert running_config.mode == 'chat'
        assert agent.tools == ['read']
        assert 'active_run_mode' not in s._controller.state.extra_data

