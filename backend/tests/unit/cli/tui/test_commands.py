"""Headless TUI — commands."""

from backend.tests.unit.cli.tui._shared import (
    GrintaHelpDialog,
    GrintaSessionsDialog,
    GrintaTUIApp,
    Label,
    MagicMock,
    RichConsole,
    TextArea,
    _get_screen,
    asyncio,
    pytest,
)

@pytest.mark.asyncio
async def test_tui_clear_command(mock_config):
    """Verify /clear slash command works."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        ta.text = '/clear'
        await pilot.press('enter')
        await pilot.pause()

        assert s is not None

@pytest.mark.asyncio
async def test_tui_help_shows(mock_config):
    """Verify /help opens the dedicated help modal."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        opened: dict[str, object | None] = {'dialog': None}

        def _fake_push_screen(dialog, callback=None) -> None:
            opened['dialog'] = dialog

        app.push_screen = _fake_push_screen  # type: ignore[method-assign]
        ta = s.query_one('#input', TextArea)
        ta.text = '/help'
        await pilot.press('enter')
        await pilot.pause()

        assert isinstance(opened['dialog'], GrintaHelpDialog)

@pytest.mark.asyncio
async def test_tui_settings_command_dispatches(mock_config):
    """Verify /settings dispatches to the real TUI settings handler."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        called = {'value': False}

        async def _fake_settings() -> None:
            called['value'] = True

        s._open_settings_tui = _fake_settings  # type: ignore[method-assign]

        ta = s.query_one('#input', TextArea)
        ta.text = '/settings'
        await pilot.press('enter')
        await pilot.pause()

        assert called['value'] is True

@pytest.mark.asyncio
async def test_tui_sessions_command_dispatches_with_args(mock_config):
    """Verify /sessions forwards parsed args to the session handler."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        captured: list[str] = []

        async def _fake_sessions(args: list[str]) -> None:
            captured.extend(args)

        s._run_sessions_tui = _fake_sessions  # type: ignore[method-assign]

        ta = s.query_one('#input', TextArea)
        ta.text = '/sessions --limit 7'
        await pilot.press('enter')
        await pilot.pause()

        assert captured == ['--limit', '7']

@pytest.mark.asyncio
async def test_tui_resume_command_dispatches_with_args(mock_config):
    """Verify /resume forwards parsed args to the resume handler."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        captured: list[str] = []

        async def _fake_resume(args: list[str]) -> None:
            captured.extend(args)

        s._run_resume_tui = _fake_resume  # type: ignore[method-assign]

        ta = s.query_one('#input', TextArea)
        ta.text = '/resume 3'
        await pilot.press('enter')
        await pilot.pause()

        assert captured == ['3']

@pytest.mark.asyncio
async def test_tui_sessions_modal_resume_handoff(mock_config):
    """Verify sessions modal selection triggers direct resume flow."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        resumed: dict[str, str | None] = {'sid': None}

        async def _fake_push_screen_wait(_dialog) -> str | None:
            return 'session-abc123'

        async def _fake_resume_target(target: str) -> None:
            resumed['sid'] = target

        app.push_screen_wait = _fake_push_screen_wait  # type: ignore[method-assign]
        s._resume_session_target = _fake_resume_target  # type: ignore[method-assign]

        await s._run_sessions_tui([])

        assert resumed['sid'] == 'session-abc123'

@pytest.mark.asyncio
async def test_tui_sessions_preview_shows_extended_metadata(
    mock_config, monkeypatch, tmp_path
):
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    fake_entries = [
        (
            'session-abc123456789',
            {
                'title': 'Fix TUI layout',
                'llm_model': 'openai/gpt-4o',
                'selected_repository': 'Grinta',
                'selected_branch': 'main',
                'trigger': 'gui',
                'accumulated_cost': 1.25,
                'prompt_tokens': 100,
                'completion_tokens': 40,
                'total_tokens': 140,
                'last_updated_at': '2026-05-21T12:00:00',
                'created_at': '2026-05-21T11:30:00',
            },
            42,
            tmp_path / 'session-abc123456789',
        )
    ]

    from backend.cli.session import session_manager

    monkeypatch.setattr(
        session_manager, '_find_sessions_root', lambda _config=None: tmp_path
    )
    monkeypatch.setattr(
        session_manager,
        '_list_session_entries',
        lambda root, sort_by='updated': fake_entries,
    )
    monkeypatch.setattr(
        session_manager, '_filter_sessions_fuzzy', lambda sessions, search: sessions
    )

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        dialog = GrintaSessionsDialog(mock_config)
        app.push_screen(dialog)
        await pilot.pause()

        preview = dialog.query_one('#sessions-preview')
        rendered = str(preview.renderable)
        assert 'Repository' in rendered
        assert 'Branch' in rendered
        assert 'Tokens' in rendered

@pytest.mark.asyncio
async def test_tui_inline_command_hint_updates(mock_config):
    """Verify slash command typing updates the compact HUD activity line."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        ta.text = '/sessions --s'
        await pilot.pause()

        hint = s.query_one('#hud-line-1-help', Label)
        assert 'Help' in str(hint.renderable)

@pytest.mark.asyncio
async def test_tui_command_autocomplete_for_sessions(mock_config):
    """Verify autocomplete expands slash command prefixes."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()
        s = _get_screen(app)
        ta = s.query_one('#input', TextArea)
        ta.text = '/sess'
        s.action_complete_command()
        await pilot.pause()

        assert ta.text == '/sessions '

@pytest.mark.asyncio
async def test_tui_unknown_command(mock_config):
    """Verify unknown slash command shows notification without crashing."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s.notify = MagicMock()  # type: ignore[method-assign]
        ta = s.query_one('#input', TextArea)
        ta.text = '/nonexistent'
        await pilot.press('enter')
        await pilot.pause()

        transcript = s.query_one('#main-display')
        assert transcript is not None
        s.notify.assert_called_once()
        assert 'Unknown command' in s.notify.call_args.args[0]
        assert s.notify.call_args.kwargs['severity'] == 'warning'

@pytest.mark.asyncio
async def test_tui_message_helpers(mock_config):
    """Verify message writing helpers work without error."""
    console = RichConsole()
    loop = asyncio.get_running_loop()
    app = GrintaTUIApp(config=mock_config, console=console, loop=loop)

    async with app.run_test(size=(120, 36)) as pilot:
        await pilot.pause()

        s = _get_screen(app)
        s.add_user_message('test user message')
        s.add_agent_message('test agent message')
        s.add_system_message('test system message')
        s.add_success('test success')
        s.add_error('test error')
        s.add_warning('test warning')
        s.add_tool_start('test_tool_name')
        s.add_tool_result('test tool result')
        s.add_divider()
        await pilot.pause()

        log = s.query_one('#main-display')
        assert log is not None
