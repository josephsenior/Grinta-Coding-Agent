"""Headless TUI — renderer tool cards."""

from unittest.mock import MagicMock

from backend.cli.tui.widgets.activity_card import OrientLine
from backend.ledger.action import TerminalCloseAction
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
    TerminalInputAction,
    TerminalObservation,
    TerminalReadAction,
    TerminalRunAction,
    TerminalWaitAction,
    TUIRenderer,
    _get_screen,
    asyncio,
    pytest,
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
async def test_tui_shell_card_correlates_by_action_id_when_command_changes(mock_config):
    """The observation may report an effective command without creating a new card."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.scan_line import ShellCard

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        action = CmdRunAction(command='python3.12 --version')
        action.id = 101
        result = CmdOutputObservation(
            'Python 3.12', command='python.12 --version', exit_code=0
        )
        result.cause = 101

        renderer._process_event(action)
        renderer._process_event(result)
        await pilot.pause()

        cards = list(s.query(ShellCard).results())
        assert len(cards) == 1
        assert cards[0].command == 'python3.12 --version'
        assert cards[0].state == 'done'


@pytest.mark.asyncio
async def test_tui_identical_shell_commands_complete_out_of_order_by_action_id(
    mock_config,
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.scan_line import ShellCard

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        first = CmdRunAction(command='pytest -q')
        second = CmdRunAction(command='pytest -q')
        first.id, second.id = 201, 202
        second_result = CmdOutputObservation('second', command='pytest -q', exit_code=0)
        first_result = CmdOutputObservation('first', command='pytest -q', exit_code=0)
        second_result.cause, first_result.cause = 202, 201

        for event in (first, second, second_result, first_result):
            renderer._process_event(event)
        await pilot.pause()

        cards = list(s.query(ShellCard).results())
        assert len(cards) == 2
        assert [card.output for card in cards] == ['first', 'second']
        assert all(card.state == 'done' for card in cards)


@pytest.mark.asyncio
async def test_tui_terminal_close_updates_existing_session_card(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.scan_line import TerminalCard

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        start = TerminalRunAction(command='npm run dev')
        start.id = 401
        started = TerminalObservation(
            session_id='terminal_1', content='ready', state='SESSION_OPENED'
        )
        started.cause = 401
        started.tool_result = {'ok': True}
        close = TerminalCloseAction(session_id='terminal_1')
        close.id = 402
        closed = TerminalObservation(
            session_id='terminal_1',
            content='Closed terminal session.',
            state='SESSION_CLOSED',
        )
        closed.cause = 402
        closed.tool_result = {'ok': True}

        for event in (start, started, close, closed):
            renderer._process_event(event)
        await pilot.pause()

        cards = list(s.query(TerminalCard).results())
        assert len(cards) == 1
        assert cards[0].state == 'done'
        assert 'Closed terminal session.' in cards[0].scrollback


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

        action = MCPAction(name='search_docs', arguments={'q': 'ranking'})
        action.id = 501
        observation = MCPObservation(
            name='search_docs',
            arguments={'q': 'ranking'},
            content='Result snippet for ranking.',
        )
        observation.cause = 501
        renderer._process_event(action)
        renderer._process_event(observation)
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

        action = DelegateTaskAction(
            task_description='Investigate flaky test',
        )
        action.id = 601
        observation = DelegateTaskObservation(
            content='Worker finished successfully.',
            success=True,
        )
        observation.cause = 601
        renderer._process_event(action)
        renderer._process_event(observation)
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

        action = BrowserToolAction(
            command='navigate',
            params={'url': 'https://example.com'},
        )
        action.id = 701
        observation = BrowserScreenshotObservation(
            content='page captured',
        )
        observation.cause = 701
        renderer._process_event(action)
        renderer._process_event(observation)
        await pilot.pause()

        cards = list(s.query(BrowserCard).results())
        assert len(cards) == 1, f'Expected 1 BrowserCard, got {len(cards)}'
        assert cards[0].state == 'done'
        assert any(
            'navigate' in str(c._line_text())
            or 'captured' in str(c._line_text())
            or 'navigate' in str(c._delta_text())
            or 'captured' in str(c._delta_text())
            for c in cards
        )


@pytest.mark.asyncio
async def test_tui_acceptance_criteria_renders_scan_line_card(mock_config):
    from backend.ledger.action import AcceptanceCriteriaAction
    from backend.ledger.observation.acceptance_criteria import (
        AcceptanceCriteriaObservation,
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
        renderer._tui._write_log = MagicMock()

        action = AcceptanceCriteriaAction(
            command='update',
            criteria_list=[
                {'assertion': 'Build succeeds', 'source': 'stated'},
                {'assertion': 'Tests pass', 'source': 'stated'},
            ],
        )
        action.id = 801
        observation = AcceptanceCriteriaObservation(
            command='update',
            criteria_list=[
                {'assertion': 'Build succeeds', 'source': 'stated'},
                {'assertion': 'Tests pass', 'source': 'stated'},
            ],
            content='✅ Acceptance criteria defined (2 items).',
        )
        observation.cause = 801
        renderer._process_event(action)
        renderer._process_event(observation)
        await pilot.pause()

        renderer._tui._write_log.assert_not_called()
        from backend.cli.tui.widgets.scan_line import AcceptanceCriteriaCard

        cards = [card for card in s.query(AcceptanceCriteriaCard).results()]
        assert len(cards) == 1
        card = cards[0]
        assert card._command == 'update'
        assert len(card._criteria_list) == 2
        assert '2 criteria' in str(card._line_text())

        detail = card.build_detail_screen()
        body_widgets = detail.build_content()
        joined = '\n'.join(
            str(getattr(widget, 'render', lambda w=widget: w)())
            for widget in body_widgets
        )
        assert 'Build succeeds' in joined
        assert 'Tests pass' in joined
        assert '●' in joined


@pytest.mark.asyncio
async def test_tui_task_state_refreshes_tasks_sidebar_without_transcript_card(
    mock_config,
):
    from backend.ledger.action import TaskStateAction
    from backend.ledger.observation import TaskStateObservation

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
        state = {
            'revision': 3,
            'contract': {'objective': 'Ship task-state cards'},
            'plan': {
                'tasks': [
                    {'id': '1', 'description': 'Add the card', 'status': 'done'},
                    {'id': '2', 'description': 'Test the card', 'status': 'todo'},
                ]
            },
        }

        renderer._process_event(TaskStateAction(command='set'))
        renderer._process_event(
            TaskStateObservation(
                command='set',
                revision=3,
                state=state,
                content='TASK STATE (revision 3)\n\nPLAN\n[done] 1 Add the card',
            )
        )
        await pilot.pause()

        renderer._tui._write_log.assert_not_called()
        from backend.cli.tui.widgets.collapsible import CollapsibleSection, SidebarRow

        tasks = s.query_one('#sidebar-tasks', CollapsibleSection)
        assert tasks._section_title == 'Tasks · 1/2 done'
        rows = list(tasks.query(SidebarRow).results())
        assert len(rows) == 2


@pytest.mark.asyncio
async def test_tui_task_state_error_does_not_create_transcript_card(mock_config):
    from backend.ledger.action import TaskStateAction
    from backend.ledger.observation import ErrorObservation

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
        renderer._process_event(TaskStateAction(command='update_task'))
        renderer._process_event(
            ErrorObservation("Task state error: Task '99' not found.")
        )
        await pilot.pause()

        assert not renderer._task_list
