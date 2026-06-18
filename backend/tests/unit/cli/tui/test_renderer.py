"""Headless TUI — renderer."""

from backend.tests.unit.cli.tui import _shared
from backend.tests.unit.cli.tui._shared import *  # noqa: F403

for _name in dir(_shared):
    if _name.startswith('_') and not _name.startswith('__'):
        globals()[_name] = getattr(_shared, _name)

from backend.tests.unit.cli.tui._shared import (
    _await_at_bottom,
    _file_change_cards,
    _fill_scrollable_transcript,
    _get_screen,
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
async def test_tui_activity_card_processing_and_mount(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        data = ActivityRenderer.shell_command('git status')
        mounted = TUIActivityCard(
            verb=data.verb,
            detail=data.detail,
            badge_category=data.badge_category,
            status='running',
            outcome=data.secondary,
            extra_content=None,
            collapsed=True,
        )
        mounted.set_processing(True)
        s.query_one('#main-display').mount(mounted)
        await pilot.pause()

        found = s.query_one(TUIActivityCard)
        assert found is not None

        from backend.cli.tui.widgets.terminal_pane import TerminalPane

        pane = found.query_one('#terminal-pane', TerminalPane)
        assert 'git status' in pane._prompt_markup()
        assert pane._running is True
        body = found.query_one('#expanded-body', Container)
        assert body.display is True


@pytest.mark.asyncio
async def test_tui_shell_card_terminal_pane_before_output(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.widgets.terminal_pane import TerminalPane

        mounted = TUIActivityCard(
            verb='Ran',
            detail='$ pytest -q',
            badge_category='shell',
            status='running',
            terminal_command='pytest -q',
            shell_kind='bash',
            extra_content=None,
            collapsed=True,
        )
        mounted.set_processing(True)
        s.query_one('#main-display').mount(mounted)
        await pilot.pause()

        pane = mounted.query_one('#terminal-pane', TerminalPane)
        assert 'pytest -q' in pane._prompt_markup()
        assert pane._running is True
        body = mounted.query_one('#expanded-body', Container)
        assert body.display is True


@pytest.mark.asyncio
async def test_tui_activity_card_expanded_output_wraps_in_extra_frame(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        data = ActivityRenderer.terminal_output('line1\nline2', session_id='term-1')
        mounted = TUIActivityCard(
            verb=data.verb,
            detail=data.detail,
            badge_category=data.badge_category,
            status='ok',
            outcome=data.secondary,
            extra_content='line1\nline2',
            collapsed=False,
        )
        s.query_one('#main-display').mount(mounted)
        await pilot.pause()

        found = s.query_one(TUIActivityCard)
        body = found.query_one('#expanded-body', Container)
        assert body is not None
        assert body.display is True


@pytest.mark.asyncio
async def test_tui_activity_card_body_click_collapses(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        data = ActivityRenderer.terminal_output('line1\nline2', session_id='term-1')
        mounted = TUIActivityCard(
            verb=data.verb,
            detail=data.detail,
            badge_category=data.badge_category,
            status='ok',
            outcome=data.secondary,
            extra_content='line1\nline2',
            collapsed=False,
        )
        s.query_one('#main-display').mount(mounted)
        await pilot.pause()

        found = s.query_one(TUIActivityCard)
        extra = found.query_one('#terminal-output', Static)

        event = SimpleNamespace(
            widget=extra,
            prevented=False,
            stopped=False,
            prevent_default=lambda: setattr(event, 'prevented', True),
            stop=lambda: setattr(event, 'stopped', True),
        )
        found.on_click(event)

        body = found.query_one('#expanded-body', Container)
        assert found._collapsed is True
        assert body.display is False
        assert event.prevented is True
        assert event.stopped is True


@pytest.mark.asyncio
async def test_tui_renderer_writes_expandable_cards_collapsed_by_default(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        card = ActivityRenderer.shell_command(
            'python fail.py',
            output='Traceback\nboom',
            exit_code=1,
        )
        assert card.is_collapsible is True
        assert card.start_collapsed is False

        widget = renderer._write_card(card)
        await pilot.pause()

        body = widget.query_one('#expanded-body', Container)
        assert widget._collapsed is True
        assert body.display is False


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
        if getattr(renderer, '_streaming_render_timer_armed', False):
            renderer._flush_deferred_streaming_render()
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

        display.user_scroll_page_up(animate=False)
        await pilot.pause()
        assert display._user_scrolled_away is True

        renderer.update_live_response(
            'Starting response.\n' + '\n'.join(f'new line {idx}' for idx in range(20))
        )
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


@pytest.mark.asyncio
async def test_tui_autonomy_visibility_follows_mode(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    agent_config = SimpleNamespace(mode='agent')
    mock_config.get_agent_config.return_value = agent_config
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        autonomy = s.query_one('#hud-autonomy', Select)
        autonomy_label = s.query_one('#hud-label-autonomy', Label)

        s._apply_mode('chat')
        await pilot.pause()
        assert autonomy.display is False
        assert autonomy_label.display is False

        s._apply_mode('plan')
        await pilot.pause()
        assert autonomy.display is False
        assert autonomy_label.display is False

        s._apply_mode('agent')
        await pilot.pause()
        assert autonomy.display is True
        assert autonomy_label.display is True


@pytest.mark.asyncio
async def test_tui_sidebar_rows_expose_delete_for_mcp_and_skills(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)
    mock_config.mcp = SimpleNamespace(
        servers=[SimpleNamespace(name='server-a', type='stdio')]
    )

    from backend.cli.event_rendering import sidebar as sidebar_module

    monkeypatch.setattr(sidebar_module, '_load_playbook_skills', lambda: ['skill-a'])

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.collapsible import SidebarRow

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._refresh_display()

        rows = s.query(SidebarRow).results()
        deletable = [row for row in rows if getattr(row, 'deletable', False)]
        assert any(getattr(row, 'item_id', '') == 'mcp:server-a' for row in deletable)
        assert any(getattr(row, 'item_id', '') == 'skill:skill-a' for row in deletable)


@pytest.mark.asyncio
async def test_tui_lsp_sidebar_lists_detected_servers(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from types import SimpleNamespace

        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.collapsible import CollapsibleSection, SidebarRow

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._lsp_servers_cache = {
            'pylsp': SimpleNamespace(
                available=True,
                spec=SimpleNamespace(language='python', extensions=('.py', '.pyw')),
            ),
            'gopls': SimpleNamespace(
                available=False,
                spec=SimpleNamespace(language='go', extensions=('.go',)),
            ),
        }
        renderer._last_lsp_sidebar_signature = None
        renderer._refresh_lsp_sidebar()
        await pilot.pause()

        lsp_section = s.query_one('#sidebar-lsp', CollapsibleSection)
        assert lsp_section._section_title == 'LSP Servers (1)'

        rows = [
            row
            for row in lsp_section.query(SidebarRow).results()
            if getattr(row, 'item_id', '').startswith('lsp:')
        ]
        assert len(rows) == 1
        assert rows[0]._label == 'python'
        assert rows[0]._meta is None
        assert rows[0].interactive is False
        assert lsp_section.is_collapsed is False


@pytest.mark.asyncio
async def test_tui_dap_sidebar_lists_detected_adapters(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.collapsible import CollapsibleSection, SidebarRow

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._dap_adapters_cache = [
            {
                'language': 'python',
                'adapter': 'debugpy',
                'available': True,
                'auto_resolvable': True,
            },
            {
                'language': 'go',
                'adapter': 'dlv',
                'available': False,
                'auto_resolvable': False,
            },
            {
                'language': 'javascript',
                'adapter': 'js-debug',
                'available': True,
                'auto_resolvable': False,
            },
        ]
        renderer._last_dap_sidebar_signature = None
        renderer._refresh_dap_sidebar()
        await pilot.pause()

        dap_section = s.query_one('#sidebar-dap', CollapsibleSection)
        assert dap_section._section_title == 'Debug Adapters (2)'

        rows = [
            row
            for row in dap_section.query(SidebarRow).results()
            if getattr(row, 'item_id', '').startswith('dap:')
        ]
        assert len(rows) == 2
        by_language = {row._label: row for row in rows}
        assert by_language['python']._meta == 'debugpy'
        assert by_language['python']._status == 'ok'
        assert by_language['javascript']._meta == 'js-debug'
        assert by_language['javascript']._status == 'warn'
        assert dap_section.is_collapsed is False


@pytest.mark.asyncio
async def test_tui_task_sidebar_does_not_clear_on_empty_view_payload(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_bootstrap', AsyncMock())
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._task_list = [
            {'id': '1', 'description': 'Persist task panel', 'status': 'in_progress'}
        ]
        renderer._refresh_display()

        tasks_widget = s.query_one('#sidebar-tasks', CollapsibleSection)
        assert tasks_widget._section_title == 'Tasks (1)'


@pytest.mark.asyncio
async def test_tui_task_sidebar_does_not_clear_on_ambiguous_empty_update_payload(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_bootstrap', AsyncMock())
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._task_list = [
            {'id': '1', 'description': 'Persist task panel', 'status': 'in_progress'}
        ]
        renderer._refresh_display()

        renderer._process_event(
            TaskTrackingObservation(
                content='task tracker sync complete',
                command='update',
                task_list=[],
            )
        )

        tasks_widget = s.query_one('#sidebar-tasks', CollapsibleSection)
        assert tasks_widget._section_title == 'Tasks (1)'


@pytest.mark.asyncio
async def test_tui_task_sidebar_allows_explicit_empty_update_clear(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_bootstrap', AsyncMock())
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._task_list = [
            {'id': '1', 'description': 'Persist task panel', 'status': 'in_progress'}
        ]
        renderer._refresh_display()

        renderer._process_event(
            TaskTrackingObservation(
                content='✅ Plan updated with 0 tasks. Now begin implementing the first todo task.',
                command='update',
                task_list=[],
            )
        )

        tasks_widget = s.query_one('#sidebar-tasks', CollapsibleSection)
        assert tasks_widget._section_title == 'Tasks (0)'

        renderer._process_event(
            TaskTrackingObservation(
                content='viewed',
                command='view',
                task_list=[],
            )
        )

        tasks_widget = s.query_one('#sidebar-tasks', CollapsibleSection)
        assert tasks_widget._section_title == 'Tasks (0)'


@pytest.mark.asyncio
async def test_tui_terminal_session_reuses_single_card(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        from backend.cli.tui.widgets.session_panel import SessionPanel

        renderer._process_event(TerminalRunAction(command='npm run dev'))
        renderer._process_event(TerminalReadAction(session_id='term-1'))
        renderer._process_event(
            TerminalObservation(session_id='term-1', content='ready')
        )
        renderer._process_event(
            TerminalInputAction(session_id='term-1', input='status')
        )
        await pilot.pause()

        panels = s.query(SessionPanel).results()
        terminal_panels = [
            panel for panel in panels if 'category-terminal' in panel.classes
        ]
        assert len(terminal_panels) == 1

        prompt = terminal_panels[0].query_one('#terminal-prompt')
        assert 'status' in str(prompt.renderable)


@pytest.mark.asyncio
async def test_tui_terminal_observation_strips_control_traffic(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        from backend.cli.tui.widgets.session_panel import SessionPanel

        renderer._process_event(CmdRunAction(command='powershell'))
        renderer._process_event(
            CmdOutputObservation(
                content='PS> \x1b[32mok\x1b[0m [444444;32;15Mdone',
                command='powershell',
                exit_code=0,
            )
        )
        await pilot.pause()

        panel = next(
            panel
            for panel in s.query(SessionPanel).results()
            if 'category-shell' in panel.classes
        )
        assert not panel.processing
        assert '[444444;32;15M' not in panel._output_buffer
        assert 'ok' in panel._output_buffer


@pytest.mark.asyncio
async def test_tui_shell_command_reuses_single_card(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        from backend.cli.tui.widgets.session_panel import SessionPanel

        renderer._process_event(CmdRunAction(command='pytest -q'))
        renderer._process_event(
            CmdOutputObservation('2 passed', command='pytest -q', exit_code=0)
        )
        await pilot.pause()

        panels = s.query(SessionPanel).results()
        shell_panels = [panel for panel in panels if 'category-shell' in panel.classes]
        assert len(shell_panels) == 1
        prompt = shell_panels[0].query_one('#terminal-prompt')
        assert 'pytest -q' in str(prompt.renderable)
        header = shell_panels[0].query_one('.session-header')
        assert 'exit 0' in str(header.renderable)


@pytest.mark.asyncio
async def test_tui_lsp_query_renders_orient_line(
    mock_config,
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            LspQueryAction(
                file='app.py',
                command='find_definition',
                line=1,
                column=1,
                symbol='MyClass',
            )
        )
        renderer._process_event(
            LspQueryObservation(
                content='app.py:10:1 - class MyClass',
                available=True,
            )
        )
        await pilot.pause()

        lines = list(s.query(OrientLine).results())
        assert len(lines) == 1
        assert lines[0].model.icon == '≡'
        assert lines[0].model.verb == 'Analyzed'
        assert lines[0].model.target == 'find_definition · MyClass'
        assert lines[0].model.result == '1 result'


@pytest.mark.asyncio
async def test_tui_mcp_call_merges_action_and_observation_into_single_card(
    mock_config,
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        from backend.cli.tui.widgets.record_panel import RecordPanel

        renderer._process_event(
            MCPAction(name='search_docs', arguments={'q': 'ranking'})
        )
        renderer._process_event(
            MCPObservation(
                name='search_docs',
                arguments={'q': 'ranking'},
                content='Result snippet for ranking.',
            )
        )
        await pilot.pause()

        mcp_panels = [
            panel
            for panel in s.query(RecordPanel).results()
            if 'category-mcp' in panel.classes
        ]
        assert len(mcp_panels) == 1
        assert '-running' not in mcp_panels[0].classes
        assert '-collapsed' in mcp_panels[0].classes
        header = mcp_panels[0].query_one('.record-header-text')
        rendered = _static_render_plain(header)
        assert 'Called' in rendered
        assert 'search_docs' in rendered
        assert 'ranking' in rendered.lower()


@pytest.mark.asyncio
async def test_tui_web_search_renders_orient_line(mock_config):
    from backend.engine.tools.web_tools import build_web_search_action
    from backend.ledger.observation.mcp import MCPObservation

    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        action = build_web_search_action(
            {'query': 'Next.js 15 release notes', 'num_results': 3}
        )
        renderer._process_event(action)
        renderer._process_event(
            MCPObservation(
                name=action.name,
                arguments=action.arguments,
                content=(
                    '{"results": ['
                    '{"title": "Next.js Blog", "url": "https://nextjs.org/blog"},'
                    '{"title": "Release notes", "url": "https://example.com/notes"}'
                    ']}'
                ),
            )
        )
        await pilot.pause()

        lines = list(s.query(OrientLine).results())
        assert len(lines) == 1
        assert lines[0].model.icon == '⚐'
        assert lines[0].model.verb == 'Searched'
        assert lines[0].model.target == '"Next.js 15 release notes"'
        assert lines[0].model.result == '2 results'


@pytest.mark.asyncio
async def test_tui_web_fetch_renders_orient_line(mock_config):
    from backend.engine.tools.web_tools import build_web_fetch_action
    from backend.ledger.observation.mcp import MCPObservation

    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        action = build_web_fetch_action(
            {'urls': ['https://example.com/docs'], 'max_characters': 4000}
        )
        renderer._process_event(action)
        renderer._process_event(
            MCPObservation(
                name=action.name,
                arguments=action.arguments,
                content='{"backend":"exa","content":[{"text":"# Docs\\nHello world"}]}',
            )
        )
        await pilot.pause()

        lines = list(s.query(OrientLine).results())
        assert len(lines) == 1
        assert lines[0].model.icon == '⚐'
        assert lines[0].model.verb == 'Fetched'
        assert lines[0].model.target == 'example.com/docs'
        assert lines[0].model.result == '1 result'


@pytest.mark.asyncio
async def test_tui_delegate_task_merges_action_and_observation_into_single_card(
    mock_config,
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        from backend.cli.tui.widgets.record_panel import RecordPanel

        renderer._process_event(
            DelegateTaskAction(
                task_description='Investigate flaky test',
            )
        )
        renderer._process_event(
            DelegateTaskObservation(
                content='Worker finished successfully.',
                success=True,
            )
        )
        await pilot.pause()

        worker_panels = [
            panel
            for panel in s.query(RecordPanel).results()
            if 'category-workers' in panel.classes
        ]
        assert len(worker_panels) == 1
        assert '-running' not in worker_panels[0].classes
        header = worker_panels[0].query_one('.record-header-text')
        rendered = _static_render_plain(header)
        assert 'Delegated' in rendered
        assert 'completed' in rendered


@pytest.mark.asyncio
async def test_tui_browser_screenshot_merges_with_action_card(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        from backend.cli.tui.widgets.record_panel import RecordPanel

        renderer._process_event(
            BrowserToolAction(
                command='navigate',
                params={'url': 'https://example.com'},
            )
        )
        renderer._process_event(
            BrowserScreenshotObservation(
                image_path='/tmp/snap.png',
                content='page captured',
            )
        )
        await pilot.pause()

        browser_panels = [
            panel
            for panel in s.query(RecordPanel).results()
            if 'category-browser' in panel.classes
        ]
        assert len(browser_panels) == 1
        assert '-running' not in browser_panels[0].classes
        header = browser_panels[0].query_one('.record-header-text')
        rendered = _static_render_plain(header)
        assert 'Navigate' in rendered
        assert 'captured' in rendered


@pytest.mark.asyncio
async def test_tui_final_stream_and_message_action_do_not_duplicate(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        final_stream = StreamingChunkAction(
            accumulated='Final answer.',
            is_final=True,
        )
        final_stream.source = EventSource.AGENT
        renderer._process_event(final_stream)

        final_message = MessageAction(content='Final answer.')
        final_message.source = EventSource.AGENT
        renderer._process_event(final_message)

        assert renderer._last_final_response_text == 'Final answer.'
        assert sum(isinstance(item, AgentMessage) for item in renderer._history) == 1
        assert isinstance(renderer._history[0], AgentMessage)
        assert isinstance(renderer._history[0].renderable, Markdown)


@pytest.mark.asyncio
async def test_tui_final_stream_commits_response(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        final_stream = StreamingChunkAction(
            accumulated='Plain preview.',
            is_final=True,
        )
        final_stream.source = EventSource.AGENT
        renderer._process_event(final_stream)

        assert renderer._last_final_response_text == 'Plain preview.'
        assert renderer._live_response == ''
        assert len(renderer._history) == 2
        assert isinstance(renderer._history[0], AgentMessage)

        suppressed = MessageAction(content='', suppress_cli=True)
        suppressed.source = EventSource.AGENT
        renderer._process_event(suppressed)

        assert renderer._last_final_response_text == 'Plain preview.'
        assert renderer._live_response == ''
        assert len(renderer._history) == 2


@pytest.mark.asyncio
async def test_tui_final_stream_empty_accumulated_commits_live_response(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        # Stream chunk with content (not final)
        chunk = StreamingChunkAction(
            accumulated='Live content preview.',
            is_final=False,
        )
        chunk.source = EventSource.AGENT
        renderer._process_event(chunk)

        assert renderer._live_response == 'Live content preview.'
        assert len(renderer._history) == 0

        # Final stream chunk with empty content
        final_stream = StreamingChunkAction(
            accumulated='',
            is_final=True,
        )
        final_stream.source = EventSource.AGENT
        renderer._process_event(final_stream)

        # Should fall back to live response and commit it
        assert renderer._last_final_response_text == 'Live content preview.'
        assert renderer._live_response == ''
        assert len(renderer._history) == 2
        assert isinstance(renderer._history[0], AgentMessage)


@pytest.mark.asyncio
async def test_tui_final_stream_suppresses_live_response_for_tool_call(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        chunk = StreamingChunkAction(
            accumulated='I will inspect the workspace.',
            is_final=False,
        )
        chunk.source = EventSource.AGENT
        renderer._process_event(chunk)

        assert renderer._live_response == 'I will inspect the workspace.'
        assert len(renderer._history) == 0

        final_stream = StreamingChunkAction(
            accumulated='',
            is_final=True,
            suppress_live_response=True,
        )
        final_stream.source = EventSource.AGENT
        renderer._process_event(final_stream)

        assert renderer._last_final_response_text == ''
        assert renderer._live_response == ''
        assert len(renderer._history) == 0


@pytest.mark.asyncio
async def test_tui_streamed_response_clears_before_tool_action(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        stream = StreamingChunkAction(
            accumulated='I will inspect the workspace.',
            is_final=False,
        )
        stream.source = EventSource.AGENT
        renderer._process_event(stream)

        command = CmdRunAction(command='Get-Location')
        command.source = EventSource.AGENT
        renderer._process_event(command)

        assert renderer._last_final_response_text == ''
        assert renderer._live_response == ''
        assert len(renderer._history) == 0


@pytest.mark.asyncio
async def test_tui_duplicate_thinking_payload_renders_once(mock_config, monkeypatch):
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        thought = 'Inspecting the render path.'
        renderer._process_event(StreamingChunkAction(thinking_accumulated=thought))
        renderer._process_event(AgentThinkAction(thought=thought))
        renderer._process_event(AgentThinkObservation(content=thought))
        renderer._process_event(
            FileEditAction(
                path='demo.txt',
                command='create_file',
                file_text='finalize thinking',
            )
        )
        await pilot.pause()

        thinking_blocks = list(s.query(ThinkingIndicator).results())
        assert len(thinking_blocks) == 1
        rendered = _static_render_plain(
            thinking_blocks[0].query_one('#thinking-content', Static)
        )
        assert rendered.count(thought) == 1


@pytest.mark.asyncio
async def test_tui_thinking_indicator_shows_content_without_collapse(
    mock_config, monkeypatch
):
    """Thinking indicator shows content directly with no collapse/expand or duration."""
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        thought = 'Plotting the next move.'
        renderer._process_event(StreamingChunkAction(thinking_accumulated=thought))
        if getattr(renderer, '_deferred_stream_chunk', None) is not None:
            renderer._flush_deferred_stream_chunk()
        await pilot.pause()
        renderer._process_event(
            FileEditAction(
                path='demo.txt',
                command='create_file',
                file_text='finalize thinking',
            )
        )
        await pilot.pause()

        blocks = list(s.query(ThinkingIndicator).results())
        assert len(blocks) == 1
        block = blocks[0]

        content = block.query_one('#thinking-content', Static)
        rendered = _static_render_plain(content)
        assert thought in rendered
        assert 'Thinking:' in rendered


@pytest.mark.asyncio
async def test_tui_find_symbols_observation_renders_orient_line(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        from backend.ledger.action.search import FindSymbolsAction
        from backend.ledger.observation.search import FindSymbolsObservation

        renderer._process_event(FindSymbolsAction(query='render', path='backend'))
        renderer._process_event(
            FindSymbolsObservation(
                content='{"status":"ok"}',
                query='render',
                path='backend',
                candidates=[
                    {
                        'qualified_name': 'render',
                        'path': 'backend/app.py',
                        'start_line': 12,
                    }
                ],
            )
        )
        await pilot.pause()

        assert list(s.query(ThinkingIndicator).results()) == []
        lines = list(s.query(OrientLine).results())
        assert len(lines) == 1
        assert lines[0].model.icon == 'ƒ'
        assert lines[0].model.verb == 'Found'
        assert lines[0].model.target == '"render" in backend'
        assert lines[0].model.result == '1 symbol'


@pytest.mark.asyncio
async def test_tui_grep_observation_renders_orient_line(mock_config):
    """``GrepObservation`` renders a flat grep row with the action pattern."""
    from backend.ledger.action.search import GrepAction
    from backend.ledger.observation.search import GrepObservation

    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        renderer._process_event(
            GrepAction(pattern='_start_election', path='raftkv/node.py')
        )
        renderer._process_event(
            GrepObservation(
                content='raftkv/node.py:194:async def _start_election',
                pattern='_start_election',
                path='raftkv/node.py',
                lines=['raftkv/node.py:194:async def _start_election'],
                match_count=1,
                file_count=1,
            )
        )
        await pilot.pause()

        lines = list(s.query(OrientLine).results())
        assert len(lines) == 1
        assert lines[0].model.icon == '⌕'
        assert lines[0].model.verb == 'Grepped'
        assert lines[0].model.target == '"_start_election" in raftkv/node.py'
        assert lines[0].model.result == '1 file'


@pytest.mark.asyncio
async def test_tui_read_symbols_observation_updates_pending_card(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        from backend.ledger.action.search import ReadSymbolsAction
        from backend.ledger.observation.search import ReadSymbolsObservation

        renderer._process_event(
            ReadSymbolsAction(
                targets=[{'symbol_name': 'UserService.login'}], path='auth.py'
            )
        )
        renderer._process_event(
            ReadSymbolsObservation(
                content='{"status":"ok"}',
                path='auth.py',
                results=[
                    {
                        'status': 'resolved',
                        'qualified_name': 'UserService.login',
                        'path': 'auth.py',
                    }
                ],
            )
        )
        await pilot.pause()

        lines = list(s.query(OrientLine).results())
        assert len(lines) == 1
        assert lines[0].model.icon == '↳'
        assert lines[0].model.verb == 'Read'
        assert lines[0].model.target == '1 symbol in auth.py'
        assert lines[0].model.result == '1 resolved'


@pytest.mark.asyncio
async def test_tui_glob_observation_renders_orient_line(mock_config):
    """``GlobObservation`` renders a flat glob row with the action pattern."""
    from backend.ledger.action.search import GlobAction
    from backend.ledger.observation.search import GlobObservation

    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        renderer._process_event(GlobAction(pattern='**/*.py', path='backend'))
        renderer._process_event(
            GlobObservation(
                content='backend/app.py\nbackend/cli.py',
                pattern='**/*.py',
                path='backend',
                files=['backend/app.py', 'backend/cli.py'],
                file_count=2,
            )
        )
        await pilot.pause()

        lines = list(s.query(OrientLine).results())
        assert len(lines) == 1
        assert lines[0].model.icon == '◆'
        assert lines[0].model.verb == 'Globbed'
        assert lines[0].model.target == '**/*.py in backend'
        assert lines[0].model.result == '2 files'


@pytest.mark.asyncio
async def test_tui_grep_content_mode_uses_match_and_file_metric(mock_config):
    """Content-mode grep rows name both matches and files."""
    from backend.ledger.action.search import GrepAction
    from backend.ledger.observation.search import GrepObservation

    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        renderer._process_event(
            GrepAction(
                pattern='_start_election',
                path='raftkv/node.py',
                output_mode='content',
            )
        )
        renderer._process_event(
            GrepObservation(
                content='raftkv/node.py:194:async def _start_election',
                pattern='_start_election',
                path='raftkv/node.py',
                output_mode='content',
                lines=['raftkv/node.py:194:async def _start_election'],
                match_count=1,
                file_count=1,
            )
        )
        await pilot.pause()

        lines = list(s.query(OrientLine).results())
        assert len(lines) == 1
        assert lines[0].model.verb == 'Grepped'
        assert lines[0].model.result == '1 match · 1 file'


@pytest.mark.asyncio
async def test_tui_glob_orient_line_uses_file_labels_not_matches(mock_config):
    """Glob rows summarize files, not grep-style match counts."""
    from backend.ledger.action.search import GlobAction
    from backend.ledger.observation.search import GlobObservation

    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        renderer._process_event(GlobAction(pattern='**/*.py', path='backend'))
        renderer._process_event(
            GlobObservation(
                content='backend/app.py\nbackend/cli.py',
                pattern='**/*.py',
                path='backend',
                files=['backend/app.py', 'backend/cli.py'],
                file_count=2,
            )
        )
        await pilot.pause()

        lines = list(s.query(OrientLine).results())
        assert len(lines) == 1
        assert lines[0].model.result == '2 files'
        assert 'matches' not in lines[0].model.result.lower()


@pytest.mark.asyncio
async def test_tui_grep_files_with_matches_shows_file_count(mock_config):
    from backend.ledger.action.search import GrepAction
    from backend.ledger.observation.search import GrepObservation

    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        renderer._process_event(
            GrepAction(
                pattern='TODO',
                path='backend',
                output_mode='files_with_matches',
                file_pattern='*.py',
                head_limit=25,
            )
        )
        renderer._process_event(
            GrepObservation(
                content='backend/app.py\nbackend/cli.py',
                pattern='TODO',
                path='backend',
                output_mode='files_with_matches',
                lines=['backend/app.py', 'backend/cli.py'],
                match_count=0,
                file_count=2,
            )
        )
        await pilot.pause()

        lines = list(s.query(OrientLine).results())
        assert len(lines) == 1
        assert lines[0].model.result == '2 files'
        assert 'matches' not in lines[0].model.result.lower()


@pytest.mark.asyncio
async def test_tui_orient_lines_stay_individual_for_consecutive_lookups(mock_config):
    from backend.ledger.action.search import FindSymbolsAction, GlobAction, GrepAction
    from backend.ledger.observation.search import (
        FindSymbolsObservation,
        GlobObservation,
        GrepObservation,
    )

    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        renderer._process_event(GrepAction(pattern='TODO', path='backend'))
        renderer._process_event(
            GrepObservation(
                pattern='TODO',
                path='backend',
                lines=['backend/app.py'],
                match_count=1,
                file_count=1,
            )
        )
        renderer._process_event(GlobAction(pattern='**/*.py', path='backend'))
        renderer._process_event(
            GlobObservation(
                pattern='**/*.py',
                path='backend',
                files=['backend/app.py'],
                file_count=1,
            )
        )
        renderer._process_event(FindSymbolsAction(query='render', path='backend'))
        renderer._process_event(
            FindSymbolsObservation(
                content='{"status":"ok"}',
                query='render',
                path='backend',
                candidates=[{'qualified_name': 'render', 'path': 'backend/app.py'}],
            )
        )
        renderer._flush_orient_burst()
        await pilot.pause()

        lines = list(s.query(OrientLine).results())
        assert len(lines) == 3
        assert list(s.query(OrientBurst).results()) == []
        assert lines[0].model.verb == 'Grepped'
        assert lines[1].model.verb == 'Globbed'
        assert lines[2].model.verb == 'Found'


@pytest.mark.asyncio
async def test_tui_internal_thinking_payloads_render_as_activity_cards(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        renderer._process_event(
            AgentThinkAction(thought="[WORKING_MEMORY] Updated 'findings' section.")
        )
        renderer._process_event(
            AgentThinkAction(
                thought='[CHECKPOINT] Saved checkpoint before edit.',
                source_tool='checkpoint',
            )
        )
        await pilot.pause()

        assert list(s.query(ThinkingIndicator).results()) == []
        from backend.cli.tui.widgets.activity_card import OrientLine

        orient_lines = list(s.query(OrientLine).results())
        checkpoint_lines = [
            line for line in orient_lines if line.model.tool == 'checkpoint'
        ]
        assert len(checkpoint_lines) == 1
        assert 'Saved' in str(
            checkpoint_lines[0].query_one('#orient-content').renderable
        )


@pytest.mark.asyncio
async def test_tui_recoverable_error_renders_as_plain_error_message(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        renderer._process_event(
            AgentThinkAction(
                thought="Invalid task status 'doing'. Use one of: blocked, in_progress, done, skipped, todo.",
                kind=AgentThinkAction.KIND_RECOVERABLE_ERROR,
            )
        )
        # The mock config causes the background bootstrap to fail with an
        # AgentNotRegisteredError, which keeps `pilot.pause()` from settling
        # (a pending message sits in the screen's call_later queue). Yield
        # briefly to let the Static error widget mount, then assert directly
        # against the renderer's history.
        await asyncio.sleep(0.3)

        assert list(s.query(ThinkingIndicator).results()) == []
        # Recoverable errors render as inline ErrorBlock rows — not ActivityCards.
        cards = list(s.query(TUIActivityCard).results())
        error_cards = [card for card in cards if 'category-error' in card.classes]
        assert error_cards == []

        # The error must be in the renderer's history (the source of truth).
        from backend.cli.tui.widgets.error_block import ErrorBlock

        def _history_plain(item: object) -> str:
            if isinstance(item, ErrorBlock):
                renderable = getattr(item, '_renderable', item)
                return str(getattr(renderable, 'plain', renderable))
            return str(getattr(item, 'plain', item))

        history_text = '\n'.join(
            _history_plain(r) for r in renderer._history if r is not None
        )
        assert "Invalid task status 'doing'" in history_text


@pytest.mark.asyncio
async def test_tui_compaction_status_renders_persistent_card(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        hud = HUDBar()
        renderer = TUIRenderer(
            console=console,
            hud=hud,
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        status = StatusObservation(
            content='Compacting context...',
            status_type='compaction',
        )
        status.source = EventSource.AGENT
        renderer._process_event(status)
        await pilot.pause()

        cards = s.query(TUIActivityCard).results()
        compaction_cards = [card for card in cards if 'category-tool' in card.classes]
        assert len(compaction_cards) == 1
        collapsed = compaction_cards[0].query_one('#collapsed-row')
        assert 'Compacting (1st)' in str(collapsed.renderable)
        assert 'context' in str(collapsed.renderable)
        assert renderer._compaction_transcript_active is True
        assert renderer._condensation_count == 1


@pytest.mark.asyncio
async def test_tui_condensation_request_reuses_status_card(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        renderer._process_event(
            StatusObservation(
                content='Compacting context...',
                status_type='compaction',
            )
        )
        renderer._process_event(CondensationRequestAction())
        renderer._process_event(
            AgentCondensationObservation('Compacted summary for the next turn.')
        )
        await pilot.pause()

        compaction_cards = [
            card
            for card in s.query(TUIActivityCard).results()
            if 'category-tool' in card.classes
        ]
        assert len(compaction_cards) == 2

        started = compaction_cards[0].query_one('#collapsed-row')
        completed = compaction_cards[1].query_one('#collapsed-row')
        assert 'Compacting (1st)' in str(started.renderable)
        assert 'Compacted (1st)' in str(completed.renderable)
        assert 'Done' in str(completed.renderable)
        assert renderer._compaction_transcript_active is False


@pytest.mark.asyncio
async def test_tui_final_stream_and_normalized_message_do_not_duplicate(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        final_stream = StreamingChunkAction(
            accumulated='Final answer.',
            is_final=True,
        )
        final_stream.source = EventSource.AGENT
        renderer._process_event(final_stream)

        final_message = MessageAction(
            content=(
                '<function_calls></function_calls>\n'
                '<function name="read"><parameter name="path">a.py</parameter></function>\n'
                'Final answer.'
            )
        )
        final_message.source = EventSource.AGENT
        renderer._process_event(final_message)

        assert 'Final answer.' in renderer._last_final_response_text
        assert '<function name="read">' in renderer._last_final_response_text
        assert sum(isinstance(item, AgentMessage) for item in renderer._history) == 2
        assert isinstance(renderer._history[0], AgentMessage)


@pytest.mark.asyncio
async def test_tui_file_edit_create_renders_compact_create_card(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            FileEditAction(
                path='demo.txt',
                command='create_file',
                file_text='alpha\nbeta',
            )
        )
        await pilot.pause()
        assert not _file_change_cards(s)

        renderer._process_event(
            FileEditObservation(
                path='demo.txt',
                content='alpha\nbeta',
                outcome='created',
                new_content='alpha\nbeta',
            )
        )
        await pilot.pause()

        cards = _file_change_cards(s)
        assert len(cards) == 1
        header = str(cards[0].query_one('#file-change-header').renderable)
        assert 'demo.txt' in header
        assert '+2' in header
        assert list(s.query(UnifiedDiffRow).results())
        assert s.query_one(UnifiedDiffView)


@pytest.mark.asyncio
async def test_tui_file_edit_observation_uses_new_content_not_polluted_preview(
    mock_config,
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        polluted = (
            'File created successfully. Line endings: \\n. File preview:\n'
            '1\t# Demo File\n'
            '2\tStale preview\n'
            '\n\nFile written: demo_file.md (2 lines)\n'
            '<SYNTAX_CHECK_PASSED />'
        )
        renderer._process_event(
            FileEditObservation(
                path='demo_file.md',
                content=polluted,
                outcome='created',
                new_content='# Demo File\n\nReal body',
            )
        )
        await pilot.pause()

        add_rows = [
            row for row in s.query(UnifiedDiffRow).results() if row._row.kind == 'add'
        ]
        rendered = '\n'.join(row._row.text for row in add_rows)
        assert 'Real body' in rendered
        assert 'Stale preview' not in rendered
        assert 'File created successfully' not in rendered
        assert 'SYNTAX_CHECK' not in rendered


@pytest.mark.asyncio
async def test_tui_file_edit_create_uses_new_content_not_observation_body(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        create_action = FileEditAction(
            path='created.txt',
            command='create_file',
            file_text='alpha\nbeta',
        )
        renderer._process_event(create_action)
        renderer._process_event(create_action)
        await pilot.pause()
        assert not _file_change_cards(s)

        obs = FileEditObservation(
            path='created.txt',
            content='created',
            outcome='created',
            new_content='alpha\nbeta',
        )
        renderer._process_event(obs)
        await pilot.pause()

        cards = _file_change_cards(s)
        assert len(cards) == 1
        header = str(cards[0].query_one('#file-change-header').renderable)
        assert 'created.txt' in header
        assert '+2' in header
        assert 'Created' not in header
        assert 'Edited' not in header
        split_rows = list(s.query(UnifiedDiffRow).results())
        assert split_rows
        assert all(row._row.kind == 'add' for row in split_rows)
        assert any('alpha' in row._row.text for row in split_rows)


@pytest.mark.asyncio
async def test_tui_file_read_renders_flat_orient_line(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        long_path = (
            'backend/cli/tui/some/really/long/path/that/should/not/stretch/read_card.py'
        )
        renderer._process_event(FileReadAction(path=long_path))
        renderer._process_event(FileReadObservation(path=long_path, content='alpha'))
        await pilot.pause()

        lines = list(s.query(OrientLine).results())
        assert len(lines) == 1
        assert lines[0].model.icon == '↳'
        assert lines[0].model.verb == 'Read'
        assert lines[0].model.target.endswith('read_card.py')
        assert lines[0].model.result == 'lines 1–EOF'
        assert not list(s.query(TUIActivityCard).results())


@pytest.mark.asyncio
async def test_tui_file_read_observation_keeps_filename_visible(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        long_path = (
            'backend/cli/tui/some/really/long/path/that/should/not/stretch/read_card.py'
        )
        renderer._process_event(FileReadAction(path=long_path))
        renderer._process_event(
            FileReadObservation(path=long_path, content='alpha\nbeta\ngamma')
        )
        await pilot.pause()

        lines = list(s.query(OrientLine).results())
        assert len(lines) == 1
        assert lines[0].model.verb == 'Read'
        assert lines[0].model.target.startswith('…/')
        assert lines[0].model.target.endswith('read_card.py')
        assert lines[0].model.result == 'lines 1–EOF'
        assert not list(lines[0].query('#caret').results())


@pytest.mark.asyncio
async def test_tui_file_read_ranged_line_shows_range_metric(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._process_event(
            FileReadAction(path='backend/cli/tui/ranged_read.py', view_range=[50, 100])
        )
        renderer._process_event(
            FileReadObservation(
                path='backend/cli/tui/ranged_read.py',
                content='selected\nrange',
            )
        )
        await pilot.pause()

        lines = list(s.query(OrientLine).results())
        assert len(lines) == 1
        assert lines[0].model.target.endswith('ranged_read.py')
        assert lines[0].model.result == 'lines 50–100'


@pytest.mark.asyncio
async def test_tui_file_edit_observation_uses_unified_diff_rows(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            FileEditObservation(
                content='edited',
                path='demo.txt',
                old_content='alpha\nbeta\n',
                new_content='alpha\ngamma\nbeta\n',
            )
        )
        await pilot.pause()

        split_rows = list(s.query(UnifiedDiffRow).results())
        assert split_rows
        assert any(
            row._row.kind == 'add' and 'gamma' in row._row.text for row in split_rows
        )
        assert any(row._row.kind == 'ctx' for row in split_rows)
        assert s.query_one(UnifiedDiffView)


@pytest.mark.asyncio
async def test_tui_file_edit_action_and_observation_render_single_delta_card(
    mock_config,
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            FileEditAction(path='demo.txt', command='edit', new_str='gamma\n')
        )
        await pilot.pause()
        assert not _file_change_cards(s)

        renderer._process_event(
            FileEditObservation(
                content='edited',
                path='demo.txt',
                old_content='alpha\nbeta\n',
                new_content='alpha\ngamma\n',
            )
        )
        await pilot.pause()

        cards = _file_change_cards(s)
        assert len(cards) == 1
        header = FileChangeCard._build_header_markup('demo.txt', '+1 -1')
        assert 'demo.txt' in header
        rendered = str(cards[0].query_one('#file-change-header').renderable)
        assert '[#54efae]+1[/]' in rendered
        assert '[#fd8383]-1[/]' in rendered


@pytest.mark.asyncio
async def test_tui_replace_string_observation_renders_edited_not_created(
    mock_config,
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            FileEditAction(
                path='demo.txt',
                command='replace_string',
                old_string='alpha',
                new_str='gamma',
            )
        )
        obs = FileEditObservation(
            content='replaced',
            path='demo.txt',
            outcome='edited',
            old_content=None,
            new_content='gamma',
        )
        renderer._process_event(obs)
        await pilot.pause()

        cards = _file_change_cards(s)
        assert len(cards) == 1
        header = str(cards[0].query_one('#file-change-header').renderable)
        assert 'demo.txt' in header
        assert 'Created' not in header
        assert 'Edited' not in header


@pytest.mark.asyncio
async def test_tui_file_edit_observation_discards_pending_create_for_overwrite(
    mock_config,
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            FileEditAction(
                path='demo.txt',
                command='create_file',
                file_text='gamma',
                overwrite_existing=True,
            )
        )
        obs = FileEditObservation(
            content='overwritten',
            path='demo.txt',
            outcome='edited',
            old_content='alpha',
            new_content='gamma',
        )
        renderer._process_event(obs)
        await pilot.pause()

        cards = _file_change_cards(s)
        assert len(cards) == 1
        header = str(cards[0].query_one('#file-change-header').renderable)
        assert 'demo.txt' in header
        assert 'Created' not in header
        assert 'Edited' not in header


@pytest.mark.asyncio
async def test_tui_file_edit_observation_uses_explicit_diff_rows(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            FileEditObservation(
                content='edited',
                path='.',
                diff='--- demo.txt\n+++ demo.txt\n@@ -1 +1 @@\n-old\n+new\n',
            )
        )
        await pilot.pause()

        diff_rows = list(s.query(UnifiedDiffRow).results())
        assert s.query_one(UnifiedDiffView)
        assert any(
            row._row.kind == 'hdr' and 'demo.txt' in row._row.text for row in diff_rows
        )
        assert any(
            row._row.kind == 'add' and row._row.text == 'new' for row in diff_rows
        )
        assert any(
            row._row.kind == 'rem' and row._row.text == 'old' for row in diff_rows
        )

        file_cards = _file_change_cards(s)
        header = str(file_cards[0].query_one('#file-change-header').renderable)
        assert '[#54efae]+1[/]' in header
        assert '[#fd8383]-1[/]' in header


@pytest.mark.asyncio
async def test_tui_file_edit_observation_uses_diff_preview_rows_in_content(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            FileEditObservation(
                content=(
                    'edited\n\n<DIFF_PREVIEW>\n'
                    '--- demo.txt\n+++ demo.txt\n@@ -1 +1 @@\n-old\n+new\n'
                    '</DIFF_PREVIEW>'
                ),
                path='demo.txt',
            )
        )
        await pilot.pause()

        diff_rows = list(s.query(UnifiedDiffRow).results())
        assert s.query_one(UnifiedDiffView)
        assert any(
            row._row.kind == 'hdr' and 'demo.txt' in row._row.text for row in diff_rows
        )
        assert any(
            row._row.kind == 'add' and row._row.text == 'new' for row in diff_rows
        )
        assert any(
            row._row.kind == 'rem' and row._row.text == 'old' for row in diff_rows
        )

        file_cards = _file_change_cards(s)
        header = str(file_cards[0].query_one('#file-change-header').renderable)
        assert '[#54efae]+1[/]' in header
        assert '[#fd8383]-1[/]' in header


@pytest.mark.asyncio
async def test_tui_file_edit_observation_uses_diff_preview_rows_with_outcome(
    mock_config,
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            FileEditObservation(
                content=(
                    'wrote\n\n<DIFF_PREVIEW>\n'
                    '--- config.toml\n+++ config.toml\n@@ -1 +1 @@\n-old\n+new\n'
                    '</DIFF_PREVIEW>'
                ),
                path='config.toml',
                outcome='edited',
                new_content='new',
            )
        )
        await pilot.pause()

        diff_rows = list(s.query(UnifiedDiffRow).results())
        assert s.query_one(UnifiedDiffView)
        assert any(
            row._row.kind == 'hdr' and 'config.toml' in row._row.text
            for row in diff_rows
        )
        assert any(
            row._row.kind == 'add' and row._row.text == 'new' for row in diff_rows
        )


@pytest.mark.asyncio
async def test_tui_shell_command_empty_output_still_completes(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        from backend.cli.tui.widgets.session_panel import SessionPanel

        renderer._process_event(CmdRunAction(command='true'))
        renderer._process_event(CmdOutputObservation('', command='true', exit_code=0))
        await pilot.pause()

        panels = s.query(SessionPanel).results()
        shell_panels = [panel for panel in panels if 'category-shell' in panel.classes]
        assert len(shell_panels) == 1
        assert '-running' not in shell_panels[0].classes


def test_activity_renderer_keeps_error_heavy_success_output_expanded() -> None:
    card = ActivityRenderer.shell_command(
        'pytest',
        output='Validation failed on line 12',
        exit_code=0,
    )
    assert card.is_collapsible is True
    assert card.start_collapsed is False


@pytest.mark.asyncio
async def test_tui_error_observations_follow_visibility_policy(mock_config):
    """ErrorObservations route by transcript/context visibility policy."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer

        s.add_error_panel = MagicMock(wraps=s.add_error_panel)  # type: ignore[method-assign]
        s.add_error = MagicMock(wraps=s.add_error)  # type: ignore[method-assign]
        s.add_warning = MagicMock(wraps=s.add_warning)  # type: ignore[method-assign]
        s.notify = MagicMock()  # type: ignore[method-assign]
        s.set_runtime_status = MagicMock()  # type: ignore[method-assign]

        # Context-bearing tool-validation outcome -> persistent error card.
        renderer._process_event(
            ErrorObservation(content='Tool validation failed: bad args')
        )
        # Agent-only repair feedback -> model context only, not user transcript.
        renderer._process_event(
            ErrorObservation(content='internal repair hint', agent_only=True)
        )
        # UI-only auth failure -> red notification and runtime strip, not transcript.
        renderer._process_event(
            ErrorObservation(
                content='401 Unauthorized',
                notify_ui_only=True,
                error_category='auth',
            )
        )
        # Transient timeout -> notification only; retry StatusObservation handles strip.
        renderer._process_event(
            ErrorObservation(
                content='Timeout: provider timed out',
                notify_ui_only=True,
                error_category='timeout',
            )
        )
        await asyncio.sleep(0.1)

        assert s.add_error_panel.call_count == 1
        panel_text = s.add_error_panel.call_args.args[0]
        assert 'Tool validation failed' in panel_text
        assert s.add_error.call_count == 0
        assert s.add_warning.call_count == 0
        assert s.notify.call_count == 2
        severities = [call.kwargs['severity'] for call in s.notify.call_args_list]
        assert severities == ['error', 'warning']
        s.set_runtime_status.assert_called_once()
        assert '401 Unauthorized' in s.set_runtime_status.call_args.kwargs['meta']


@pytest.mark.asyncio
async def test_tui_add_error_and_warning_omit_hardcoded_wrap(mock_config):
    """add_error/add_warning must not pre-wrap text — let the container wrap."""
    from backend.cli.tui.screen.messages import (
        ScreenMessagesMixin,
    )
    from backend.cli.tui.widgets.error_block import ErrorBlock
    from backend.cli.tui.widgets.transcript_notice import TranscriptNotice

    long_text = 'recoverable ' + ('x' * 200)
    # Use a stub class to exercise the helper without spinning up Textual.
    stub = ScreenMessagesMixin.__new__(ScreenMessagesMixin)
    captured: list[object] = []
    stub._write_log = lambda renderable: captured.append(renderable)  # type: ignore[attr-defined]

    stub.add_error('boom')
    stub.add_warning(long_text)

    def _widget_plain(item: object) -> str:
        if isinstance(item, (ErrorBlock, TranscriptNotice)):
            renderable = getattr(item, '_renderable', None) or getattr(
                item, 'renderable', item
            )
            return str(getattr(renderable, 'plain', renderable))
        return str(getattr(item, 'plain', item))

    plain = '\n'.join(_widget_plain(item) for item in captured)
    assert isinstance(captured[0], ErrorBlock)
    assert isinstance(captured[1], TranscriptNotice)
    # The 200-char run must remain on a single line — no width=80 pre-wrap.
    assert 'x' * 200 in plain


@pytest.mark.asyncio
async def test_tui_protocol_status_is_unlabeled_dim_text(mock_config):
    from backend.cli.tui.screen.messages import (
        ScreenMessagesMixin,
    )

    stub = ScreenMessagesMixin.__new__(ScreenMessagesMixin)
    captured: list[object] = []
    stub.finalize_thinking = lambda: None  # type: ignore[attr-defined]
    stub._write_log = lambda renderable: captured.append(renderable)  # type: ignore[attr-defined]

    stub.add_protocol_status('[END_TOOL_CALL]\nWorking through the next edit.')

    assert len(captured) == 1
    rendered = captured[0]
    plain = str(getattr(rendered, 'plain', rendered))
    assert plain == 'Working through the next edit.'
    assert 'Status' not in plain
    assert 'Continue with a tool call' not in plain


@pytest.mark.asyncio
async def test_flush_live_ui_applies_deferred_stream_chunk(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._deferred_stream_chunk = StreamingChunkAction(
            accumulated='Deferred stream preview.',
            is_final=False,
        )
        renderer._stream_paint_timer_armed = True

        renderer.flush_live_ui()

        assert renderer._live_response == 'Deferred stream preview.'
        assert renderer._deferred_stream_chunk is None
        assert renderer._stream_paint_timer_armed is False


@pytest.mark.asyncio
async def test_transcript_skips_mount_animation_during_streaming(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        display = s._get_display()
        display._suppress_mount_animation = True
        widget = Static('quiet mount')
        display.append_widget(widget)
        assert float(widget.styles.offset.y.value) == 0.0


@pytest.mark.asyncio
async def test_terminal_append_does_not_remount_all_children(mock_config):
    """Incremental terminal append keeps a single tail widget."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        card = TUIActivityCard(
            verb='Terminal',
            detail='session s1',
            badge_category='terminal',
            collapsed=True,
            shell_kind='terminal',
            terminal_session_id='s1',
        )
        card.enable_incremental_mode()
        await pilot.app.mount(card)
        card.append_content_incremental('first line')
        card.append_content_incremental('second line')
        await pilot.pause()
        body = card.query_one('#expanded-body', Container)
        children = list(body.children)
        assert len(children) == 1
        assert children[0].id == 'terminal-pane'
        output = children[0].query_one('#terminal-output', Static)
        assert 'first line' in str(output.renderable)
        assert 'second line' in str(output.renderable)


@pytest.mark.asyncio
async def test_incremental_tail_highlights_partial_json(mock_config):
    """Incremental non-terminal cards should syntax-highlight as content arrives."""
    from rich.syntax import Syntax

    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        card = TUIActivityCard(
            verb='Read',
            detail='data.json',
            badge_category='code',
            collapsed=False,
        )
        card.enable_incremental_mode()
        await pilot.app.mount(card)
        card.append_content_incremental('{"name": "gr')
        await pilot.pause()

        tail = card.query_one('#incremental-tail', Static)
        assert isinstance(tail.renderable, Syntax)
        assert tail.renderable.lexer.name.lower() == 'json'


@pytest.mark.asyncio
async def test_tui_debugger_events_render_terminal_style_card(mock_config, monkeypatch):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.session_panel import SessionPanel
        from backend.cli.tui.widgets.terminal_pane import TerminalPane
        from backend.ledger.action.debugger import DebuggerAction
        from backend.ledger.observation.debugger import DebuggerObservation

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._process_event(
            DebuggerAction(
                debug_action='start',
                adapter='python',
                program='tests/demo.py',
            )
        )
        renderer._process_event(
            DebuggerObservation(
                content='debugger started',
                session_id='dbg-session-1',
                state='started',
                payload={
                    'session_id': 'dbg-session-1',
                    'state': 'started',
                    'target': 'tests/demo.py',
                    'current_thread_id': 1,
                },
            )
        )
        await pilot.pause()

        debugger_panels = [
            panel
            for panel in s.query(SessionPanel).results()
            if 'category-debugger' in panel.classes
        ]
        assert len(debugger_panels) == 1
        panel = debugger_panels[0]
        assert '-running' not in panel.classes
        assert panel._shell_kind == 'debugger'
        pane = panel.query_one('#terminal-pane', TerminalPane)
        assert pane is not None
        assert 'DAP>' in pane._prompt_markup()
        assert 'dbg-session-1'[:12] in pane._title_markup()


@pytest.mark.asyncio
async def test_tui_live_response_uses_streaming_widget(mock_config, monkeypatch):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(100, 24)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        s._renderer = renderer
        renderer.update_live_response('Streaming answer')
        await pilot.pause()

        assert isinstance(renderer._live_response_widget, LiveResponse)
        assert renderer._live_response_widget.has_class('-streaming')


@pytest.mark.asyncio
async def test_tui_tasks_sidebar_refreshes_during_streaming_skip(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_bootstrap', AsyncMock())
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.widgets.collapsible import CollapsibleSection, SidebarRow

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._task_list = [
            {'id': '1', 'description': 'First task', 'status': 'todo'},
        ]
        renderer._refresh_display(skip_sidebar=True)

        tasks_widget = s.query_one('#sidebar-tasks', CollapsibleSection)
        assert tasks_widget._section_title == 'Tasks (1)'

        renderer._task_list = [
            {'id': '1', 'description': 'First task', 'status': 'in_progress'},
        ]
        renderer._refresh_display(skip_sidebar=True)
        await pilot.pause()

        tasks_widget = s.query_one('#sidebar-tasks', CollapsibleSection)
        assert not tasks_widget.is_collapsed
        rows = list(tasks_widget.query(SidebarRow).results())
        assert any(row.has_class('-active-task') for row in rows)
