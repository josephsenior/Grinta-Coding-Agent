from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from contextlib import suppress
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from rich.console import Console

from backend.cli.confirmation import _risk_label
from backend.cli.diff_renderer import DiffPanel
from backend.cli.event_renderer import CLIEventRenderer
from backend.cli.hud import HUDBar
from backend.cli.main import (
    _configure_redirected_streams,
    _read_piped_stdin,
    show_grinta_splash,
)
from backend.cli.reasoning_display import ReasoningDisplay
from backend.cli.repl import Repl, _prompt_toolkit_available, _supports_prompt_session
from backend.core.config import AppConfig
from backend.core.enums import ActionSecurityRisk, AgentState, EventSource
from backend.inference.metrics import Metrics, TokenUsage
from backend.ledger.action import CmdRunAction, MessageAction, StreamingChunkAction


def _make_console(*, width: int = 120) -> Console:
    return Console(file=io.StringIO(), force_terminal=False, width=width)


def _make_config() -> AppConfig:
    return cast(AppConfig, MagicMock())


def _console_output(console: Console) -> str:
    file_obj = console.file
    assert isinstance(file_obj, io.StringIO)
    return file_obj.getvalue()


@pytest.mark.asyncio
async def test_event_renderer_updates_metrics_and_streaming_preview() -> None:
    console = _make_console()
    hud = HUDBar()
    renderer = CLIEventRenderer(
        console,
        hud,
        ReasoningDisplay(),
        loop=asyncio.get_running_loop(),
    )

    metrics = Metrics()
    metrics.accumulated_cost = 1.25
    metrics.token_usages = [
        TokenUsage(prompt_tokens=10, completion_tokens=5, context_window=1000)
    ]

    chunk = StreamingChunkAction(chunk='Hello', accumulated='Hello', is_final=False)
    chunk.source = EventSource.AGENT
    chunk.llm_metrics = metrics

    await renderer.handle_event(chunk)

    assert renderer.streaming_preview == 'Hello'
    assert hud.state.cost_usd == 1.25
    assert hud.state.context_tokens == 15
    assert hud.state.context_limit == 1000

    final_message = MessageAction(content='Hello', wait_for_response=True)
    final_message.source = EventSource.AGENT
    await renderer.handle_event(final_message)

    assert renderer.streaming_preview == ''
    assert len(renderer.history) == 1


def test_confirmation_uses_backend_security_risk() -> None:
    action = CmdRunAction(command='echo hello')
    action.security_risk = ActionSecurityRisk.HIGH

    assert _risk_label(action) == ('HIGH', 'bold red')


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


def test_hud_tracks_llm_call_count() -> None:
    """HUD should count the number of LLM calls from token_usages list."""
    hud = HUDBar()
    metrics = Metrics()
    metrics.accumulated_cost = 0.5
    metrics.token_usages = [
        TokenUsage(prompt_tokens=100, completion_tokens=50),
        TokenUsage(prompt_tokens=200, completion_tokens=80),
        TokenUsage(prompt_tokens=150, completion_tokens=60),
    ]
    hud.update_from_llm_metrics(metrics)
    assert hud.state.llm_calls == 3
    assert hud.state.cost_usd == 0.5


def test_diff_panel_new_file() -> None:
    """DiffPanel should show creation info for new files."""
    obs = MagicMock()
    obs.path = 'src/main.py'
    obs.prev_exist = False
    obs.new_content = "print('hello')\nprint('world')\n"
    obs.content = 'File created'

    panel = DiffPanel(obs)
    console = _make_console(width=80)
    console.print(panel)
    output = _console_output(console)
    assert 'created' in output
    assert 'src/main.py' in output


def test_diff_panel_existing_file_with_groups() -> None:
    """DiffPanel should render edit groups for existing file edits."""
    obs = MagicMock()
    obs.path = 'README.md'
    obs.prev_exist = True
    obs.get_edit_groups.return_value = [
        {
            'before_edits': ['- old line 1'],
            'after_edits': ['+ new line 1', '+ new line 2'],
        }
    ]

    panel = DiffPanel(obs)
    console = _make_console(width=80)
    console.print(panel)
    output = _console_output(console)
    assert 'edited' in output
    assert 'README.md' in output


def test_show_grinta_splash_renders_logo_text() -> None:
    console = _make_console(width=120)
    show_grinta_splash(console)
    output = _console_output(console)

    assert 'GRINTA' in output
    assert '>_' in output
    assert 'AI coding agent' in output


def test_prompt_session_requires_tty_streams() -> None:
    interactive_stream = MagicMock()
    interactive_stream.isatty.return_value = True
    piped_stream = MagicMock()
    piped_stream.isatty.return_value = False

    with patch('backend.cli.repl._prompt_toolkit_available', return_value=True):
        assert _supports_prompt_session(interactive_stream, interactive_stream) is True
    assert _supports_prompt_session(piped_stream, interactive_stream) is False
    assert _supports_prompt_session(interactive_stream, piped_stream) is False


def test_prompt_session_requires_prompt_toolkit() -> None:
    interactive_stream = MagicMock()
    interactive_stream.isatty.return_value = True

    with patch('backend.cli.repl._prompt_toolkit_available', return_value=False):
        assert _supports_prompt_session(interactive_stream, interactive_stream) is False


def test_prompt_toolkit_available_returns_false_when_missing() -> None:
    original = sys.modules.get('prompt_toolkit')
    sys.modules.pop('prompt_toolkit', None)
    try:
        with patch.dict('sys.modules', {'prompt_toolkit': None}):
            assert _prompt_toolkit_available() is False
    finally:
        if original is not None:
            sys.modules['prompt_toolkit'] = original
        else:
            sys.modules.pop('prompt_toolkit', None)


def test_configure_redirected_streams_uses_utf8_for_non_tty() -> None:
    redirected = MagicMock()
    redirected.isatty.return_value = False
    redirected.reconfigure = MagicMock()

    interactive = MagicMock()
    interactive.isatty.return_value = True
    interactive.reconfigure = MagicMock()

    _configure_redirected_streams(redirected, interactive, None)

    redirected.reconfigure.assert_called_once_with(encoding='utf-8', errors='replace')
    interactive.reconfigure.assert_not_called()


def test_read_piped_stdin_returns_none_for_tty() -> None:
    stdin = MagicMock()
    stdin.isatty.return_value = True

    with patch.object(sys, 'stdin', stdin):
        assert _read_piped_stdin() is None


def test_read_piped_stdin_reads_non_tty_once() -> None:
    stdin = MagicMock()
    stdin.isatty.return_value = False
    stdin.read.return_value = 'queued task\n'

    with patch.object(sys, 'stdin', stdin):
        assert _read_piped_stdin() == 'queued task\n'


def test_confirmation_handles_all_risk_levels() -> None:
    """All ActionSecurityRisk levels should map to readable labels."""
    for risk_val, expected_label in [
        (ActionSecurityRisk.HIGH, 'HIGH'),
        (ActionSecurityRisk.MEDIUM, 'MEDIUM'),
        (ActionSecurityRisk.LOW, 'LOW'),
        (ActionSecurityRisk.UNKNOWN, 'ASK'),
    ]:
        action = CmdRunAction(command='test')
        action.security_risk = risk_val
        label, _ = _risk_label(action)
        assert label == expected_label


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
    assert len(renderer.history) == 1


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

    assert len(renderer.history) == 1


def test_autonomy_command_shows_current_level() -> None:
    """_handle_autonomy_command with no arg shows current level."""
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    repl.handle_autonomy_command('/autonomy')
    mock_renderer.add_system_message.assert_called_once()
    call_text = mock_renderer.add_system_message.call_args[0][0]
    assert 'balanced' in call_text


def test_autonomy_command_sets_level() -> None:
    """_handle_autonomy_command with a valid level should update the controller."""
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    mock_renderer = MagicMock()
    repl.set_renderer(mock_renderer)

    ac = MagicMock()
    ac.autonomy_level = 'balanced'
    controller = MagicMock()
    controller.autonomy_controller = ac
    repl.set_controller(controller)

    repl.handle_autonomy_command('/autonomy full')
    assert ac.autonomy_level == 'full'
    mock_renderer.add_system_message.assert_called_once()


def test_entry_point_dispatches_serve() -> None:
    """Entry point should dispatch 'serve' to embedded main."""
    import sys

    with patch.object(sys, 'argv', ['app', 'serve', '--port', '3030']):
        with patch('backend.embedded.main') as mock_serve:
            from backend.cli.entry import main

            main()
            mock_serve.assert_called_once()
            # argv should have been modified to strip 'serve'
            assert sys.argv == ['app', '--port', '3030']


# ── New tests: CLI flags ─────────────────────────────────────────────────


def test_entry_point_parses_model_flag() -> None:
    """--model flag should be forwarded to repl main."""
    import sys

    with patch.object(sys, 'argv', ['app', '--model', 'openai/gpt-4.1']):
        with patch('backend.cli.main.main') as mock_repl:
            from backend.cli.entry import main

            main()
            mock_repl.assert_called_once_with(model='openai/gpt-4.1', project=None)


def test_entry_point_parses_project_flag() -> None:
    """--project flag should be forwarded to repl main."""
    import sys

    with patch.object(sys, 'argv', ['app', '--project', '/tmp/myrepo']):
        with patch('backend.cli.main.main') as mock_repl:
            from backend.cli.entry import main

            main()
            mock_repl.assert_called_once_with(model=None, project='/tmp/myrepo')


def test_entry_point_parses_both_flags() -> None:
    """Both --model and --project should be forwarded."""
    import sys

    with patch.object(
        sys,
        'argv',
        ['app', '-m', 'anthropic/claude-sonnet-4-20250514', '-p', '/tmp/proj'],
    ):
        with patch('backend.cli.main.main') as mock_repl:
            from backend.cli.entry import main

            main()
            mock_repl.assert_called_once_with(
                model='anthropic/claude-sonnet-4-20250514', project='/tmp/proj'
            )


def test_grinta_main_parses_project_flag() -> None:
    """Grinta should parse --project even when invoked via backend.cli.main."""
    import sys

    with patch.object(sys, 'argv', ['grinta', '--project', '/tmp/myrepo']):
        with patch(
            'backend.cli.main._async_main', new_callable=MagicMock
        ) as mock_async_main:
            with patch('backend.cli.main.asyncio.run') as mock_asyncio_run:
                from backend.cli.main import main

                main()

    mock_async_main.assert_called_once_with(model=None, project='/tmp/myrepo')
    mock_asyncio_run.assert_called_once()


def test_grinta_main_dispatches_serve() -> None:
    """Grinta should dispatch serve-style subcommands from backend.cli.main."""
    import sys

    with patch.object(sys, 'argv', ['grinta', 'serve', '--port', '3030']):
        with patch('backend.embedded.main') as mock_serve:
            with patch('backend.cli.main.asyncio.run') as mock_asyncio_run:
                from backend.cli.main import main

                main()

    mock_serve.assert_called_once()
    mock_asyncio_run.assert_not_called()


@pytest.mark.asyncio
async def test_async_main_defaults_workspace_to_cwd(tmp_path: Path) -> None:
    config = AppConfig()
    config.get_llm_config().model = 'openai/gpt-4.1'

    repl = MagicMock()
    repl.run = AsyncMock()

    with patch('backend.core.config.load_app_config', return_value=config):
        with patch('backend.cli.main.Console', return_value=_make_console()):
            with patch('backend.cli.repl.Repl', return_value=repl):
                with patch('backend.cli.config_manager.needs_onboarding', return_value=False):
                    with patch('backend.cli.config_manager.ensure_default_model', return_value='openai/gpt-4.1'):
                        with patch('backend.cli.main._setup_logging'):
                            with patch('pathlib.Path.cwd', return_value=tmp_path):
                                from backend.cli.main import _async_main

                                await _async_main()

    resolved = str(tmp_path.resolve())
    assert config.project_root == resolved
    # local_data_root is intentionally NOT set to project_root in CLI mode;
    # it stays at the global default so Grinta never pollutes the user's workspace.
    assert config.local_data_root == '~/.grinta/storage'
    assert config.get_agent_config(config.default_agent).cli_mode is True
    repl.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_main_queues_piped_input(tmp_path: Path) -> None:
    config = AppConfig()
    config.get_llm_config().model = 'openai/gpt-4.1'

    repl = MagicMock()
    repl.run = AsyncMock()

    stdin = MagicMock()
    stdin.isatty.return_value = False
    stdin.read.return_value = 'queued task\n'

    with patch.object(sys, 'stdin', stdin):
        with patch('backend.core.config.load_app_config', return_value=config):
            with patch('backend.cli.main.Console', return_value=_make_console()):
                with patch('backend.cli.repl.Repl', return_value=repl):
                    with patch(
                        'backend.cli.config_manager.needs_onboarding',
                        return_value=False,
                    ):
                        with patch(
                            'backend.cli.config_manager.ensure_default_model',
                            return_value='openai/gpt-4.1',
                        ):
                            with patch('backend.cli.main._setup_logging'):
                                with patch('pathlib.Path.cwd', return_value=tmp_path):
                                    from backend.cli.main import _async_main

                                    await _async_main()

    repl.queue_initial_input.assert_called_once_with('queued task\n')
    repl.run.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_main_keeps_explicit_project_override(tmp_path: Path) -> None:
    config = AppConfig()
    config.get_llm_config().model = 'openai/gpt-4.1'
    repl = MagicMock()
    repl.run = AsyncMock()

    with patch('backend.core.config.load_app_config', return_value=config):
        with patch('backend.cli.main.Console', return_value=_make_console()):
            with patch('backend.cli.repl.Repl', return_value=repl):
                with patch('backend.cli.config_manager.needs_onboarding', return_value=False):
                    with patch('backend.cli.config_manager.ensure_default_model', return_value='openai/gpt-4.1'):
                        with patch('backend.cli.main._setup_logging'):
                            from backend.cli.main import _async_main

                            await _async_main(project=str(tmp_path))

    resolved = str(tmp_path.resolve())
    assert config.project_root == resolved
    # local_data_root is intentionally NOT set to project_root in CLI mode.
    assert config.local_data_root == '~/.grinta/storage'
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


def test_find_sessions_root_prefers_workspace_conversations(tmp_path: Path) -> None:
    from backend.cli.session_manager import _find_sessions_root

    conversations = tmp_path / '.grinta' / 'conversations'
    conversations.mkdir(parents=True)

    with patch.dict(os.environ, {'APP_ROOT': str(tmp_path)}, clear=False):
        assert _find_sessions_root() == conversations


def test_find_sessions_root_prefers_hidden_storage_sessions(tmp_path: Path) -> None:
    from backend.cli.session_manager import _find_sessions_root

    sessions = tmp_path / '.grinta' / 'storage' / 'sessions'
    sessions.mkdir(parents=True)

    with patch.dict(os.environ, {'APP_ROOT': str(tmp_path)}, clear=False):
        assert _find_sessions_root() == sessions


# ── New tests: Ctrl+C handling ───────────────────────────────────────────


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
async def test_repl_run_saves_controller_state_on_exit() -> None:
    repl = Repl(_make_config(), Console(file=io.StringIO(), force_terminal=False))
    controller = MagicMock()
    repl.set_controller(controller)

    with (
        patch(
            'backend.core.bootstrap.main._initialize_session_components',
            side_effect=RuntimeError('bootstrap failed'),
        ),
        patch('backend.cli.repl.load_app_config'),
    ):
        await repl.run()

    controller.save_state.assert_called_once()


# ── New tests: Reasoning elapsed time ────────────────────────────────────


def test_reasoning_display_elapsed_time() -> None:
    """ReasoningDisplay should show elapsed time when active."""
    rd = ReasoningDisplay()
    with patch(
        'backend.cli.reasoning_display.time.monotonic', side_effect=[100.0, 105.0]
    ):
        rd.start()
        console = _make_console(width=80)
        console.print(rd.renderable())
    output = _console_output(console)
    assert '(5s)' in output


def test_reasoning_display_stop_resets_timer() -> None:
    """stop() should reset the start time."""
    rd = ReasoningDisplay()
    with patch('backend.cli.reasoning_display.time.monotonic', return_value=100.0):
        rd.start()
    assert rd.elapsed_seconds is not None
    rd.stop()
    assert rd.elapsed_seconds is None


# ── New tests: Atomic settings writes ────────────────────────────────────


def test_atomic_settings_write(tmp_path: Path) -> None:
    """_save_raw_settings should write atomically via tempfile + rename."""
    from backend.cli.config_manager import _load_raw_settings, _save_raw_settings

    settings_file = tmp_path / 'settings.json'
    with patch('backend.cli.config_manager._settings_path', return_value=settings_file):
        data = {'llm_api_key': 'sk-test123', 'llm_model': 'test/model'}
        _save_raw_settings(data)

        loaded = _load_raw_settings()
        assert loaded['llm_api_key'] == 'sk-test123'
        assert loaded['llm_model'] == 'test/model'

        # No stale .tmp files left behind
        tmp_files = list(settings_file.parent.glob('*.tmp'))
        assert len(tmp_files) == 0


def test_get_masked_api_key_returns_not_set_when_missing() -> None:
    """Masking should be safe when no key is configured anywhere."""
    from backend.cli.config_manager import get_masked_api_key

    llm_cfg = MagicMock()
    llm_cfg.api_key = None
    llm_cfg.model = 'openai/gpt-4.1'
    config = MagicMock()
    config.get_llm_config.return_value = llm_cfg

    with patch.dict(os.environ, {}, clear=True):
        assert get_masked_api_key(config) == '(not set)'


def test_get_masked_api_key_reads_env_fallback() -> None:
    """Masking should use env-backed keys when config.api_key is unset."""
    from backend.cli.config_manager import get_masked_api_key

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
    from backend.cli.config_manager import ensure_default_model

    llm_cfg = MagicMock()
    llm_cfg.api_key = None
    llm_cfg.model = None
    config = MagicMock()
    config.get_llm_config.return_value = llm_cfg

    with patch.dict(os.environ, {'LLM_API_KEY': 'AIzaSyBxxxxxxxxxxxxxxx'}, clear=True):
        selected = ensure_default_model(config)

    assert selected == 'google/gemini-2.5-flash'
    assert llm_cfg.model == 'google/gemini-2.5-flash'


def test_ensure_default_model_preserves_existing_model() -> None:
    from backend.cli.config_manager import ensure_default_model

    llm_cfg = MagicMock()
    llm_cfg.api_key = None
    llm_cfg.model = 'anthropic/claude-sonnet-4-20250514'
    config = MagicMock()
    config.get_llm_config.return_value = llm_cfg

    with patch.dict(os.environ, {'LLM_API_KEY': 'sk-test12345678901234567890'}, clear=True):
        selected = ensure_default_model(config)

    assert selected == 'anthropic/claude-sonnet-4-20250514'
    assert llm_cfg.model == 'anthropic/claude-sonnet-4-20250514'


def test_ensure_default_model_uses_provider_specific_env_var() -> None:
    from backend.cli.config_manager import ensure_default_model

    llm_cfg = MagicMock()
    llm_cfg.api_key = None
    llm_cfg.model = None
    config = MagicMock()
    config.get_llm_config.return_value = llm_cfg

    with patch.dict(os.environ, {'OPENAI_API_KEY': 'sk-test12345678901234567890'}, clear=True):
        selected = ensure_default_model(config)

    assert selected == 'openai/gpt-4.1'
    assert llm_cfg.model == 'openai/gpt-4.1'


def test_run_onboarding_uses_provider_default_model(tmp_path: Path) -> None:
    from backend.cli.config_manager import run_onboarding

    settings_file = tmp_path / 'settings.json'
    # New flow: 1) provider number (2 = Anthropic), 2) model (accept default), 3) API key
    entered = iter(['2', '', 'sk-ant-api03-test-value'])
    loaded_config = MagicMock()

    with patch('backend.cli.config_manager._settings_path', return_value=settings_file):
        with patch('backend.cli.config_manager.Prompt.ask', side_effect=lambda *args, **kwargs: next(entered)):
            with patch('backend.cli.config_manager.load_app_config', return_value=loaded_config):
                with patch('os.isatty', return_value=True):
                    result = run_onboarding()

    saved = json.loads(settings_file.read_text(encoding='utf-8'))
    assert saved['llm_api_key'] == 'sk-ant-api03-test-value'
    assert saved['llm_model'] == 'anthropic/claude-sonnet-4-20250514'
    assert saved['llm_provider'] == 'anthropic'
    assert result is loaded_config


# ── New tests: Budget warnings ───────────────────────────────────────────


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
    # A budget warning panel was appended to history.
    assert len(renderer.history) > 0


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


# ── New tests: Session resume command ────────────────────────────────────


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
async def test_resume_session_uses_persisted_session_index(tmp_path: Path) -> None:
    """resume_session should resolve numeric indexes from the real session storage layout."""
    sessions_root = tmp_path / 'storage' / '.grinta' / 'conversations'
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

    repl = Repl(_make_config(), _make_console())
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

    with patch.dict(os.environ, {'APP_ROOT': str(tmp_path)}, clear=False):
        with patch(
            'backend.core.bootstrap.main._setup_runtime_for_controller',
            return_value=(runtime, None, 'new-runtime-handle'),
        ) as mock_setup_runtime:
            with patch(
                'backend.core.bootstrap.main._setup_memory_and_mcp',
                new=AsyncMock(return_value=memory),
            ) as mock_setup_memory:
                with patch(
                    'backend.execution.runtime_orchestrator.release'
                ) as mock_release:
                    create_controller = MagicMock(
                        return_value=(controller, MagicMock())
                    )
                    create_status_callback = MagicMock(return_value=MagicMock())

                    resumed = await repl.resume_session(
                        '1',
                        MagicMock(),
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
