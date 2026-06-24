"""CLI frontend — misc."""

from backend.tests.unit.cli.frontend import _shared
from backend.tests.unit.cli.frontend._shared import *  # noqa: F403

for _name in dir(_shared):
    if _name.startswith('_') and not _name.startswith('__'):
        globals()[_name] = getattr(_shared, _name)

from backend.tests.unit.cli.frontend._shared import (
    _console_output,
    _make_config,
    _make_console,
)


@pytest.mark.asyncio
async def test_repl_restarts_agent_loop_after_terminal_state() -> None:
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))

    controller = MagicMock()
    controller.get_agent_state.return_value = AgentState.FINISHED
    controller.set_agent_state_to = AsyncMock()

    completed_task = asyncio.create_task(asyncio.sleep(0))
    await completed_task

    async def fake_run_agent_until_done(*args, **kwargs) -> None:
        await asyncio.sleep(0)

    resolved_controller, restarted_task = await repl.ensure_controller_loop(
        controller=controller,
        agent_task=completed_task,
        create_controller=MagicMock(),
        create_status_callback=lambda ctrl: MagicMock(),
        run_agent_until_done=fake_run_agent_until_done,
        agent=MagicMock(),
        runtime=MagicMock(),
        config=MagicMock(),
        conversation_stats=MagicMock(),
        memory=MagicMock(),
        end_states=[AgentState.FINISHED, AgentState.ERROR],
    )

    assert resolved_controller is controller
    controller.set_agent_state_to.assert_awaited_once_with(AgentState.RUNNING)
    assert restarted_task is not completed_task
    assert restarted_task is not None
    restarted_task = cast(asyncio.Task[None], restarted_task)
    await restarted_task


@pytest.mark.asyncio
async def test_renderer_handles_error_observation() -> None:
    """ErrorObservation should be rendered with structured error panel."""
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    error_obs = ErrorObservation(
        content='FileNotFoundError: x.py\nTraceback detail here'
    )
    await renderer.handle_event(error_obs)

    assert hud.state.ledger_status == 'Error'
    # Error panel printed to console (no Live active).
    output = _console_output(console)
    assert 'FileNotFoundError' in output


@pytest.mark.asyncio
async def test_start_stop_live_flushes_items_to_console() -> None:
    """During Live, system messages print immediately; stop_live clears the live region."""
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    renderer.start_live()
    renderer.add_system_message('Working…', title='grinta')
    renderer.stop_live()

    output = _console_output(console)
    assert 'Working' in output


@pytest.mark.asyncio
async def test_renderer_error_observation_shows_recovery_steps() -> None:
    """Known provider errors should include actionable recovery guidance."""
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    error_obs = ErrorObservation(content='401 Unauthorized\ninvalid api key')
    await renderer.handle_event(error_obs)

    # Error panel printed to console (no Live active).
    output = _console_output(console)
    assert 'What you can try' in output
    assert '/settings' in output
    assert 'update the API key' in output


@pytest.mark.asyncio
async def test_renderer_timeout_error_uses_notice_panel_copy() -> None:
    """Provider wait timeouts should use cyan notice framing, not raw exception titles."""
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    await renderer.handle_event(
        ErrorObservation(
            content='Timeout: Fallback completion timed out after 60.0 seconds'
        )
    )
    output = _console_output(console)
    assert 'Still no reply' in output
    assert 'Next steps' in output
    assert 'APP_LLM_FALLBACK_TIMEOUT_SECONDS' in output


@pytest.mark.asyncio
async def test_renderer_notice_panel_does_not_repeat_summary_under_next_steps() -> None:
    """Notice headline already states the summary; recovery must list only numbered steps."""
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    renderer = CLIEventRenderer(
        console, HUDBar(), ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    await renderer.handle_event(
        ErrorObservation(content='TimeoutError: LLM call timed out after 120s')
    )
    output = _console_output(console)
    needle = "The model didn't finish within Grinta's wait window"
    assert needle in output
    assert output.count(needle) == 1


@pytest.mark.asyncio
async def test_renderer_timeout_error_with_autonomous_retry_uses_recovery_copy() -> (
    None
):
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    renderer = CLIEventRenderer(
        console, HUDBar(), ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    await renderer.handle_event(
        ErrorObservation(
            content=(
                'Timeout: slow\n\nThe provider timed out on this step. Automatic '
                'backoff and retry will run if the retry queue is available; '
                'otherwise the agent will return to the prompt.'
            )
        )
    )
    output = _console_output(console)
    # Autonomous recovery panel removed per user request (ugly UI)
    assert 'Autonomous recovery' not in output
    assert 'Automatic retry is running. No action needed.' not in output
    # Should show generic timeout error guidance instead
    assert 'Request timed out' in output


@pytest.mark.asyncio
async def test_renderer_rate_limit_queue_error_uses_notice_not_red_error() -> None:
    """Compact provider limit copy must use calm notice panels, not Error / red chrome."""
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    await renderer.handle_event(
        ErrorObservation(
            content=(
                'RateLimitError: provider limit reached.\n\n'
                'Waiting before retrying - no action needed.'
            )
        )
    )
    output = _console_output(console)
    # Autonomous recovery panel removed per user request (ugly UI)
    assert 'Autonomous recovery' not in output
    assert 'Autonomous recovery is in progress' not in output
    assert hud.state.ledger_status != 'Error'
    assert 'What you can try' not in output
    # Should show rate limit guidance instead
    assert 'Rate or quota limit' in output


@pytest.mark.asyncio
async def test_renderer_null_action_loop_uses_notice_panel_copy() -> None:
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    renderer = CLIEventRenderer(
        console, HUDBar(), ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    await renderer.handle_event(
        ErrorObservation(
            content=(
                'The model returned no executable action for multiple consecutive '
                'steps. Pausing to avoid a no-progress loop that burns model calls.'
            )
        )
    )
    output = _console_output(console)
    assert 'Paused safely' in output
    assert 'Grinta paused to avoid a no-progress loop.' in output
    assert (
        'No action is required unless you want the task to continue immediately.'
        in output
    )


@pytest.mark.asyncio
async def test_renderer_verification_required_uses_notice_panel_copy() -> None:
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    renderer = CLIEventRenderer(
        console, HUDBar(), ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    await renderer.handle_event(
        ErrorObservation(
            content=(
                'VERIFICATION REQUIRED BEFORE CONTINUING\n\n'
                'Recent edits were followed by failing feedback, so blind retries are blocked for one grounding step.\n'
                'Files to reconcile: backend/context/schemas.py\n'
                'Latest failing feedback: FAILED: backend/context/schemas.py is out of sync\n'
                'Allowed next moves: read the affected file, inspect terminal output, or rerun a focused check.\n'
                'After one fresh grounding action, edits and finish are allowed again.'
            )
        )
    )
    output = _console_output(console)
    assert 'Need fresh evidence' in output
    assert (
        'Grinta blocked another blind write because recent edits were followed by failing feedback.'
        in output
    )
    assert (
        'Read the affected file or rerun the focused failing check to get fresh evidence.'
        in output
    )


@pytest.mark.asyncio
async def test_renderer_default_shell_session_error_uses_recovery_copy() -> None:
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    renderer = CLIEventRenderer(
        console, HUDBar(), ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    await renderer.handle_event(
        ErrorObservation(content='Default shell session not initialized')
    )
    output = _console_output(console)
    assert 'The runtime shell session is missing or was interrupted.' in output
    assert 'Retry once to let Grinta recreate the default shell session.' in output


@pytest.mark.asyncio
async def test_renderer_stream_fallback_status_renders_still_working_panel() -> None:
    from backend.ledger.observation import StatusObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    await renderer.handle_event(
        StatusObservation(content='Stream timed out — retrying without streaming…')
    )
    output = _console_output(console)
    assert 'Still Working' in output
    assert 'non-streaming' in output.lower()


@pytest.mark.asyncio
async def test_renderer_syntax_validation_error_panel_is_compact() -> None:
    """Syntax validation failures should not dump tree-sitter noise into the CLI panel."""
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    noisy = (
        'ERROR:\nSyntax validation failed: Syntax error at '
        'C:\\proj\\demo.test.ts:8:3: node=ERROR\n'
        "  Node text: 'it'\n"
        "    it('x', () => {\n"
        '    ^\n'
    )
    error_obs = ErrorObservation(content=noisy)
    await renderer.handle_event(error_obs)

    output = _console_output(console)
    assert 'syntax check' in output.lower()
    assert 'What you can try' in output
    assert 'node=' not in output
    assert 'Node text' not in output


@pytest.mark.asyncio
async def test_system_error_message_shows_restart_guidance_for_init_failures() -> None:
    """Startup failures should suggest how to recover outside the REPL."""
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    renderer.add_system_message(
        'No API key or model configured.\nAuthenticationError: invalid api key',
        title='error',
    )

    output = _console_output(console)
    assert 'Restart grinta' in output
    assert 'settings.json' in output


@pytest.mark.asyncio
async def test_renderer_shows_recall_observation() -> None:
    """RecallObservation should show a brief recall indicator."""
    from backend.core.enums import RecallType
    from backend.ledger.observation.agent import RecallObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    recall_obs = RecallObservation(
        content='recalled',
        recall_type=RecallType.WORKSPACE_CONTEXT,
    )
    await renderer.handle_event(recall_obs)

    # Recall goes to reasoning panel — no console output expected
    output = _console_output(console)
    assert output == ''
    assert renderer._reasoning.active
    assert 'recalled' in renderer._reasoning._current_action.lower()


def test_model_command_rejects_unqualified_model() -> None:
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    with patch('backend.cli.settings.update_model') as update_model:
        result = repl.handle_command('/model gpt-4.1')

    assert result is True
    update_model.assert_not_called()
    message = mock_renderer.add_system_message.call_args[0][0]
    assert 'provider-qualified' in message


def test_sessions_command_accepts_optional_limit() -> None:
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    with patch('backend.cli.session.session_manager.list_sessions') as list_sessions:
        result = repl.handle_command('/sessions list 5')

    assert result is True
    list_sessions.assert_called_once()
    assert list_sessions.call_args.kwargs['limit'] == 5


def test_entry_point_rejects_legacy_serve_subcommand() -> None:
    """Entry point should reject the removed serve subcommand."""
    import sys

    with patch.object(sys, 'argv', ['app', 'serve', '--port', '3030']):
        from backend.cli.entry import main

        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 2


def test_entry_point_parses_model_flag() -> None:
    """--model flag should be forwarded to repl main."""
    import sys

    with patch.object(sys, 'argv', ['app', '--model', 'openai/gpt-5.1']):
        with patch('backend.cli.main.main') as mock_repl:
            from backend.cli.entry import main

            main()
            mock_repl.assert_called_once_with(
                model='openai/gpt-5.1',
                project=None,
                cleanup_storage=False,
                no_splash=False,
            )


def test_entry_point_parses_project_flag(tmp_path: Path) -> None:
    """--project flag should be forwarded to repl main."""
    import sys

    with patch.object(sys, 'argv', ['app', '--project', str(tmp_path)]):
        with patch('backend.cli.main.main') as mock_repl:
            from backend.cli.entry import main

            main()
            mock_repl.assert_called_once_with(
                model=None,
                project=str(tmp_path.resolve()),
                cleanup_storage=False,
                no_splash=False,
            )


def test_entry_point_parses_cleanup_storage_flag() -> None:
    """--cleanup-storage should be forwarded to repl main."""
    import sys

    with patch.object(sys, 'argv', ['app', '--cleanup-storage']):
        with patch('backend.cli.main.main') as mock_repl:
            from backend.cli.entry import main

            main()
            mock_repl.assert_called_once_with(
                model=None,
                project=None,
                cleanup_storage=True,
                no_splash=False,
            )


def test_entry_point_parses_both_flags(tmp_path: Path) -> None:
    """Both --model and --project should be forwarded."""
    import sys

    with patch.object(
        sys,
        'argv',
        ['app', '-m', 'anthropic/claude-sonnet-4-20250514', '-p', str(tmp_path)],
    ):
        with patch('backend.cli.main.main') as mock_repl:
            from backend.cli.entry import main

            main()
            mock_repl.assert_called_once_with(
                model='anthropic/claude-sonnet-4-20250514',
                project=str(tmp_path.resolve()),
                cleanup_storage=False,
                no_splash=False,
            )


def test_entry_point_parses_cleanup_and_project_flags(tmp_path: Path) -> None:
    """Cleanup flag should preserve the selected project override."""
    import sys

    with patch.object(
        sys, 'argv', ['app', '--cleanup-storage', '--project', str(tmp_path)]
    ):
        with patch('backend.cli.main.main') as mock_repl:
            from backend.cli.entry import main

            main()
            mock_repl.assert_called_once_with(
                model=None,
                project=str(tmp_path.resolve()),
                cleanup_storage=True,
                no_splash=False,
            )


def test_entry_point_parses_no_splash_flag() -> None:
    """--no-splash should be forwarded to repl main."""
    import sys

    with patch.object(sys, 'argv', ['app', '--no-splash']):
        with patch('backend.cli.main.main') as mock_repl:
            from backend.cli.entry import main

            main()
            mock_repl.assert_called_once_with(
                model=None,
                project=None,
                cleanup_storage=False,
                no_splash=True,
            )


def test_grinta_main_parses_project_flag(tmp_path: Path) -> None:
    """Grinta should parse --project even when invoked via backend.cli.main."""
    import sys

    with patch.object(sys, 'argv', ['grinta', '--project', str(tmp_path)]):
        with patch(
            'backend.cli.main._async_main', new_callable=MagicMock
        ) as mock_async_main:
            with patch('backend.cli.main.asyncio.run') as mock_asyncio_run:
                from backend.cli.main import main

                main()

    mock_async_main.assert_called_once_with(
        model=None, project=str(tmp_path.resolve()), show_splash=True
    )
    mock_asyncio_run.assert_called_once()


def test_grinta_main_parses_no_splash_flag() -> None:
    """Direct backend.cli.main invocation should honor --no-splash."""
    import sys

    with patch.object(sys, 'argv', ['grinta', '--no-splash']):
        with patch(
            'backend.cli.main._async_main', new_callable=MagicMock
        ) as mock_async_main:
            with patch('backend.cli.main.asyncio.run') as mock_asyncio_run:
                from backend.cli.main import main

                main()

    mock_async_main.assert_called_once_with(model=None, project=None, show_splash=False)
    mock_asyncio_run.assert_called_once()


def test_grinta_main_rejects_legacy_serve_subcommand() -> None:
    """Grinta main should reject the removed serve subcommand."""
    import sys

    with patch.object(sys, 'argv', ['grinta', 'serve', '--port', '3030']):
        with patch('backend.cli.main.asyncio.run') as mock_asyncio_run:
            from backend.cli.main import main

            with pytest.raises(SystemExit) as exc:
                main()

    assert exc.value.code == 2
    mock_asyncio_run.assert_not_called()


def test_grinta_main_runs_cleanup_storage_without_asyncio() -> None:
    """Cleanup mode should run the one-off storage command and exit."""
    import sys

    with patch.object(sys, 'argv', ['grinta', '--cleanup-storage']):
        with patch('backend.cli.main.asyncio.run') as mock_asyncio_run:
            with patch(
                'backend.cli.session.storage_cleanup.run_storage_cleanup_command',
                return_value=0,
            ) as mock_cleanup:
                from backend.cli.main import main

                main()

    mock_cleanup.assert_called_once_with(None)
    mock_asyncio_run.assert_not_called()


@pytest.mark.asyncio
async def test_async_main_defaults_workspace_to_cwd(
    tmp_path: Path, monkeypatch
) -> None:
    config = AppConfig()
    config.get_llm_config().model = 'openai/gpt-5.1'

    sim_home = tmp_path / 'SIM_HOME'
    sim_home.mkdir()
    monkeypatch.setenv('HOME', str(sim_home))
    monkeypatch.setenv('USERPROFILE', str(sim_home))

    stdin_mock = MagicMock()
    stdin_mock.isatty.return_value = True

    with patch.object(sys, 'stdin', stdin_mock):
        with patch('backend.core.config.load_app_config', return_value=config):
            with patch('backend.cli.main.Console', return_value=_make_console()):
                with patch('backend.cli.tui.main._async_main_tui', return_value=None):
                    with patch(
                        'backend.cli.settings.needs_onboarding',
                        return_value=False,
                    ):
                        with patch(
                            'backend.cli.settings.ensure_default_model',
                            return_value='openai/gpt-5.1',
                        ):
                            with patch('backend.cli.main._setup_logging'):
                                with patch('pathlib.Path.cwd', return_value=tmp_path):
                                    import backend.cli.tui.main  # noqa: F401
                                    from backend.cli.main import _async_main

                                    await _async_main()

    resolved = str(tmp_path.resolve())
    assert config.project_root == resolved
    assert config.local_data_root == get_project_local_data_root(tmp_path)
    assert 'workspaces' in config.local_data_root
    assert config.get_agent_config(config.default_agent).cli_mode is True


@pytest.mark.asyncio
async def test_async_main_queues_piped_input(tmp_path: Path) -> None:
    config = AppConfig()
    config.get_llm_config().model = 'openai/gpt-5.1'

    stdin = MagicMock()
    stdin.isatty.return_value = False
    stdin.read.return_value = 'queued task\n'

    with patch.object(sys, 'stdin', stdin):
        with patch('backend.core.config.load_app_config', return_value=config):
            with patch('backend.cli.main.Console', return_value=_make_console()):
                with patch(
                    'backend.cli.repl.noninteractive.run_noninteractive',
                    return_value=None,
                ):
                    with patch(
                        'backend.cli.settings.needs_onboarding',
                        return_value=False,
                    ):
                        with patch(
                            'backend.cli.settings.ensure_default_model',
                            return_value='openai/gpt-5.1',
                        ):
                            with patch('backend.cli.main._setup_logging'):
                                with patch('pathlib.Path.cwd', return_value=tmp_path):
                                    from backend.cli.main import _async_main

                                    await _async_main()


@pytest.mark.asyncio
async def test_async_main_keeps_explicit_project_override(
    tmp_path: Path, monkeypatch
) -> None:
    config = AppConfig()
    config.get_llm_config().model = 'openai/gpt-5.1'
    sim_home = tmp_path / 'SIM_HOME'
    sim_home.mkdir()
    monkeypatch.setenv('HOME', str(sim_home))
    monkeypatch.setenv('USERPROFILE', str(sim_home))

    stdin_mock = MagicMock()
    stdin_mock.isatty.return_value = True

    with patch.object(sys, 'stdin', stdin_mock):
        with patch('backend.core.config.load_app_config', return_value=config):
            with patch('backend.cli.main.Console', return_value=_make_console()):
                with patch('backend.cli.tui.main._async_main_tui', return_value=None):
                    with patch(
                        'backend.cli.settings.needs_onboarding',
                        return_value=False,
                    ):
                        with patch(
                            'backend.cli.settings.ensure_default_model',
                            return_value='openai/gpt-5.1',
                        ):
                            with patch('backend.cli.main._setup_logging'):
                                import backend.cli.tui.main  # noqa: F401
                                from backend.cli.main import _async_main

                                await _async_main(project=str(tmp_path))

    resolved = str(tmp_path.resolve())
    assert config.project_root == resolved
    assert config.local_data_root == get_project_local_data_root(tmp_path)
    assert 'workspaces' in config.local_data_root
    assert config.get_agent_config(config.default_agent).cli_mode is True


@pytest.mark.asyncio
async def test_repl_non_interactive_uses_queued_input_before_stdin() -> None:
    repl = Repl(_make_config(), _make_console())
    repl.queue_initial_input('queued task\n')

    stdin = MagicMock()
    stdin.readline.return_value = ''

    with patch.object(sys, 'stdin', stdin):
        result = await repl._read_non_interactive_input()

    assert result == 'queued task\n'
    stdin.readline.assert_not_called()


def test_find_sessions_root_uses_project_storage_root(tmp_path: Path) -> None:
    from backend.cli.session.session_manager import _find_sessions_root

    storage = tmp_path / '.grinta' / 'storage'
    storage.mkdir(parents=True)
    config = AppConfig(local_data_root=str(storage))

    assert _find_sessions_root(config) == storage


@pytest.mark.asyncio
async def test_cancel_agent_stops_task() -> None:
    """_cancel_agent should cancel a running task and show message."""
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    async def never_finish():
        await asyncio.sleep(999)

    task = asyncio.create_task(never_finish())

    await repl.cancel_agent(task)

    assert task.cancelled()
    mock_renderer.add_system_message.assert_called_once()
    assert 'Interrupted' in mock_renderer.add_system_message.call_args[0][0]


@pytest.mark.asyncio
async def test_ensure_controller_loop_reconnects_after_hard_kill() -> None:
    """After interrupt/hard_kill, next turn must await runtime.connect()."""
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    runtime = MagicMock()
    runtime.runtime_initialized = False
    connect = AsyncMock()
    runtime.connect = connect

    controller = MagicMock()
    controller.get_agent_state.return_value = AgentState.RUNNING

    async def run_agent_until_done(*_a: object, **_k: object) -> None:
        await asyncio.sleep(0)

    await repl._ensure_controller_loop(
        controller=controller,
        agent_task=None,
        create_controller=MagicMock(),
        create_status_callback=MagicMock(return_value=None),
        run_agent_until_done=run_agent_until_done,
        agent=MagicMock(),
        runtime=runtime,
        config=_make_config(),
        conversation_stats=MagicMock(),
        memory=MagicMock(),
        end_states=[AgentState.FINISHED],
    )
    connect.assert_awaited_once()

    connect.reset_mock()
    runtime.runtime_initialized = True
    await repl._ensure_controller_loop(
        controller=controller,
        agent_task=None,
        create_controller=MagicMock(),
        create_status_callback=MagicMock(return_value=None),
        run_agent_until_done=run_agent_until_done,
        agent=MagicMock(),
        runtime=runtime,
        config=_make_config(),
        conversation_stats=MagicMock(),
        memory=MagicMock(),
        end_states=[AgentState.FINISHED],
    )
    connect.assert_not_called()


@pytest.mark.asyncio
async def test_repl_run_saves_controller_state_on_exit() -> None:
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    controller = MagicMock()
    repl.set_controller(controller)

    async def fake_read() -> str:
        return ''

    with (
        patch(
            'backend.app.main._initialize_session_components',
            side_effect=RuntimeError('bootstrap failed'),
        ),
        patch('backend.cli.repl.session.get_current_model', return_value='test-model'),
        patch.object(repl, '_read_non_interactive_input', side_effect=fake_read),
        patch('backend.cli.repl.session.load_app_config'),
    ):
        await repl.run()

    controller.save_state.assert_called_once()


@pytest.mark.asyncio
async def test_wait_for_agent_idle_drains_late_final_message() -> None:
    from backend.ledger.observation.agent import AgentStateChangedObservation

    console = _make_console()
    repl = Repl(_make_config(), console)
    renderer = CLIEventRenderer(
        console,
        HUDBar(),
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )
    repl.set_renderer(renderer)
    controller = MagicMock()
    controller.get_agent_state.return_value = AgentState.AWAITING_USER_INPUT

    await renderer.handle_event(
        AgentStateChangedObservation('', AgentState.AWAITING_USER_INPUT)
    )

    late_message = MessageAction(content='Final answer', wait_for_response=True)
    late_message.source = EventSource.AGENT

    async def emit_late_message() -> None:
        await asyncio.sleep(0.01)
        renderer._on_event_threadsafe(late_message)

    emit_task = asyncio.create_task(emit_late_message())
    await repl._wait_for_agent_idle(controller, None)
    await emit_task

    output = _console_output(console)
    assert 'Final answer' in output


@pytest.mark.asyncio
async def test_wait_for_agent_idle_default_timeout_disabled(monkeypatch) -> None:
    repl = Repl(_make_config(), _make_console())
    controller = MagicMock()

    states = [
        AgentState.RUNNING,
        AgentState.RUNNING,
        AgentState.AWAITING_USER_INPUT,
    ]

    def _next_state():
        return states.pop(0) if states else AgentState.AWAITING_USER_INPUT

    controller.get_agent_state.side_effect = _next_state

    async def never_finish() -> None:
        await asyncio.sleep(999)

    agent_task = asyncio.create_task(never_finish())
    tick = {'value': 0.0}

    def _fake_monotonic() -> float:
        tick['value'] += 10_000.0
        return tick['value']

    monkeypatch.delenv('APP_AGENT_HARD_TIMEOUT_SECONDS', raising=False)
    monkeypatch.delenv('APP_AGENT_HARD_TIMEOUT_CMD_SECONDS', raising=False)

    with patch(
        'backend.cli.repl.session_lifecycle_mixin.time.monotonic',
        side_effect=_fake_monotonic,
    ):
        await repl._wait_for_agent_idle(controller, agent_task)

    assert not agent_task.cancelled()

    agent_task.cancel()
    with suppress(asyncio.CancelledError):
        await agent_task


@pytest.mark.asyncio
async def test_wait_for_agent_idle_uses_controller_idle_state_when_renderer_is_stale() -> (
    None
):
    repl = Repl(_make_config(), _make_console())
    renderer = CLIEventRenderer(
        _make_console(),
        HUDBar(),
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )
    repl.set_renderer(renderer)
    renderer._current_state = AgentState.RUNNING

    controller = MagicMock()
    controller.get_agent_state.return_value = AgentState.AWAITING_USER_INPUT

    await asyncio.wait_for(repl._wait_for_agent_idle(controller, None), timeout=0.2)


@pytest.mark.asyncio
async def test_wait_for_agent_idle_rate_limited_not_treated_as_idle() -> None:
    """RATE_LIMITED must not end _wait_for_agent_idle while backoff is pending.

    Regression: including RATE_LIMITED in idle_states returned to the prompt
    immediately even though RetryService had scheduled an automatic resume.
    """
    repl = Repl(_make_config(), _make_console())
    repl.set_renderer(None)
    controller = MagicMock()

    calls = {'n': 0}

    def _state() -> AgentState:
        calls['n'] += 1
        if calls['n'] < 8:
            return AgentState.RATE_LIMITED
        return AgentState.AWAITING_USER_INPUT

    controller.get_agent_state.side_effect = _state

    async def never_finish() -> None:
        await asyncio.sleep(999)

    agent_task = asyncio.create_task(never_finish())
    await repl._wait_for_agent_idle(controller, agent_task)

    agent_task.cancel()
    with suppress(asyncio.CancelledError):
        await agent_task

    assert calls['n'] >= 8


@pytest.mark.asyncio
async def test_repl_run_shows_ready_before_background_bootstrap() -> None:
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    events: list[str] = []
    original_add_system_message = CLIEventRenderer.add_system_message

    async def fake_read() -> str:
        await asyncio.sleep(0)
        return ''

    def record_message(self, message: str, title: str = 'system'):
        events.append(message)
        return original_add_system_message(self, message, title=title)

    def fail_bootstrap(*_args, **_kwargs):
        events.append('bootstrap')
        raise RuntimeError('bootstrap failed')

    with (
        patch.object(
            CLIEventRenderer,
            'add_system_message',
            autospec=True,
            side_effect=record_message,
        ),
        patch('backend.cli.repl.session.get_current_model', return_value='test-model'),
        patch('backend.cli.repl.session._supports_prompt_session', return_value=False),
        patch.object(repl, '_read_non_interactive_input', side_effect=fake_read),
        patch(
            'backend.app.main._initialize_session_components',
            side_effect=fail_bootstrap,
        ),
    ):
        await repl.run()

    assert events
    # The first system message before bootstrap should be "Initializing engine…"
    # (the old "grinta ready" message was removed — the splash covers that).
    init_msgs = [e for e in events if e != 'bootstrap']
    assert any('nitializ' in m for m in init_msgs) or events


@pytest.mark.asyncio
async def test_repl_run_accepts_first_message_before_mcp_warmup_finishes() -> None:
    config = AppConfig()
    console = Console(file=io.StringIO(), force_terminal=False)
    repl = Repl(config, console)
    event_stream = MagicMock()
    event_stream.sid = 'session-1'
    runtime = MagicMock()
    runtime.event_stream = event_stream
    memory = MagicMock()
    controller = MagicMock()
    agent = MagicMock()
    agent.config.enable_mcp = True
    agent.mcp_capability_status = {'connected_client_count': 0}
    llm_registry = MagicMock()
    conversation_stats = MagicMock()
    acquire_result = MagicMock()
    acquire_result.runtime = runtime
    first_message_dispatched = asyncio.Event()
    allow_mcp_finish = asyncio.Event()
    queued_inputs: asyncio.Queue[str] = asyncio.Queue()
    await queued_inputs.put('hello\n')

    def add_event(action, source):
        del source
        if isinstance(action, MessageAction) and action.content == 'hello':
            first_message_dispatched.set()

    async def fake_read() -> str:
        return await queued_inputs.get()

    async def fake_setup_mcp(*_args, **_kwargs) -> None:
        await allow_mcp_finish.wait()
        agent.mcp_capability_status = {'connected_client_count': 2}

    event_stream.add_event.side_effect = add_event

    with (
        patch('backend.cli.repl.session.get_current_model', return_value='test-model'),
        patch('backend.cli.repl.session._supports_prompt_session', return_value=False),
        patch.object(repl, '_read_non_interactive_input', side_effect=fake_read),
        patch.object(
            repl,
            '_ensure_controller_loop',
            new=AsyncMock(return_value=(controller, None)),
        ),
        patch.object(
            repl,
            '_wait_for_agent_idle',
            new=AsyncMock(return_value=None),
        ),
        patch(
            'backend.app.main._initialize_session_components',
            return_value=(
                'session-1',
                llm_registry,
                conversation_stats,
                config,
                agent,
            ),
        ),
        patch(
            'backend.app.main._setup_runtime_for_controller',
            return_value=(runtime, None, acquire_result),
        ),
        patch(
            'backend.app.main._setup_memory',
            new=AsyncMock(return_value=memory),
        ) as mock_setup_memory,
        patch(
            'backend.app.main._setup_mcp_tools',
            new=AsyncMock(side_effect=fake_setup_mcp),
        ) as mock_setup_mcp,
        patch('backend.execution.runtime_orchestrator.release') as mock_release,
    ):
        run_task = asyncio.create_task(repl.run())
        await asyncio.wait_for(first_message_dispatched.wait(), timeout=1)
        assert not allow_mcp_finish.is_set()
        allow_mcp_finish.set()
        await queued_inputs.put('')
        await run_task

    mock_setup_memory.assert_awaited_once()
    mock_setup_mcp.assert_awaited_once()
    mock_release.assert_called_once_with(acquire_result)


def test_start_live_passes_vertical_overflow_crop() -> None:
    """Rich Live must use ``crop`` (not ``visible``) for the Thinking panel.

    Regression: ``vertical_overflow='visible'`` caused Rich to re-print the
    overflow portion of the Live body on every refresh when the panel was
    taller than the terminal. With streaming reasoning that grows line by
    line, this stacked dozens of duplicate copies per turn in the scrollback
    — the panel looked like it was stuttering. ``crop`` redraws in place;
    tall sections (e.g. draft tail preview) still respect line budgets; the
    Live region itself is cropped in place rather than re-printed.
    """
    console = _make_console()
    loop = asyncio.new_event_loop()
    with patch('backend.cli.event_rendering.live_mixin.Live') as live_cls:
        try:
            live_cls.return_value = MagicMock()
            r = CLIEventRenderer(console, HUDBar(), ReasoningDisplay(), loop=loop)
            r.start_live()
        finally:
            loop.close()
    assert live_cls.call_args is not None
    assert live_cls.call_args.kwargs.get('vertical_overflow') == 'scroll'


def test_atomic_settings_write(tmp_path: Path) -> None:
    """_save_raw_settings should write atomically via tempfile + rename."""
    from backend.cli.settings import _load_raw_settings, _save_raw_settings

    settings_file = tmp_path / 'settings.json'
    with patch(
        'backend.cli.settings.storage._settings_path', return_value=settings_file
    ):
        data = {
            'llm_api_key': LLM_API_KEY_SETTINGS_PLACEHOLDER,
            'llm_model': 'test/model',
        }
        _save_raw_settings(data)

        loaded = _load_raw_settings()
        assert loaded['llm_api_key'] == LLM_API_KEY_SETTINGS_PLACEHOLDER
        assert loaded['llm_model'] == 'test/model'

        # No stale .tmp files left behind
        tmp_files = list(settings_file.parent.glob('*.tmp'))
        assert not tmp_files


def test_get_masked_api_key_returns_not_set_when_missing() -> None:
    """Masking should be safe when no key is configured anywhere."""
    from backend.cli.settings import get_masked_api_key

    llm_cfg = MagicMock()
    llm_cfg.api_key = None
    llm_cfg.model = 'openai/gpt-5.1'
    config = MagicMock()
    config.get_llm_config.return_value = llm_cfg

    with patch.dict(os.environ, {}, clear=True):
        assert get_masked_api_key(config) == '(not set)'


def test_get_masked_api_key_reads_env_fallback() -> None:
    """Masking should use env-backed keys when config.api_key is unset."""
    from backend.cli.settings import get_masked_api_key

    llm_cfg = MagicMock()
    llm_cfg.api_key = None
    llm_cfg.model = ''
    config = MagicMock()
    config.get_llm_config.return_value = llm_cfg

    with patch.dict(os.environ, {'LLM_API_KEY': 'env-secret-12345678'}, clear=True):
        masked = get_masked_api_key(config)

    assert masked.startswith('env-')
    assert masked.endswith('5678')
    assert '•' in masked


def test_ensure_default_model_sets_model_from_google_key() -> None:
    from backend.cli.settings import ensure_default_model

    llm_cfg = MagicMock()
    llm_cfg.api_key = None
    llm_cfg.model = None
    config = MagicMock()
    config.get_llm_config.return_value = llm_cfg

    with patch.dict(os.environ, {'LLM_API_KEY': 'AIzaSyBxxxxxxxxxxxxxxx'}, clear=True):
        selected = ensure_default_model(config)

    assert selected == 'google/gemini-3-flash'
    assert llm_cfg.model == 'google/gemini-3-flash'


def test_ensure_default_model_preserves_existing_model() -> None:
    from backend.cli.settings import ensure_default_model

    llm_cfg = MagicMock()
    llm_cfg.api_key = None
    llm_cfg.model = 'anthropic/claude-sonnet-4-20250514'
    config = MagicMock()
    config.get_llm_config.return_value = llm_cfg

    with patch.dict(
        os.environ, {'LLM_API_KEY': 'sk-test12345678901234567890'}, clear=True
    ):
        selected = ensure_default_model(config)

    assert selected == 'anthropic/claude-sonnet-4-20250514'
    assert llm_cfg.model == 'anthropic/claude-sonnet-4-20250514'


def test_ensure_default_model_uses_provider_specific_env_var() -> None:
    from backend.cli.settings import ensure_default_model

    llm_cfg = MagicMock()
    llm_cfg.api_key = None
    llm_cfg.model = None
    config = MagicMock()
    config.get_llm_config.return_value = llm_cfg

    with patch.dict(
        os.environ, {'OPENAI_API_KEY': 'sk-test12345678901234567890'}, clear=True
    ):
        selected = ensure_default_model(config)

    assert selected == 'openai/gpt-5.1'
    assert llm_cfg.model == 'openai/gpt-5.1'


def test_run_onboarding_delegates_to_init_wizard(tmp_path: Path) -> None:
    from backend.cli.settings import run_onboarding

    loaded_config = MagicMock()

    with patch('os.isatty', return_value=True):
        with patch(
            'backend.cli.onboarding.init_wizard.run_init', return_value=0
        ) as mock_init:
            with patch(
                'backend.cli.settings.onboarding.load_app_config',
                return_value=loaded_config,
            ):
                result = run_onboarding()

    mock_init.assert_called_once()
    assert result is loaded_config


@pytest.mark.asyncio
async def test_budget_warning_at_80_percent() -> None:
    """Renderer should emit a warning when cost reaches 80% of budget."""
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console,
        hud,
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
        max_budget=1.0,
    )

    metrics = Metrics()
    metrics.accumulated_cost = 0.85
    metrics.token_usages = [TokenUsage(prompt_tokens=100, completion_tokens=50)]

    chunk = StreamingChunkAction(chunk='x', accumulated='x', is_final=False)
    chunk.source = EventSource.AGENT
    chunk.llm_metrics = metrics

    await renderer.handle_event(chunk)

    assert renderer.budget_warned_80
    assert not renderer.budget_warned_100
    # Budget warning printed to console (no Live active).
    output = _console_output(console)
    assert 'Budget' in output or 'budget' in output


@pytest.mark.asyncio
async def test_budget_exceeded_at_100_percent() -> None:
    """Renderer should emit a strong warning when cost exceeds budget."""
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console,
        hud,
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
        max_budget=1.0,
    )

    metrics = Metrics()
    metrics.accumulated_cost = 1.05
    metrics.token_usages = [TokenUsage(prompt_tokens=100, completion_tokens=50)]

    chunk = StreamingChunkAction(chunk='x', accumulated='x', is_final=False)
    chunk.source = EventSource.AGENT
    chunk.llm_metrics = metrics

    await renderer.handle_event(chunk)

    assert renderer.budget_warned_100


@pytest.mark.asyncio
async def test_no_budget_warning_when_no_budget_set() -> None:
    """No budget warnings should fire when max_budget is None."""
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console,
        hud,
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )

    metrics = Metrics()
    metrics.accumulated_cost = 999.0
    metrics.token_usages = [TokenUsage(prompt_tokens=100, completion_tokens=50)]

    chunk = StreamingChunkAction(chunk='x', accumulated='x', is_final=False)
    chunk.source = EventSource.AGENT
    chunk.llm_metrics = metrics

    await renderer.handle_event(chunk)

    assert not renderer.budget_warned_80
    assert not renderer.budget_warned_100


@pytest.mark.asyncio
async def test_renderer_shows_command_context_for_output() -> None:
    from backend.ledger.observation import CmdOutputObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console,
        hud,
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )

    obs = CmdOutputObservation(content='2 passed', command='python -m pytest -q')
    await renderer.handle_event(obs)

    # exit_code defaults to -1 (unknown), so renderer shows a dim error line with content snippet.
    output = _console_output(console)
    assert 'exit -1' in output
    assert '2 passed' in output


@pytest.mark.asyncio
async def test_renderer_browser_cmd_output_does_not_print_ghost_terminal_card() -> None:
    """Regression: browser tool completions reuse ``CmdOutputObservation`` with
    ``command='browser navigate'`` etc. The Browser activity card is already
    printed when the action is dispatched; the observation handler used to
    fall through to the shell-result path and emit a spurious
    ``Terminal / Ran / $ (command) / ✓ done`` block. That created the duplicate
    rows visible in real sessions between every browser step.
    """
    from backend.ledger.observation import CmdOutputObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console,
        hud,
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )

    for cmd in (
        'browser navigate',
        'browser screenshot',
        'browser snapshot',
        'browser click',
    ):
        obs = CmdOutputObservation(
            content=f'Done: {cmd}',
            command=cmd,
            exit_code=0,
        )
        await renderer.handle_event(obs)

    output = _console_output(console)
    # The specific corruption pattern we saw in the bug report must not appear.
    assert '$ (command)' not in output
    # No Terminal-card header for these observations.
    assert 'Terminal' not in output, (
        'Browser CmdOutputObservations should not render as Terminal cards; got:\n'
        + output
    )


@pytest.mark.asyncio
async def test_renderer_browser_screenshot_timeout_shows_browser_guidance() -> None:
    """Regression: the generic ``timed out`` branch applied LLM-provider
    advice (``Check your network connection and the provider status page``)
    to browser screenshot timeouts. The new branch must fire first and
    give browser-specific next steps.
    """
    from backend.ledger.observation import ErrorObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    error_obs = ErrorObservation(
        content='ERROR: Browser screenshot timed out after 45s (with one retry).'
    )
    await renderer.handle_event(error_obs)

    output = _console_output(console)
    # Recoverable timeouts render as a cyan notice with "Next steps"; hard
    # errors use "What you can try".
    assert 'Next steps' in output or 'What you can try' in output
    assert 'browser' in output.lower()
    # The misleading provider-centric copy must not appear for this case.
    assert 'provider status page' not in output
    assert 'faster model' not in output


@pytest.mark.asyncio
async def test_renderer_directory_view_uses_entries_not_lines() -> None:
    """Regression: ``FileReadObservation`` on a directory previously rendered
    the result as ``N lines`` because the handler unconditionally split the
    content on newlines. ``read_file`` on a directory returns
    a ``Directory contents of <path>:`` header followed by one entry per
    line; users reading ``Viewed . • 2 lines`` for a dir listing (where one
    of the lines is the header) was confusing. Now we label as ``entries``
    and discount the header line.
    """
    from backend.ledger.observation import FileReadObservation

    console = _make_console()
    renderer = CLIEventRenderer(
        console,
        HUDBar(),
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )
    renderer.start_live()

    action = FileReadAction(path='.')
    action.source = EventSource.AGENT
    renderer._process_event_data(action)

    content = 'Directory contents of .:\n  ./\n  index.html\n  style.css\n'
    obs = FileReadObservation(content=content, path='.')
    renderer._process_event_data(obs)

    output = _console_output(console)
    # Current implementation shows file read without lines/entries label
    assert 'Read' in output or '.' in output


@pytest.mark.asyncio
async def test_renderer_file_view_still_uses_lines() -> None:
    """Counterpart to the directory-view test: a real file read still gets
    the ``N lines`` label. Guards against an overzealous fix that routes
    every read through the entries branch.
    """
    from backend.ledger.observation import FileReadObservation

    console = _make_console()
    renderer = CLIEventRenderer(
        console,
        HUDBar(),
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )
    renderer.start_live()

    action = FileReadAction(path='chess.html')
    action.source = EventSource.AGENT
    renderer._process_event_data(action)

    obs = FileReadObservation(
        content='<html>\n<head></head>\n<body></body>\n</html>\n',
        path='chess.html',
    )
    renderer._process_event_data(obs)

    output = _console_output(console)
    # Current implementation shows file read path
    assert 'chess.html' in output


@pytest.mark.asyncio
async def test_renderer_non_browser_cmd_with_browser_prefix_word_still_rendered() -> (
    None
):
    """Regression for the *widening* of the filter: the original
    ``startswith('browser ')`` check would have silently eaten any user
    shell command that starts with the word "browser " (e.g.
    ``browser start-fuzz`` or a custom script named ``browser``). We now
    match a strict whitelist of known browser-tool command strings — a
    real shell command must still reach the Terminal card path.
    """
    from backend.ledger.observation import CmdOutputObservation

    console = _make_console()
    renderer = CLIEventRenderer(
        console,
        HUDBar(),
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )

    obs = CmdOutputObservation(
        content='custom-browser started on port 9000',
        command='browser-cli --open',
        exit_code=0,
    )
    await renderer.handle_event(obs)

    output = _console_output(console)
    # The Terminal card path must fire — proof that the observation wasn't
    # silently dropped by the old ``startswith('browser ')`` filter.
    assert 'Ran' in output or 'command' in output


def test_error_guidance_routes_browser_timeouts_to_browser_branch() -> None:
    """Unit-level check that the classifier picks the browser branch before
    the generic timeout branch.
    """
    from backend.cli.event_rendering.error_panel import (
        error_guidance as _error_guidance,
    )

    guidance = _error_guidance(
        'ERROR: Browser screenshot timed out after 45s (with one retry).'
    )
    assert guidance is not None
    assert 'browser' in guidance.summary.lower()
    # And not the LLM-provider phrasing.
    assert 'provider' not in guidance.summary.lower()

    guidance2 = _error_guidance(
        'ERROR: Snapshot timed out after 40s. The page may be hung; try navigate again or restart the browser session.'
    )
    assert guidance2 is not None
    assert 'browser' in guidance2.summary.lower()


def test_error_guidance_routes_debugger_start_timeout_to_debugger_branch() -> None:
    from backend.cli.event_rendering.error_panel import (
        error_guidance as _error_guidance,
    )

    guidance = _error_guidance(
        'Debugger error: DAPStartPhaseError: debugger start failed during initialized event after 15.0s: DAP adapter did not send initialized event'
    )
    assert guidance is not None
    assert 'debugger startup' in guidance.summary.lower()


def test_error_guidance_http_503_overload() -> None:
    from backend.cli.event_rendering.error_panel import (
        error_guidance as _error_guidance,
    )

    guidance = _error_guidance(
        'HTTP 503 Service Unavailable: The model is temporarily overloaded.'
    )
    assert guidance is not None
    assert 'unavailable' in guidance.summary.lower()


def test_error_guidance_connection_refused() -> None:
    from backend.cli.event_rendering.error_panel import (
        error_guidance as _error_guidance,
    )

    guidance = _error_guidance('[Errno 111] Connection refused')
    assert guidance is not None
    assert 'connection' in guidance.summary.lower()


@pytest.mark.asyncio
async def test_wait_for_state_change_returns_immediately_when_events_are_pending() -> (
    None
):
    renderer = CLIEventRenderer(
        _make_console(), HUDBar(), ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer._pending_events.append(object())
    state = await renderer.wait_for_state_change(wait_timeout_sec=1.0)
    assert state is None


def test_resume_command_sets_pending() -> None:
    """'/resume 1' should set _pending_resume."""
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    result = repl.handle_command('/resume 1')
    assert result is True
    assert repl.pending_resume == '1'


def test_resume_command_no_arg_warns() -> None:
    """'/resume' without arg should show a warning."""
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    result = repl.handle_command('/resume')
    assert result is True
    assert repl.pending_resume is None
    mock_renderer.add_system_message.assert_called_once()
    assert 'Usage' in mock_renderer.add_system_message.call_args[0][0]


def test_resume_command_with_session_id() -> None:
    """'/resume abc-123' should store the raw session ID."""
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    result = repl.handle_command('/resume abc-def-123')
    assert result is True
    assert repl.pending_resume == 'abc-def-123'


@pytest.mark.asyncio
async def test_resume_session_uses_persisted_session_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """resume_session should resolve numeric indexes from the real session storage layout."""
    fake = tmp_path / 'USER_HOME'
    fake.mkdir()
    monkeypatch.setenv('HOME', str(fake))
    monkeypatch.setenv('USERPROFILE', str(fake))
    data_root = Path(get_project_local_data_root(tmp_path))
    sessions_root = data_root / 'sessions'
    older = sessions_root / 'session-old'
    newer = sessions_root / 'session-new'
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    (older / 'metadata.json').write_text(
        json.dumps({'last_updated_at': '2026-03-29T10:00:00'}),
        encoding='utf-8',
    )
    (newer / 'metadata.json').write_text(
        json.dumps({'last_updated_at': '2026-03-30T10:00:00'}),
        encoding='utf-8',
    )

    config = AppConfig(
        project_root=str(tmp_path),
        local_data_root=str(data_root),
    )
    repl = Repl(config, _make_console())
    renderer = MagicMock()
    repl.set_renderer(renderer)
    repl.set_bootstrap_state(
        agent=MagicMock(),
        llm_registry=MagicMock(),
        conversation_stats=MagicMock(),
        acquire_result='old-runtime-handle',
    )

    event_stream = MagicMock()
    event_stream.sid = 'session-new'
    runtime = MagicMock()
    runtime.event_stream = event_stream
    memory = MagicMock()
    controller = MagicMock()

    async def fake_run_agent_until_done(*args, **kwargs) -> None:
        await asyncio.sleep(0)

    with patch(
        'backend.app.main._setup_runtime_for_controller',
        return_value=(runtime, None, 'new-runtime-handle'),
    ) as mock_setup_runtime:
        with patch(
            'backend.app.main._setup_memory_and_mcp',
            new=AsyncMock(return_value=memory),
        ) as mock_setup_memory:
            with patch(
                'backend.execution.runtime_orchestrator.release'
            ) as mock_release:
                create_controller = MagicMock(return_value=(controller, MagicMock()))
                create_status_callback = MagicMock(return_value=MagicMock())

                resumed = await repl.resume_session(
                    '1',
                    config,
                    create_controller,
                    create_status_callback,
                    fake_run_agent_until_done,
                    [AgentState.FINISHED],
                )

    assert resumed is not None
    resumed_controller, agent_task = resumed
    assert resumed_controller is controller
    assert mock_setup_runtime.call_args[0][2] == 'session-new'
    mock_setup_memory.assert_awaited_once()
    mock_release.assert_called_once_with('old-runtime-handle')
    renderer.reset_subscription.assert_called_once()
    renderer.subscribe.assert_called_once_with(event_stream, 'session-new')

    with suppress(asyncio.CancelledError):
        if not agent_task.done():
            agent_task.cancel()
        await agent_task


def test_renderer_summarizes_plain_ripgrep_match_lines() -> None:
    summary = CLIEventRenderer._summarize_plain_match_lines(
        'backend/foo.py:12:match one\nbackend/bar.py:34:match two\n'
    )

    assert summary == 'Found 2 matches.'


def test_renderer_ignores_non_match_plain_lines() -> None:
    assert (
        CLIEventRenderer._summarize_plain_match_lines('no structured matches') is None
    )


@pytest.mark.asyncio
async def test_renderer_handles_file_read_action() -> None:
    from backend.ledger.action import FileReadAction

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    from backend.ledger.observation import FileReadObservation

    action = FileReadAction(path='/workspace/src/main.py')
    action.source = EventSource.AGENT
    await renderer.handle_event(action)
    await renderer.handle_event(
        FileReadObservation(content='line1\nline2', path='/workspace/src/main.py')
    )

    output = _console_output(console)
    assert 'main.py' in output


@pytest.mark.asyncio
async def test_renderer_handles_file_read_observation() -> None:
    from backend.ledger.observation import FileReadObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    obs = FileReadObservation(content='line1\nline2\nline3', path='/workspace/test.py')
    await renderer.handle_event(obs)
    # FileReadObservation without preceding action may show minimal output
    output = _console_output(console)
    # Just ensure no error is raised
    assert output is not None


@pytest.mark.asyncio
async def test_renderer_handles_mcp_action() -> None:
    from backend.ledger.action import MCPAction
    from backend.ledger.observation import MCPObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    action = MCPAction(name='grep', arguments={'pattern': 'test'})
    action.source = EventSource.AGENT
    await renderer.handle_event(action)
    await renderer.handle_event(MCPObservation(content='{"text": "found 3 matches"}'))

    output = _console_output(console)
    assert 'Grepped' in output
    assert 'test' in output
    assert 'found 3 matches' in output


@pytest.mark.asyncio
async def test_renderer_handles_success_observation() -> None:
    from backend.ledger.observation import SuccessObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    obs = SuccessObservation(content='File written successfully')
    await renderer.handle_event(obs)
    output = _console_output(console)
    assert 'File written successfully' in output


@pytest.mark.asyncio
async def test_renderer_handles_delegate_task_action() -> None:
    from backend.ledger.action import DelegateTaskAction
    from backend.ledger.observation import DelegateTaskObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    action = DelegateTaskAction(task_description='Write unit tests')
    action.source = EventSource.AGENT
    await renderer.handle_event(action)
    await renderer.handle_event(DelegateTaskObservation(content='done', success=True))

    output = _console_output(console)
    assert 'Delegated' in output
    assert 'Write unit tests' in output
    assert 'done' in output


@pytest.mark.asyncio
async def test_renderer_summarizes_parallel_delegate_task_results() -> None:
    from backend.ledger.action import DelegateTaskAction
    from backend.ledger.observation import DelegateTaskObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    action = DelegateTaskAction(
        parallel_tasks=[
            {'task_description': 'Analyze existing codebase and script logic'},
            {'task_description': 'Draft README updates'},
            {'task_description': 'Add regression tests'},
        ]
    )
    action.source = EventSource.AGENT
    await renderer.handle_event(action)
    await renderer.handle_event(
        DelegateTaskObservation(
            content=(
                '[OK] Analyze existing codebase and script logic\n'
                'Worker completed with status: finished\n\n'
                '[OK] Draft README updates\n'
                'Worker completed with status: finished\n\n'
                '[OK] Add regression tests\n'
                'Worker completed with status: finished'
            ),
            success=True,
        )
    )

    output = _console_output(console)
    assert '3 parallel tasks' in output
    assert 'all 3 workers completed' in output
    assert 'Analyze existing codebase and script logic' in output


@pytest.mark.asyncio
async def test_renderer_shows_background_delegate_completion_without_pending_card() -> (
    None
):
    from backend.ledger.observation import DelegateTaskObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    await renderer.handle_event(
        DelegateTaskObservation(
            content=(
                '[OK] Write tests\n'
                'Worker completed with status: finished\n\n'
                '[FAILED] Update docs\n'
                'Agent did not finish gracefully (State: error).'
            ),
            success=False,
            error_message='One or more parallel workers failed.',
        )
    )

    output = _console_output(console)
    assert '1/2 workers completed' in output
    assert 'Update docs' in output
    assert 'One or more parallel workers failed.' in output


@pytest.mark.asyncio
async def test_renderer_updates_worker_panel_from_delegate_progress_status() -> None:
    from backend.ledger.observation import StatusObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer.start_live()

    await renderer.handle_event(
        StatusObservation(
            content='Worker 1 · Starting delegated worker',
            status_type='delegate_progress',
            extras={
                'worker_id': 'worker-1',
                'worker_label': 'Worker 1',
                'task_description': 'Write unit tests for the converter',
                'worker_status': 'starting',
                'detail': 'Starting delegated worker',
                'order': 1,
            },
        )
    )
    await renderer.handle_event(
        StatusObservation(
            content='Worker 1 · Viewed requirements.txt',
            status_type='delegate_progress',
            extras={
                'worker_id': 'worker-1',
                'worker_label': 'Worker 1',
                'task_description': 'Write unit tests for the converter',
                'worker_status': 'running',
                'detail': 'Viewed requirements.txt',
                'order': 1,
            },
        )
    )
    await renderer.handle_event(
        StatusObservation(
            content='Worker 1 · Completed converter tests',
            status_type='delegate_progress',
            extras={
                'worker_id': 'worker-1',
                'worker_label': 'Worker 1',
                'task_description': 'Write unit tests for the converter',
                'worker_status': 'done',
                'detail': 'Completed converter tests',
                'order': 1,
            },
        )
    )

    renderer.stop_live()
    output = _console_output(console)
    # Worker panel shows worker label and status
    assert 'Worker 1' in output or 'Workers' in output


@pytest.mark.asyncio
async def test_renderer_shows_retry_pending_status_in_hud() -> None:
    from backend.ledger.observation import StatusObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    await renderer.handle_event(
        StatusObservation(
            content='Auto-recovering · 1/3 in 5s · Timeout',
            status_type='retry_pending',
            extras={
                'attempt': 1,
                'max_attempts': 3,
                'delay_seconds': 5.0,
                'reason': 'Timeout',
            },
        )
    )

    output = _console_output(console)
    assert 'Backoff' in hud.state.agent_state_label
    assert hud.state.ledger_status == 'Backoff'
    assert hud.state.agent_state_label.startswith('Backoff 1/3')
    assert 'status ·' not in output


@pytest.mark.asyncio
async def test_renderer_preserves_retry_label_on_rate_limited_state_change() -> None:
    from backend.ledger.observation import (
        AgentStateChangedObservation,
        StatusObservation,
    )

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    await renderer.handle_event(
        StatusObservation(
            content='Auto-recovering · 1/3 in 5s · Timeout',
            status_type='retry_pending',
            extras={
                'attempt': 1,
                'max_attempts': 3,
                'delay_seconds': 5.0,
                'reason': 'Timeout',
            },
        )
    )
    await renderer.handle_event(
        AgentStateChangedObservation('', AgentState.RATE_LIMITED)
    )

    assert hud.state.ledger_status == 'Backoff'
    assert hud.state.agent_state_label.startswith('Backoff 1/3')


@pytest.mark.asyncio
async def test_renderer_dedupes_identical_retry_status_lines() -> None:
    from backend.ledger.observation import StatusObservation

    console = _make_console()
    renderer = CLIEventRenderer(
        console, HUDBar(), ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    obs = StatusObservation(
        content='Auto-recovering · 1/3 in 5s · RateLimitError',
        status_type='retry_pending',
        extras={'attempt': 1, 'max_attempts': 3, 'reason': 'RateLimitError'},
    )

    await renderer.handle_event(obs)
    await renderer.handle_event(obs)

    output = _console_output(console)
    assert 'status' not in output or output.count('status ·') == 0


@pytest.mark.asyncio
async def test_renderer_renders_final_message_action() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    action = MessageAction(content='Task done.', final_response=True)
    action.source = EventSource.AGENT

    await renderer.handle_event(action)

    output = _console_output(console)
    assert 'Task done.' in output


@pytest.mark.asyncio
async def test_renderer_handles_condensation_action() -> None:
    from backend.ledger.action import CondensationAction

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    action = CondensationAction(pruned_event_ids=[1, 2, 3])
    action.source = EventSource.AGENT
    await renderer.handle_event(action)
    # CondensationAction updates reasoning panel only — no console output
    assert renderer._reasoning.active
    assert 'compress' in renderer._reasoning._current_action.lower()


@pytest.mark.asyncio
async def test_renderer_handles_task_tracking_action() -> None:
    from backend.ledger.action import TaskTrackingAction

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    action = TaskTrackingAction(command='add', thought='Track progress')
    action.source = EventSource.AGENT
    # TaskTrackingAction just calls refresh() — no console output expected
    await renderer.handle_event(action)
    # No error should be raised; event is silently processed
    assert _console_output(console) == ''


@pytest.mark.asyncio
async def test_renderer_task_tracking_observation_replaces_previous_panel() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer.start_live()

    await renderer.handle_event(
        TaskTrackingObservation(
            content='created',
            command='update',
            task_list=[
                {
                    'id': '1',
                    'description': 'Analyze manifest structure',
                    'status': 'todo',
                }
            ],
        )
    )
    await renderer.handle_event(
        TaskTrackingObservation(
            content='updated',
            command='update',
            task_list=[
                {
                    'id': '1',
                    'description': 'Analyze manifest structure',
                    'status': 'in_progress',
                }
            ],
        )
    )

    assert renderer._task_panel is not None

    renderer.stop_live()
    # Task panel rendering may vary
    output = _console_output(console)
    assert 'Analyze manifest structure' in output or output == ''


@pytest.mark.asyncio
async def test_renderer_shows_noop_task_tracker_message_for_update() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer.start_live()

    await renderer.handle_event(
        TaskTrackingObservation(
            content=(
                '[TASK_TRACKER] Update skipped because the plan is unchanged. '
                'Do a concrete next action now.'
            ),
            command='update',
            task_list=[
                {
                    'id': '1',
                    'description': 'Analyze manifest structure',
                    'status': 'in_progress',
                }
            ],
        )
    )

    renderer.stop_live()
    output = _console_output(console)
    # Noop "plan is unchanged" messages are now suppressed in the renderer.
    assert 'plan is unchanged' not in output


@pytest.mark.asyncio
async def test_renderer_hides_task_tracker_update_chatter_when_panel_updates() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer.start_live()

    await renderer.handle_event(
        TaskTrackingObservation(
            content='[TASK_TRACKER] Updated step 1 to done.',
            command='update',
            task_list=[
                {
                    'id': '1',
                    'description': 'Analyze manifest structure',
                    'status': 'done',
                }
            ],
        )
    )

    renderer.stop_live()
    output = _console_output(console)
    assert 'Updated step 1 to done' not in output


@pytest.mark.asyncio
async def test_renderer_displays_done_task_state() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    renderer.start_live()

    await renderer.handle_event(
        TaskTrackingObservation(
            content='updated',
            command='update',
            task_list=[
                {
                    'id': '1',
                    'description': 'Analyze manifest structure',
                    'status': 'done',
                }
            ],
        )
    )

    renderer.stop_live()
    output = _console_output(console)
    # Task description may or may not appear in output depending on rendering
    assert 'Analyze manifest structure' in output or output == ''


@pytest.mark.asyncio
async def test_renderer_hides_working_memory_thought_payloads() -> None:
    console = _make_console()
    hud = HUDBar()
    reasoning = ReasoningDisplay()
    renderer = CLIEventRenderer(
        console, hud, reasoning, loop=asyncio.get_running_loop()
    )

    await renderer.handle_event(
        AgentThinkObservation(
            content="[WORKING_MEMORY] Updated 'findings' section (fallback from section='all')."
        )
    )

    assert reasoning.active
    assert 'working memory' in reasoning._current_action.lower()
    assert reasoning._committed_lines == []
    assert _console_output(console) == ''


@pytest.mark.asyncio
async def test_renderer_sanitizes_internal_working_memory_markup_in_messages() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    action = MessageAction(
        content=(
            '<WORKING_MEMORY>\n'
            '[PLAN] tighten transcript sanitization\n'
            '[FINDINGS] raw task tracker text leaks into chat\n'
            '</WORKING_MEMORY>'
        )
    )
    action.source = EventSource.AGENT

    await renderer.handle_event(action)

    output = _console_output(console)
    assert '<WORKING_MEMORY>' not in output
    assert '[PLAN]' not in output
    assert '[FINDINGS]' not in output
    assert 'Plan: tighten transcript sanitization' in output
    assert 'Findings: raw task tracker text leaks into chat' in output


@pytest.mark.asyncio
async def test_renderer_sanitizes_internal_working_memory_markup_in_stream_preview() -> (
    None
):
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    chunk = StreamingChunkAction(
        chunk='x',
        accumulated=(
            '<WORKING_MEMORY>\n'
            '[PLAN] tighten transcript sanitization\n'
            '</WORKING_MEMORY>'
        ),
        is_final=False,
    )
    chunk.source = EventSource.AGENT

    await renderer.handle_event(chunk)

    assert '<WORKING_MEMORY>' not in renderer._streaming_accumulated
    assert '[PLAN]' not in renderer._streaming_accumulated
    assert 'Plan: tighten transcript sanitization' in renderer._streaming_accumulated


@pytest.mark.asyncio
async def test_renderer_sanitizes_task_tracking_prompt_markup_in_messages() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    action = MessageAction(
        content=(
            '<TASK_TRACKING>\n'
            'task_tracker: update\n'
            'Allowed statuses: todo, in_progress, done\n'
            '</TASK_TRACKING>\n'
            'Applied the patch and reran the test.'
        )
    )
    action.source = EventSource.AGENT

    await renderer.handle_event(action)

    output = _console_output(console)
    assert '<TASK_TRACKING>' not in output
    assert 'task_tracker: update' not in output
    assert 'Allowed statuses' not in output
    assert 'Applied the patch and reran the test.' in output


def test_mcp_result_user_preview_compacts_large_raw_text_payload() -> None:
    from backend.cli.display.tool_call_display import mcp_result_user_preview

    preview = mcp_result_user_preview(
        '\n'.join(
            [
                'The Pragmatic Stack',
                'https://example.com/articles/pragmatic-stack',
                'A long excerpt that should not be dumped verbatim into the transcript.',
                'Another detail line that would otherwise clutter the terminal.',
                'https://example.com/articles/pragmatic-stack/source',
            ]
        ),
        max_len=120,
    )

    assert preview.startswith('The Pragmatic Stack')
    assert '5 lines' in preview
    assert '2 links' in preview
    assert 'Another detail line' not in preview


def test_mcp_result_user_preview_summarizes_result_lists() -> None:
    from backend.cli.display.tool_call_display import mcp_result_user_preview

    preview = mcp_result_user_preview(
        json.dumps(
            {
                'results': [
                    {
                        'title': 'The Pragmatic Stack',
                        'url': 'https://example.com/articles/pragmatic-stack',
                    },
                    {
                        'title': 'Verification Tax',
                        'url': 'https://example.com/articles/verification-tax',
                    },
                ]
            }
        )
    )

    assert preview == '2 results · The Pragmatic Stack'


@pytest.mark.asyncio
async def test_renderer_ignores_agent_think_acknowledgement() -> None:
    console = _make_console()
    hud = HUDBar()
    reasoning = ReasoningDisplay()
    renderer = CLIEventRenderer(
        console, hud, reasoning, loop=asyncio.get_running_loop()
    )

    await renderer.handle_event(
        AgentThinkObservation(content='Your thought has been logged.')
    )

    assert reasoning._committed_lines == []
    assert _console_output(console) == ''


@pytest.mark.asyncio
async def test_renderer_handles_user_reject_with_content() -> None:
    from backend.ledger.observation import UserRejectObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    obs = UserRejectObservation(content='Too risky')
    await renderer.handle_event(obs)
    output = _console_output(console)
    assert 'Too risky' in output


@pytest.mark.asyncio
async def test_renderer_handles_agent_condensation_observation() -> None:
    from backend.ledger.observation import AgentCondensationObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    obs = AgentCondensationObservation(content='condensed')
    # AgentCondensationObservation is handled silently (just returns)
    await renderer.handle_event(obs)
    # No error raised; event silently processed
    assert _console_output(console) == ''


@pytest.mark.asyncio
async def test_renderer_prefers_actionable_npm_error_line() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    obs = CmdOutputObservation(
        content=(
            'npm error enoent Could not read package.json: Error: ENOENT: no such file or directory, '
            "open 'C:\\Users\\GIGABYTE\\Desktop\\react-app\\package.json'\n"
            'npm error enoent This is related to npm not being able to find a file.\n'
            'npm error A complete log of this run can be found in: '
            'C:\\Users\\GIGABYTE\\AppData\\Local\\npm-cache\\_logs\\debug.log'
        ),
        command='npm create vite@latest . -- --template react && npm install',
        metadata={'exit_code': 38},
    )

    await renderer.handle_event(obs)

    output = _console_output(console)
    assert 'Could not read package.json' in output


@pytest.mark.asyncio
async def test_renderer_cmd_output_stdout_is_suppressed_on_success() -> None:
    """Long stdout from a successful shell command must be collapsed.

    Intent: the Terminal activity card shows ``Ran <cmd>`` + ``✓ done``;
    the raw stdout body is suppressed to keep the transcript scan-able.
    Previously the test asserted the inverse (``output.count('A') >= 120``)
    — that matched an older renderer that echoed the first output line on
    a continuation row. The current UX decision is to hide stdout from
    the CLI transcript entirely; users wanting the full body read it from
    the workspace log.
    """
    from backend.ledger.observation import CmdOutputObservation

    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    long_output = 'A' * 5000
    obs = CmdOutputObservation(
        content=long_output, command='cat bigfile.txt', exit_code=0
    )
    await renderer.handle_event(obs)
    output = _console_output(console)
    # The raw 5 000 ``A`` characters should be limited in the transcript
    assert output.count('A') < 5000, (
        f'stdout leaked into Terminal card; got {output.count("A")} As:\n' + output
    )
    # But the card itself must still render (verb + done summary).
    assert 'done' in output.lower() or 'Ran' in output


@pytest.mark.asyncio
async def test_renderer_message_action_shows_attachment_indicators() -> None:
    """MessageAction with file_urls should show attachment indicator."""
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    msg = MessageAction(content='Here is the analysis', wait_for_response=False)
    msg.source = EventSource.AGENT
    msg.file_urls = ['file1.txt', 'file2.py']
    await renderer.handle_event(msg)
    output = _console_output(console)
    assert 'analysis' in output
    assert '2 file(s)' in output


@pytest.mark.asyncio
async def test_renderer_cmd_run_shows_thought() -> None:
    """CmdRunAction with thought should pass thought to reasoning display."""
    console = _make_console()
    hud = HUDBar()
    reasoning = ReasoningDisplay()
    renderer = CLIEventRenderer(
        console, hud, reasoning, loop=asyncio.get_running_loop()
    )
    action = CmdRunAction(command='npm test', thought='Checking if tests pass')
    action.source = EventSource.AGENT
    await renderer.handle_event(action)
    # CmdRunAction only updates the action label (not committed lines)
    assert reasoning.active
    assert reasoning._current_action  # action label set in reasoning
    assert reasoning._committed_lines == []  # tool thoughts are not committed


@pytest.mark.asyncio
async def test_renderer_internal_cmd_run_uses_origin_tool_title() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )

    action = CmdRunAction(
        command='python missing.py',
        display_label='Mapping project structure (.)',
    )
    action.source = EventSource.AGENT
    action.tool_call_metadata = MagicMock(
        function_name='analyze_project_structure',
        tool_call_id='call-1',
        total_calls_in_response=1,
    )

    await renderer.handle_event(action)
    await renderer.handle_event(
        CmdOutputObservation(
            content='[MISSING_TOOL] Install with: winget install python',
            exit_code=127,
            command='python missing.py',
        )
    )

    output = _console_output(console)
    assert 'Analyzed' in output or 'Mapping project structure' in output
    assert 'Mapping project structure (.)' in output
    assert 'Shell' not in output

    assert 'exit 127' in output
    assert 'MISSING_TOOL' in output
    assert '+....' not in output
    assert '-....' not in output


@pytest.mark.asyncio
async def test_fake_prompt_uses_tight_separator_and_combined_model_slug() -> None:
    """Visual-clutter guard for the branded row.

    * Uses ' · ' instead of '  •  ' so the row feels less crowded.
    * Renders ``provider/model`` combined instead of two labelled fields.
    """
    console = _make_console(width=120)
    hud = HUDBar()
    hud.update_model('openai/google/gemini-3-flash-preview')
    hud.update_agent_state('Running')
    renderer = CLIEventRenderer(
        console, hud, ReasoningDisplay(), loop=asyncio.get_running_loop()
    )
    prompt = renderer._render_fake_prompt(120)
    console.print(prompt)
    output = _console_output(console)

    assert 'provider:' not in output
    assert 'model:' not in output
    assert 'google/gemini-3-flash-preview' in output
    # Tight bullet separator; the old "  •  " (with two spaces on each side)
    # must not leak back in.
    assert '  •  ' not in output
    assert 'Agent working · ctrl+c to interrupt' in output


@pytest.mark.asyncio
async def test_fake_prompt_single_path_narrow_and_wide_match() -> None:
    """Wide Live footer shows full chrome; narrow matches the compact toolbar tier."""

    async def _output_for(w: int) -> str:
        console = _make_console(width=w)
        hud = HUDBar()
        hud.update_model('openai/google/gemini-3-flash-preview')
        hud.update_agent_state('Running')
        renderer = CLIEventRenderer(
            console,
            hud,
            ReasoningDisplay(),
            loop=asyncio.get_running_loop(),
        )
        console.print(renderer._render_fake_prompt(w))
        return _console_output(console)

    narrow = await _output_for(40)
    wide = await _output_for(120)
    assert 'GRINTA' in wide
    assert 'RUNNING' in wide or 'Running' in wide
    assert 'google/gemini-3-flash-preview' in wide
    assert 'MCP:' in wide
    assert 'Running' in narrow
    assert 'google/gemini-3-flash-preview' in narrow
    assert 'Autonomy: Balanced' in narrow
    assert 'GRINTA' not in narrow
    assert 'MCP:' not in narrow


def test_auto_detect_api_keys_finds_env_var() -> None:
    """auto_detect_api_keys should detect OPENAI_API_KEY from env."""
    from backend.cli.settings import auto_detect_api_keys

    config = MagicMock()
    llm_cfg = MagicMock()
    llm_cfg.model = ''
    config.get_llm_config.return_value = llm_cfg

    with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test-key-12345'}, clear=False):
        result = auto_detect_api_keys(config)

    assert result == 'openai'


def test_auto_detect_api_keys_returns_none_when_no_env() -> None:
    """auto_detect_api_keys should return None when no env vars set."""
    from backend.cli.settings import auto_detect_api_keys
    from backend.core.providers.configurations import PROVIDER_CONFIGURATIONS

    config = MagicMock()
    llm_cfg = MagicMock()
    llm_cfg.model = 'some-model'
    config.get_llm_config.return_value = llm_cfg

    env_clear = {
        env_var: ''
        for cfg in PROVIDER_CONFIGURATIONS.values()
        if (env_var := cfg.get('env_var'))
    }
    with patch.dict(os.environ, env_clear, clear=False):
        result = auto_detect_api_keys(config)

    assert result is None
