"""Headless TUI — renderer file ops."""

from backend.cli.tui.widgets.activity_card import OrientLine
from backend.cli.tui.widgets.scan_line import (
    EditCard,
)
from backend.tests.unit.cli.tui._shared import (
    FileEditAction,
    FileEditObservation,
    FileReadAction,
    FileReadObservation,
    GrintaTUIApp,
    HUDBar,
    ReasoningDisplay,
    RichConsole,
    _get_screen,
    asyncio,
    pytest,
)


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

        renderer._process_event(
            FileEditObservation(
                path='demo.txt',
                content='alpha\nbeta',
                outcome='created',
                new_content='alpha\nbeta',
            )
        )
        await pilot.pause()

        cards = list(s.query(EditCard).results())
        assert len(cards) == 1
        line = str(cards[0]._line_text())
        assert 'demo.txt' in line
        assert '+2' in cards[0]._delta_text()


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

        cards = list(s.query(EditCard).results())
        assert len(cards) == 1
        line = str(cards[0]._line_text())
        delta = str(cards[0]._delta_text())
        assert 'demo_file.md' in line
        assert '✓' in delta  # SYNTAX_CHECK_PASSED
        # 1-line summary must not contain polluted content
        assert 'Stale preview' not in line
        assert 'File created successfully' not in line


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

        obs = FileEditObservation(
            path='created.txt',
            content='created',
            outcome='created',
            new_content='alpha\nbeta',
        )
        renderer._process_event(obs)
        await pilot.pause()

        cards = list(s.query(EditCard).results())
        assert len(cards) == 1
        line = str(cards[0]._line_text())
        assert 'created.txt' in line
        assert '+2' in cards[0]._delta_text()


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

        cards = list(s.query(EditCard).results())
        assert len(cards) == 1
        line = str(cards[0]._line_text())
        assert 'demo.txt' in line
        detail = cards[0].build_detail_screen()
        assert detail is not None
        assert cards[0]._encoded_diff is not None, 'EditCard should store a diff'


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

        renderer._process_event(
            FileEditObservation(
                content='edited',
                path='demo.txt',
                old_content='alpha\nbeta\n',
                new_content='alpha\ngamma\n',
            )
        )
        await pilot.pause()

        cards = list(s.query(EditCard).results())
        assert len(cards) == 1
        line = str(cards[0]._line_text())
        assert 'demo.txt' in line
        delta = cards[0]._delta_text()
        assert '+1' in delta and '-1' in delta


@pytest.mark.asyncio
async def test_tui_undo_last_edit_renders_undo_edit_card(mock_config):
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

        action = FileEditAction(path='demo.txt', command='undo_last_edit')
        action._id = 7
        renderer._process_event(action)
        await pilot.pause()

        obs = FileEditObservation(
            content='Undid last edit; restored previous file contents.',
            path='demo.txt',
            old_content='alpha\nbeta\n',
            new_content='alpha\ngamma\n',
        )
        obs.cause = 7
        renderer._process_event(obs)
        await pilot.pause()

        cards = list(s.query(EditCard).results())
        assert len(cards) == 1
        assert cards[0]._is_undo is True
        assert 'Undo' in str(cards[0]._line_text())
        assert cards[0]._encoded_diff is not None


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

        cards = list(s.query(EditCard).results())
        assert len(cards) == 1
        line = str(cards[0]._line_text())
        assert 'demo.txt' in line
        assert cards[0].build_detail_screen() is not None


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
                overwrite=True,
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

        cards = list(s.query(EditCard).results())
        assert len(cards) == 1
        line = str(cards[0]._line_text())
        assert 'demo.txt' in line
        assert cards[0].build_detail_screen() is not None


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

        cards = list(s.query(EditCard).results())
        assert len(cards) == 1
        assert cards[0]._encoded_diff is not None, 'EditCard should store a diff'
        assert cards[0].build_detail_screen() is not None


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

        cards = list(s.query(EditCard).results())
        assert len(cards) == 1
        line = str(cards[0]._line_text())
        assert 'demo.txt' in line
        assert cards[0]._encoded_diff is not None, 'EditCard should store a diff'
        assert cards[0].build_detail_screen() is not None


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

        cards = list(s.query(EditCard).results())
        assert len(cards) == 1
        line = str(cards[0]._line_text())
        assert 'config.toml' in line
        assert cards[0]._encoded_diff is not None, 'EditCard should store a diff'
        assert cards[0].build_detail_screen() is not None
