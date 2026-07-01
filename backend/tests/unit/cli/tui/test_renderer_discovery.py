"""Headless TUI — renderer discovery/orient."""

from backend.tests.unit.cli.tui._shared import (
    AgentThinkAction,
    GrintaTUIApp,
    HUDBar,
    ReasoningDisplay,
    RichConsole,
    TUIRenderer,
    ThinkingIndicator,
    _get_screen,
    asyncio,
    pytest,
)

from backend.cli.tui.widgets.activity_card import OrientLine
from backend.cli.tui.widgets.scan_line import (
    EditCard,
)

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
        assert checkpoint_lines[0].model.icon == '├'
        assert 'Saved' in str(
            checkpoint_lines[0].query_one('#orient-content').renderable
        )

