"""Headless TUI — renderer tool cards."""

from backend.tests.unit.cli.tui._shared import (
    BrowserScreenshotObservation,
    BrowserToolAction,
    CmdOutputObservation,
    CmdRunAction,
    DelegateTaskAction,
    DelegateTaskObservation,
    GrintaTUIApp,
    HUDBar,
    LspQueryAction,
    LspQueryObservation,
    MCPAction,
    MCPObservation,
    ReasoningDisplay,
    RichConsole,
    TUIRenderer,
    TerminalInputAction,
    TerminalObservation,
    TerminalReadAction,
    TerminalRunAction,
    TerminalWaitAction,
    _get_screen,
    asyncio,
    pytest,
)
from unittest.mock import MagicMock

from backend.cli.tui.widgets.activity_card import OrientLine
from backend.cli.tui.widgets.scan_line import (
    EditCard,
)

@pytest.mark.asyncio
async def test_tui_terminal_wait_action_is_silent_in_transcript(mock_config):
    """TerminalWaitAction must not fall through to the unknown-event log line."""
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
        renderer._tui._write_log = MagicMock()
        renderer._process_event(
            TerminalWaitAction(session_id='term-1', pattern='ready', timeout=5)
        )
        await pilot.pause()
        renderer._tui._write_log.assert_not_called()


@pytest.mark.asyncio
async def test_tui_terminal_session_reuses_single_card(mock_config):
    """Terminal now appends one TerminalCard per command (not upserting SessionPanel)."""

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

        from backend.cli.tui.widgets.scan_line import TerminalCard

        renderer._process_event(TerminalRunAction(command='npm run dev'))
        renderer._process_event(TerminalReadAction(session_id='term-1'))
        renderer._process_event(
            TerminalObservation(session_id='term-1', content='ready')
        )
        renderer._process_event(
            TerminalInputAction(session_id='term-1', input='status')
        )
        await pilot.pause()

        cards = list(s.query(TerminalCard).results())
        assert len(cards) >= 2, f'Expected >=2 TerminalCards, got {len(cards)}'
        # Verify cards exist and can produce detail screens
        for c in cards:
            assert c.build_detail_screen() is not None

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

        from backend.cli.tui.widgets.scan_line import ShellCard

        renderer._process_event(CmdRunAction(command='powershell'))
        renderer._process_event(
            CmdOutputObservation(
                content='PS> \x1b[32mok\x1b[0m [444444;32;15Mdone',
                command='powershell',
                exit_code=0,
            )
        )
        await pilot.pause()

        cards = list(s.query(ShellCard).results())
        assert len(cards) >= 1
        card = cards[0]
        assert '[444444;32;15M' not in card.output
        assert 'ok' in card.output

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

        from backend.cli.tui.widgets.scan_line import ShellCard

        renderer._process_event(CmdRunAction(command='pytest -q'))
        renderer._process_event(
            CmdOutputObservation('2 passed', command='pytest -q', exit_code=0)
        )
        await pilot.pause()

        cards = list(s.query(ShellCard).results())
        assert len(cards) == 1, f'Expected 1 ShellCard, got {len(cards)}'
        assert 'pytest -q' in str(cards[0]._line_text())
        assert cards[0]._state == 'done'

@pytest.mark.asyncio
async def test_tui_shell_command_reuses_card_with_mixed_case_flags(mock_config):
    """CmdRun and CmdOutput must use the same command key (no .lower() on complete)."""
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

        command = "sed -n '168,171p' autograd/demo.py | cat -A"
        renderer._process_event(CmdRunAction(command=command))
        renderer._process_event(
            CmdOutputObservation('line1$', command=command, exit_code=0)
        )
        await pilot.pause()

        cards = list(s.query(ShellCard).results())
        assert len(cards) == 1, f'Expected 1 ShellCard, got {len(cards)}'
        assert cards[0]._state == 'done'
        assert 'cat -A' in cards[0].command

@pytest.mark.asyncio
async def test_tui_shell_command_reuses_card_with_multiline_command(mock_config):
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

        command = 'python3 -c "\nimport sys\nsys.path.insert(0, \'.\')\nprint(1)"'
        renderer._process_event(CmdRunAction(command=command))
        renderer._process_event(
            CmdOutputObservation('1\n', command=command, exit_code=0)
        )
        await pilot.pause()

        cards = list(s.query(ShellCard).results())
        assert len(cards) == 1, f'Expected 1 ShellCard, got {len(cards)}'
        assert cards[0]._state == 'done'
        line = str(cards[0]._line_text())
        assert '\n' not in line
        assert 'import sys' in line

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

        from backend.cli.tui.widgets.scan_line import MCPCard

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

        mcp_cards = list(s.query(MCPCard).results())
        assert len(mcp_cards) == 1
        assert mcp_cards[0].state == 'done'
        line = str(mcp_cards[0]._line_text())
        assert 'Called' in line
        assert 'search_docs' in line
        assert 'ranking' in line.lower()

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

        from backend.cli.tui.widgets.scan_line import DelegateCard

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

        delegate_cards = list(s.query(DelegateCard).results())
        assert len(delegate_cards) == 1
        assert delegate_cards[0].state == 'done'
        line = str(delegate_cards[0]._line_text())
        assert 'Delegated' in line
        assert 'Investigate flaky test' in line


@pytest.mark.asyncio
async def test_tui_browser_cmd_output_does_not_create_shell_card(mock_config):
    """Browser tool emits CmdOutputObservation; it must not produce a ShellCard."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.scan_line import BrowserCard, ShellCard

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        renderer._process_event(
            BrowserToolAction(
                command='navigate',
                params={'url': 'https://example.com'},
            )
        )
        renderer._process_event(
            CmdOutputObservation(
                'Navigated to https://example.com',
                command='browser navigate',
                exit_code=0,
            )
        )
        await pilot.pause()

        browser_cards = list(s.query(BrowserCard).results())
        shell_cards = list(s.query(ShellCard).results())
        assert len(browser_cards) >= 1, 'Expected a BrowserCard'
        assert len(shell_cards) == 0, f'Expected no ShellCard, got {len(shell_cards)}'


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

        from backend.cli.tui.widgets.scan_line import BrowserCard

        renderer._process_event(
            BrowserToolAction(
                command='navigate',
                params={'url': 'https://example.com'},
            )
        )
        renderer._process_event(
            BrowserScreenshotObservation(
                content='page captured',
            )
        )
        await pilot.pause()

        cards = list(s.query(BrowserCard).results())
        assert len(cards) >= 1, f'Expected >=1 BrowserCard, got {len(cards)}'
        assert any(
            'navigate' in str(c._line_text())
            or 'captured' in str(c._line_text())
            or 'navigate' in str(c._delta_text())
            or 'captured' in str(c._delta_text())
            for c in cards
        )

