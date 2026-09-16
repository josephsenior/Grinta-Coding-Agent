"""Headless TUI — Environment modal, Tasks drawer, and the HUD task summary.

MCP Servers, LSP Servers, Debug Adapters, and Skills moved from a permanent
sidebar column into ``GrintaEnvironmentDialog``, opened on demand (Ctrl+B).
Tasks moved from its own permanent sidebar column into a compact HUD line
summary plus ``GrintaTasksDialog`` (Ctrl+T) for the full list. See
backend/cli/tui/dialogs/environment.py and backend/cli/tui/dialogs/tasks.py.
"""

from backend.tests.unit.cli.tui._shared import (
    AsyncMock,
    GrintaScreen,
    GrintaTUIApp,
    HUDBar,
    ReasoningDisplay,
    RichConsole,
    SimpleNamespace,
    TaskTrackingObservation,
    _get_screen,
    asyncio,
    pytest,
)


@pytest.mark.asyncio
async def test_tui_autonomy_visibility_follows_mode(mock_config):
    from textual.widgets import Label, Select

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
async def test_environment_dialog_mcp_rows_have_switch_and_skills_are_read_only(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)
    mock_config.mcp = SimpleNamespace(
        enabled=True,
        servers=[SimpleNamespace(name='server-a', type='stdio', enabled=True)],
    )

    from backend.cli.event_rendering import sidebar as sidebar_module

    monkeypatch.setattr(
        sidebar_module,
        'load_sidebar_skill_items',
        lambda: [
            ('skill-a', 'skill:skill-a', False, 'info', None, False),
            (
                'skill-b',
                'skill:skill-b',
                False,
                'neutral',
                None,
                False,
                {'view_only': True},
            ),
        ],
    )

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.dialogs import GrintaEnvironmentDialog
        from backend.cli.tui.widgets.collapsible import McpServerRow, SidebarRow

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        skill_items = renderer._build_skills_sidebar_items()
        bundled_items = [
            item
            for item in skill_items
            if item[0] == 'skill-b' and item[6].get('view_only')
        ]
        assert len(bundled_items) == 1

        dialog = GrintaEnvironmentDialog(renderer)
        await app.push_screen(dialog)
        await pilot.pause()

        rows = list(dialog.query('.sidebar-item-row'))
        mcp_rows = [
            row for row in rows if getattr(row, 'item_id', '').startswith('mcp:')
        ]
        skill_rows = [
            row for row in rows if getattr(row, 'item_id', '').startswith('skill:')
        ]
        assert any(isinstance(row, McpServerRow) for row in mcp_rows)
        assert all(isinstance(row, SidebarRow) for row in skill_rows)
        assert all(not getattr(row, 'deletable', False) for row in skill_rows)


@pytest.mark.asyncio
async def test_environment_dialog_lists_detected_lsp_servers(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    agent_config = SimpleNamespace(enable_lsp_query=True, enable_debugger=False)
    mock_config.get_agent_config.return_value = agent_config
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.dialogs import GrintaEnvironmentDialog
        from backend.cli.tui.widgets.collapsible import CollapsibleSection, SidebarRow

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._lsp_servers_cache = {
            'pyright-langserver': SimpleNamespace(
                available=True,
                spec=SimpleNamespace(language='python', extensions=('.py', '.pyw')),
            ),
            'gopls': SimpleNamespace(
                available=False,
                spec=SimpleNamespace(language='go', extensions=('.go',)),
            ),
        }

        dialog = GrintaEnvironmentDialog(renderer)
        await app.push_screen(dialog)
        await pilot.pause()

        lsp_section = dialog.query_one('#env-lsp', CollapsibleSection)
        assert lsp_section._section_title == 'LSP Servers (1)'

        rows = [
            row
            for row in lsp_section.query(SidebarRow).results()
            if getattr(row, 'item_id', '').startswith('lsp:')
        ]
        assert len(rows) == 1
        assert rows[0]._label == 'python (pyright-langserver)'
        assert rows[0]._meta is None
        assert rows[0].interactive is False
        assert lsp_section.is_collapsed is False


@pytest.mark.asyncio
async def test_environment_dialog_lists_detected_dap_adapters(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    agent_config = SimpleNamespace(enable_lsp_query=False, enable_debugger=True)
    mock_config.get_agent_config.return_value = agent_config
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.dialogs import GrintaEnvironmentDialog
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

        dialog = GrintaEnvironmentDialog(renderer)
        await app.push_screen(dialog)
        await pilot.pause()

        dap_section = dialog.query_one('#env-dap', CollapsibleSection)
        assert dap_section._section_title == 'Debug Adapters (2)'

        rows = [
            row
            for row in dap_section.query(SidebarRow).results()
            if getattr(row, 'item_id', '').startswith('dap:')
        ]
        assert len(rows) == 2
        by_language = {row._label: row for row in rows}
        assert by_language['python']._meta is None
        assert by_language['python']._status == 'ok'
        assert by_language['javascript']._meta is None
        assert by_language['javascript']._status == 'warn'
        assert dap_section.is_collapsed is False


@pytest.mark.asyncio
async def test_environment_dialog_lsp_shows_disabled_when_feature_off(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_bootstrap', AsyncMock())
    agent_config = SimpleNamespace(enable_lsp_query=False, enable_debugger=False)
    mock_config.get_agent_config.return_value = agent_config
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.dialogs import GrintaEnvironmentDialog
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        dialog = GrintaEnvironmentDialog(renderer)
        await app.push_screen(dialog)
        await pilot.pause()

        lsp_section = dialog.query_one('#env-lsp', CollapsibleSection)
        assert lsp_section._section_title == 'LSP Servers'
        assert lsp_section.feature_enabled is False


@pytest.mark.asyncio
async def test_environment_dialog_dap_shows_disabled_when_feature_off(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_bootstrap', AsyncMock())
    agent_config = SimpleNamespace(enable_lsp_query=False, enable_debugger=False)
    mock_config.get_agent_config.return_value = agent_config
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.dialogs import GrintaEnvironmentDialog
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        dialog = GrintaEnvironmentDialog(renderer)
        await app.push_screen(dialog)
        await pilot.pause()

        dap_section = dialog.query_one('#env-dap', CollapsibleSection)
        assert dap_section._section_title == 'Debug Adapters'
        assert dap_section.feature_enabled is False


@pytest.mark.asyncio
async def test_environment_dialog_mcp_shows_disabled_when_feature_off(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_bootstrap', AsyncMock())
    from backend.cli.event_rendering import sidebar as sidebar_module

    monkeypatch.setattr(sidebar_module, 'load_sidebar_skill_items', lambda: [])
    mock_config.mcp = SimpleNamespace(
        enabled=False,
        servers=[SimpleNamespace(name='server-a', type='stdio', enabled=True)],
    )
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        if s._bootstrapping is not None:
            s._bootstrapping.set()
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.dialogs import GrintaEnvironmentDialog
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        assert renderer._sidebar_mcp_enabled() is False

        dialog = GrintaEnvironmentDialog(renderer)
        await app.push_screen(dialog)
        await pilot.pause()

        mcp_section = dialog.query_one('#env-mcp', CollapsibleSection)
        assert mcp_section._section_title == 'MCP Servers'
        assert mcp_section._content == 'Disabled'
        assert mcp_section.feature_enabled is False


@pytest.mark.asyncio
async def test_environment_dialog_mcp_server_row_shows_disabled_label(
    mock_config, monkeypatch
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_bootstrap', AsyncMock())
    from backend.cli.event_rendering import sidebar as sidebar_module

    monkeypatch.setattr(sidebar_module, 'load_sidebar_skill_items', lambda: [])
    mock_config.mcp = SimpleNamespace(
        enabled=True,
        servers=[
            SimpleNamespace(name='github', type='stdio', enabled=False),
        ],
    )
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        if s._bootstrapping is not None:
            s._bootstrapping.set()
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.dialogs import GrintaEnvironmentDialog
        from backend.cli.tui.widgets.collapsible import McpServerRow

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )

        dialog = GrintaEnvironmentDialog(renderer)
        await app.push_screen(dialog)
        await pilot.pause()

        row = dialog.query_one('McpServerRow', McpServerRow)
        label = row.query_one('#row-label')
        rendered = str(label.render())
        assert 'github' in rendered
        assert 'Disabled' in rendered
        assert '[strike]' not in rendered


@pytest.mark.asyncio
async def test_hud_task_summary_reflects_task_list(mock_config, monkeypatch):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_bootstrap', AsyncMock())
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

        # No tasks: the HUD line carries no task summary at all — no reserved
        # space for an empty panel, unlike the old permanent sidebar column.
        assert s._hud_tasks_summary_markup() == ''

        renderer._task_list = [
            {'id': '1', 'description': 'Persist task panel', 'status': 'in_progress'}
        ]
        summary = s._hud_tasks_summary_markup()
        assert '0/1' in summary
        assert 'Persist task panel' in summary

        renderer._process_event(
            TaskTrackingObservation(
                content='task tracker sync complete',
                command='update',
                task_list=[],
            )
        )
        # Ambiguous empty payloads must not silently blank out the summary.
        assert '0/1' in s._hud_tasks_summary_markup()


@pytest.mark.asyncio
async def test_tasks_dialog_lists_current_tasks(mock_config, monkeypatch):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(GrintaScreen, '_bootstrap', AsyncMock())
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.dialogs import GrintaTasksDialog
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._task_list = [
            {'id': '1', 'description': 'Persist task panel', 'status': 'done'},
            {'id': '2', 'description': 'Wire HUD summary', 'status': 'in_progress'},
        ]

        dialog = GrintaTasksDialog(renderer)
        await app.push_screen(dialog)
        await pilot.pause()

        section = dialog.query_one('#tasks-list', CollapsibleSection)
        assert section._section_title == 'Tasks · 1/2 done'


@pytest.mark.asyncio
async def test_environment_and_tasks_bindings_push_dialogs(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.dialogs import GrintaEnvironmentDialog, GrintaTasksDialog

        if s._renderer is None:
            s._renderer = TUIRenderer(
                console=console,
                hud=HUDBar(),
                reasoning=ReasoningDisplay(),
                tui=s,
                loop=loop,
            )

        s.action_show_environment()
        await pilot.pause()
        assert isinstance(app.screen, GrintaEnvironmentDialog)
        app.pop_screen()
        await pilot.pause()

        s.action_show_tasks()
        await pilot.pause()
        assert isinstance(app.screen, GrintaTasksDialog)
