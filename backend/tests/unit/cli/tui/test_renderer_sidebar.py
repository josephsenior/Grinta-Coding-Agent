"""Headless TUI — renderer sidebar."""

from backend.tests.unit.cli.tui._shared import (
    AsyncMock,
    GrintaScreen,
    GrintaTUIApp,
    HUDBar,
    Label,
    ReasoningDisplay,
    RichConsole,
    Select,
    SimpleNamespace,
    TaskTrackingObservation,
    _get_screen,
    asyncio,
    pytest,
)


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
async def test_tui_sidebar_mcp_rows_have_switch_and_skills_are_read_only(
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
        from backend.cli.tui.widgets.collapsible import McpServerRow, SidebarRow

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._refresh_display()

        skill_items = renderer._build_skills_sidebar_items()
        bundled_items = [
            item
            for item in skill_items
            if item[0] == 'skill-b' and item[6].get('view_only')
        ]
        assert len(bundled_items) == 1

        rows = list(s.query('.sidebar-item-row'))
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
async def test_tui_lsp_sidebar_lists_detected_servers(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    agent_config = SimpleNamespace(enable_lsp_query=True, enable_debugger=False)
    mock_config.get_agent_config.return_value = agent_config
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
        assert rows[0]._label == 'python (pyright-langserver)'
        assert rows[0]._meta is None
        assert rows[0].interactive is False
        assert lsp_section.is_collapsed is False


@pytest.mark.asyncio
async def test_tui_dap_sidebar_lists_detected_adapters(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    agent_config = SimpleNamespace(enable_lsp_query=False, enable_debugger=True)
    mock_config.get_agent_config.return_value = agent_config
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
        assert by_language['python']._meta is None
        assert by_language['python']._status == 'ok'
        assert by_language['javascript']._meta is None
        assert by_language['javascript']._status == 'warn'
        assert dap_section.is_collapsed is False


@pytest.mark.asyncio
async def test_tui_lsp_sidebar_shows_disabled_when_feature_off(
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
        from textual.widgets import Static

        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._lsp_servers_cache = {
            'rust': SimpleNamespace(
                available=True,
                spec=SimpleNamespace(language='rust', extensions=('.rs',)),
            ),
        }
        renderer._last_lsp_sidebar_signature = None
        renderer._refresh_lsp_sidebar()
        await pilot.pause()

        lsp_section = s.query_one('#sidebar-lsp', CollapsibleSection)
        assert lsp_section._section_title == 'LSP Servers'
        empty = lsp_section.query_one('#empty-text', Static)
        assert 'Disabled' in str(empty.render())
        assert lsp_section.feature_enabled is False


@pytest.mark.asyncio
async def test_tui_dap_sidebar_shows_disabled_when_feature_off(
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
        from textual.widgets import Static

        from backend.cli.tui.app import TUIRenderer
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

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
        ]
        renderer._last_dap_sidebar_signature = None
        renderer._refresh_dap_sidebar()
        await pilot.pause()

        dap_section = s.query_one('#sidebar-dap', CollapsibleSection)
        assert dap_section._section_title == 'Debug Adapters'
        empty = dap_section.query_one('#empty-text', Static)
        assert 'Disabled' in str(empty.render())
        assert dap_section.feature_enabled is False


@pytest.mark.asyncio
async def test_tui_mcp_sidebar_shows_disabled_when_feature_off(
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
        from backend.cli.tui.widgets.collapsible import CollapsibleSection

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        assert renderer._sidebar_mcp_enabled() is False
        renderer._last_sidebar_state = None
        renderer._refresh_display()
        mcp_section = s.query_one('#sidebar-mcp', CollapsibleSection)
        assert mcp_section._section_title == 'MCP Servers'
        assert mcp_section._content == 'Disabled'
        from textual.widgets import Static

        empty = mcp_section.query_one('#empty-text', Static)
        assert 'Disabled' in str(empty.render())
        assert mcp_section.feature_enabled is False


@pytest.mark.asyncio
async def test_tui_mcp_server_row_shows_disabled_label_when_server_off(
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
        from backend.cli.tui.widgets.collapsible import McpServerRow

        renderer = TUIRenderer(
            console=console,
            hud=HUDBar(),
            reasoning=ReasoningDisplay(),
            tui=s,
            loop=loop,
        )
        renderer._last_sidebar_state = None
        renderer._refresh_display()
        await pilot.pause()

        row = s.query_one('McpServerRow', McpServerRow)
        label = row.query_one('#row-label')
        rendered = str(label.render())
        assert 'github' in rendered
        assert 'Disabled' in rendered
        assert '[strike]' not in rendered


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
        assert tasks_widget._section_title == 'Tasks · 0/1 done'


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
        assert tasks_widget._section_title == 'Tasks · 0/1 done'


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
        assert tasks_widget._section_title == 'Tasks'

        renderer._process_event(
            TaskTrackingObservation(
                content='viewed',
                command='view',
                task_list=[],
            )
        )

        tasks_widget = s.query_one('#sidebar-tasks', CollapsibleSection)
        assert tasks_widget._section_title == 'Tasks'


@pytest.mark.asyncio
async def test_tui_toggle_sidebar_adjusts_left_column_width(mock_config):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        sidebar = s.query_one('#sidebar')
        left_col = s.query_one('#left-column')

        # Initially, sidebar is visible (doesn't have -hidden class)
        assert not sidebar.has_class('-hidden')

        # Toggle sidebar off (hide it)
        s.action_toggle_sidebar()
        await pilot.pause()
        assert sidebar.has_class('-hidden')
        assert str(left_col.styles.width) == '100w'

        # Toggle sidebar back on (show it)
        s.action_toggle_sidebar()
        await pilot.pause()
        assert not sidebar.has_class('-hidden')
        assert str(left_col.styles.width) == '78w'

