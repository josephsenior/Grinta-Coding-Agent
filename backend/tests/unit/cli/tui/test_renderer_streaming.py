"""Headless TUI — renderer streaming."""

from backend.tests.unit.cli.tui._shared import (
    AgentThinkAction,
    AgentThinkObservation,
    CmdRunAction,
    EventSource,
    FileEditAction,
    GrintaScreen,
    GrintaTUIApp,
    HUDBar,
    MessageAction,
    ReasoningDisplay,
    RichConsole,
    Static,
    StreamingChunkAction,
    ThinkingIndicator,
    TUIRenderer,
    _get_screen,
    _static_render_plain,
    asyncio,
    pytest,
)


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
        from backend.cli.tui.widgets.activity_card import AgentMessage

        msgs = list(s.query(AgentMessage).results())
        assert len(msgs) == 1


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

        suppressed = MessageAction(content='', suppress_cli=True)
        suppressed.source = EventSource.AGENT
        renderer._process_event(suppressed)

        assert renderer._last_final_response_text == 'Plain preview.'
        assert renderer._live_response == ''
        assert (
            len(renderer._history) == 1
        )  # suppressed message should not add to history


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
        from backend.cli.tui.widgets.activity_card import AgentMessage

        msgs = list(s.query(AgentMessage).results())
        assert len(msgs) >= 1


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
        assert renderer._live_response == 'I will inspect the workspace.'
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
async def test_tui_tool_step_message_then_tool_card_in_order(mock_config):
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
            StreamingChunkAction(
                accumulated='I will inspect the workspace.',
                is_final=False,
            )
        )
        renderer._process_event(
            StreamingChunkAction(
                accumulated='',
                is_final=True,
                suppress_live_response=True,
            )
        )
        assert renderer._live_response == 'I will inspect the workspace.'
        renderer._process_event(
            MessageAction(
                content='I will inspect the workspace.',
                transcript_only=True,
            )
        )
        renderer._process_event(CmdRunAction(command='Get-Location'))
        await pilot.pause()

        from backend.cli.tui.widgets.activity_card import AgentMessage
        from backend.cli.tui.widgets.scan_line import ShellCard

        msgs = list(s.query(AgentMessage).results())
        shells = list(s.query(ShellCard).results())
        assert len(msgs) == 1
        assert len(shells) == 1
        assert renderer._live_response == ''
        assert renderer._last_streamed_preamble_text == 'I will inspect the workspace.'


@pytest.mark.asyncio
async def test_tui_tool_step_does_not_duplicate_partial_stream_preamble(mock_config):
    """Final suppress must not commit a partial live snapshot before MessageAction."""
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
            StreamingChunkAction(accumulated='Now let me', is_final=False)
        )
        renderer._process_event(
            StreamingChunkAction(
                accumulated='',
                is_final=True,
                suppress_live_response=True,
            )
        )
        renderer._process_event(
            MessageAction(
                content='Now let me create the elementwise operators:',
                transcript_only=True,
            )
        )
        await pilot.pause()

        from backend.cli.tui.widgets.activity_card import AgentMessage

        msgs = list(s.query(AgentMessage).results())
        assert len(msgs) == 1


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
