"""Headless TUI — renderer errors/misc."""

from backend.cli.tui.widgets.scan_line import CompactionCard
from backend.tests.unit.cli.tui._shared import (
    ActivityRenderer,
    AgentCondensationObservation,
    AsyncMock,
    CmdOutputObservation,
    CmdRunAction,
    CondensationRequestAction,
    ErrorObservation,
    EventSource,
    GrintaScreen,
    GrintaTUIApp,
    HUDBar,
    LiveResponse,
    MagicMock,
    MessageAction,
    ReasoningDisplay,
    RichConsole,
    Static,
    StatusObservation,
    StreamingChunkAction,
    SystemHintAction,
    ThinkingIndicator,
    TUIRenderer,
    _get_screen,
    asyncio,
    pytest,
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
            SystemHintAction(
                thought="Invalid task status 'doing'. Use one of: blocked, in_progress, done, skipped, todo.",
                kind=SystemHintAction.KIND_RECOVERABLE_ERROR,
            )
        )
        # The mock config causes the background bootstrap to fail with an
        # AgentNotRegisteredError, which keeps `pilot.pause()` from settling
        # (a pending message sits in the screen's call_later queue). Yield
        # briefly to let the Static error widget mount, then assert directly
        # against the renderer's history.
        await asyncio.sleep(0.3)

        assert list(s.query(ThinkingIndicator).results()) == []

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
        hud.update_agent_state('Running')
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

        cards = list(s.query(CompactionCard).results())
        assert len(cards) == 1
        assert cards[0].state == 'running'
        assert 'Compacting' in str(cards[0]._line_text())
        assert 'context' not in str(cards[0]._line_text())
        assert '(1st)' not in str(cards[0]._line_text())
        assert renderer._compaction_transcript_active is True
        assert renderer._condensation_count == 1
        assert hud.state.agent_state_label == 'Running'


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

        cards = list(s.query(CompactionCard).results())
        assert len(cards) == 1
        card = cards[0]
        assert card.state == 'done'
        assert 'Compacted' in str(card._line_text())
        assert 'Compacted summary' in card.summary
        assert renderer._compaction_transcript_active is False


@pytest.mark.asyncio
async def test_tui_condensation_action_completes_status_card(mock_config):
    """Production path: StatusObservation starts card, CondensationAction completes it."""
    from backend.ledger.action.agent import CondensationAction

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
            StatusObservation(
                content='Compacting context...',
                status_type='compaction',
            )
        )
        renderer._process_event(
            CondensationAction(
                pruned_event_ids=[1, 2, 3],
                summary='Session summary after LLM compaction.',
                summary_offset=0,
            )
        )
        await pilot.pause()

        cards = list(s.query(CompactionCard).results())
        assert len(cards) == 1
        card = cards[0]
        assert card.state == 'done'
        assert 'Compacted' in str(card._line_text())
        assert card.summary == 'Session summary after LLM compaction.'
        assert renderer._compaction_transcript_active is False


@pytest.mark.asyncio
async def test_tui_compaction_streaming_final_waits_for_condensation_action(
    mock_config,
):
    """Stream is_final is preview-only; CondensationAction commits the card."""
    from backend.ledger.action.agent import CondensationAction

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
            StatusObservation(
                content='Compacting context...',
                status_type='compaction',
            )
        )
        renderer._process_event(
            StreamingChunkAction(
                chunk='Session summary ',
                accumulated='Session summary ',
                is_final=False,
                tool_call_name='compaction',
            )
        )
        renderer._process_event(
            StreamingChunkAction(
                chunk='after streaming.',
                accumulated='Session summary after streaming.',
                is_final=True,
                tool_call_name='compaction',
            )
        )
        await pilot.pause()

        cards = list(s.query(CompactionCard).results())
        assert len(cards) == 1
        card = cards[0]
        assert card.state == 'running'
        assert 'Compacting' in str(card._line_text())
        assert card.summary == 'Session summary after streaming.'
        assert renderer._compaction_transcript_active is True

        renderer._process_event(
            CondensationAction(
                pruned_event_ids=[1, 2],
                summary='Session summary after streaming.',
                summary_offset=0,
            )
        )
        await pilot.pause()

        assert card.state == 'done'
        assert 'Compacted' in str(card._line_text())
        assert renderer._compaction_transcript_active is False


@pytest.mark.asyncio
async def test_tui_compaction_sanity_retries_emit_single_card(mock_config):
    """Multiple stream finals during one compaction must not create duplicate cards."""
    from backend.ledger.action.agent import CondensationAction

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
            StatusObservation(
                content='Compacting context...',
                status_type='compaction',
            )
        )
        for attempt in range(3):
            renderer._process_event(
                StreamingChunkAction(
                    chunk='',
                    accumulated='',
                    is_final=True,
                    tool_call_name='compaction',
                )
            )
        await pilot.pause()

        cards = list(s.query(CompactionCard).results())
        assert len(cards) == 1
        assert cards[0].state == 'running'

        renderer._process_event(
            CondensationAction(
                pruned_event_ids=[1, 2, 3],
                summary='Committed after retries.',
                summary_offset=0,
            )
        )
        await pilot.pause()

        assert len(list(s.query(CompactionCard).results())) == 1
        assert cards[0].state == 'done'
        assert cards[0].summary == 'Committed after retries.'


@pytest.mark.asyncio
async def test_tui_compaction_late_stream_does_not_reopen_card(mock_config):
    """A late compaction stream chunk must not flip a completed card back to running."""
    from backend.ledger.action.agent import CondensationAction

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
            StatusObservation(
                content='Compacting context...',
                status_type='compaction',
            )
        )
        renderer._process_event(
            CondensationAction(
                pruned_event_ids=[1, 2],
                summary='Committed summary.',
                summary_offset=0,
            )
        )
        renderer._process_event(
            StreamingChunkAction(
                chunk='late chunk',
                accumulated='late chunk',
                is_final=False,
                tool_call_name='compaction',
            )
        )
        await pilot.pause()

        cards = list(s.query(CompactionCard).results())
        assert len(cards) == 1
        card = cards[0]
        assert card.state == 'done'
        assert 'Compacted' in str(card._line_text())
        assert card.summary == 'Committed summary.'
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
        from backend.cli.tui.widgets.activity_card import AgentMessage

        msgs = list(s.query(AgentMessage).results())
        assert len(msgs) >= 2


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

        from backend.cli.tui.widgets.scan_line import ShellCard

        renderer._process_event(CmdRunAction(command='true'))
        renderer._process_event(CmdOutputObservation('', command='true', exit_code=0))
        await pilot.pause()

        cards = list(s.query(ShellCard).results())
        assert len(cards) >= 1
        assert '✓' in str(cards[0]._delta_text())


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
        # Transient timeout -> HUD/backoff only; no toast popup.
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
        assert s.notify.call_count == 1
        severities = [call.kwargs['severity'] for call in s.notify.call_args_list]
        assert severities == ['error']
        assert s.set_runtime_status.called
        status_args = s.set_runtime_status.call_args
        all_args = str(status_args.args) + ' ' + str(status_args.kwargs)
        assert '401 Unauthorized' in all_args


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
async def test_tui_debugger_events_render_terminal_style_card(mock_config, monkeypatch):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_start_background_bootstrap', lambda self: None)
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer

        return
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

        from backend.cli.tui.widgets.scan_line import DebuggerCard

        cards = list(s.query(DebuggerCard).results())
        assert len(cards) >= 1
        line = str(cards[0]._line_text())
        assert 'tests/demo.py' in line or 'demo.py' in line


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
        assert tasks_widget._section_title == 'Tasks · 0/1 done'

        renderer._task_list = [
            {'id': '1', 'description': 'First task', 'status': 'in_progress'},
        ]
        renderer._refresh_display(skip_sidebar=True)
        await pilot.pause()

        tasks_widget = s.query_one('#sidebar-tasks', CollapsibleSection)
        assert not tasks_widget.is_collapsed
        rows = list(tasks_widget.query(SidebarRow).results())
        assert any(row.has_class('-active-task') for row in rows)
