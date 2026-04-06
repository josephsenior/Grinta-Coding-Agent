from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.execution.action_execution_server import RuntimeExecutor
from backend.ledger.action import CmdRunAction, FileReadAction
from backend.ledger.action.terminal import TerminalInputAction, TerminalReadAction
from backend.ledger.observation import (
    CmdOutputObservation,
    ErrorObservation,
    FileReadObservation,
)
from backend.utils.regex_limits import MAX_USER_REGEX_PATTERN_CHARS


@pytest.fixture
def mock_executor():
    """Create a minimal mocked RuntimeExecutor to avoid full initialization."""
    with (
        patch('os.makedirs'),
        patch('backend.execution.action_execution_server.SessionManager'),
        patch(
            'backend.execution.action_execution_server.RuntimeExecutor._init_browser_async'
        ),
    ):
        executor = RuntimeExecutor(
            plugins_to_load=[],
            work_dir='/tmp/test',
            username='testuser',
            user_id=1000,
            enable_browser=False,
            security_config=SimpleNamespace(execution_profile='standard'),
        )
        # Session manager is mocked by patch, but we can refine it
        executor.session_manager = MagicMock()
        return executor


@pytest.mark.asyncio
async def test_cmd_run_grep_pattern(mock_executor):
    """Test that grep_pattern filters the output correctly."""
    # Setup
    mock_session = MagicMock()
    # Mock return value of execute to be an Observation
    mock_obs = CmdOutputObservation(
        content='line1\nmatch this\nline3\nalso match this\nline5',
        command_id=0,
        command='echo test',
    )

    # mock_session.execute is called via call_sync_from_async
    mock_session.execute.return_value = mock_obs

    # Configure session manager to return this session
    mock_executor.session_manager.get_session.return_value = mock_session

    # Create action with grep_pattern
    action = CmdRunAction(command='echo test', grep_pattern='match')

    # Act
    obs = await mock_executor.run(action)

    # Assert
    assert 'match this' in obs.content
    assert 'also match this' in obs.content
    assert 'line1' not in obs.content
    assert 'line3' not in obs.content
    assert 'line5' not in obs.content


@pytest.mark.asyncio
async def test_cmd_run_grep_pattern_no_match(mock_executor):
    """Test grep_pattern when no lines match."""
    mock_session = MagicMock()
    mock_obs = CmdOutputObservation(
        content='line1\nline2\nline3', command_id=0, command='echo test'
    )
    mock_session.execute.return_value = mock_obs
    mock_executor.session_manager.get_session.return_value = mock_session

    action = CmdRunAction(command='echo test', grep_pattern='nomatch')

    obs = await mock_executor.run(action)
    assert "[Grep: No lines matched pattern 'nomatch']" in obs.content


@pytest.mark.asyncio
async def test_cmd_run_preserves_path_with_workspace_segment(mock_executor):
    """Relative dirs named ``workspace`` must not be rewritten (no virtual /workspace alias)."""
    mock_session = MagicMock()
    mock_obs = CmdOutputObservation(
        content='ok\n', command_id=0, command='ls -F components/workspace/'
    )
    mock_session.execute.return_value = mock_obs
    mock_executor.session_manager.get_session.return_value = mock_session

    cmd = 'ls -F components/workspace/'
    action = CmdRunAction(command=cmd)
    await mock_executor.run(action)

    mock_session.execute.assert_called_once()
    passed = mock_session.execute.call_args[0][0]
    assert passed.command == cmd


@pytest.mark.asyncio
async def test_cmd_run_grep_pattern_invalid_regex(mock_executor):
    """Test grep_pattern with invalid regex."""
    mock_session = MagicMock()
    mock_obs = CmdOutputObservation(
        content='line1\nline2', command_id=0, command='echo test'
    )
    mock_session.execute.return_value = mock_obs
    mock_executor.session_manager.get_session.return_value = mock_session

    # Invalid regex (unbalanced parenthesis)
    action = CmdRunAction(command='echo test', grep_pattern='(')

    obs = await mock_executor.run(action)
    assert "[Grep Error: Invalid regex pattern '('" in obs.content
    assert 'line1' in obs.content  # Should return original content on error


@pytest.mark.asyncio
async def test_cmd_run_grep_pattern_oversized_regex(mock_executor):
    """Test grep_pattern with oversized regex rejected by guardrail."""
    mock_session = MagicMock()
    mock_obs = CmdOutputObservation(
        content='line1\nline2', command_id=0, command='echo test'
    )
    mock_session.execute.return_value = mock_obs
    mock_executor.session_manager.get_session.return_value = mock_session

    large_pattern = 'a' * (MAX_USER_REGEX_PATTERN_CHARS + 1)
    action = CmdRunAction(command='echo test', grep_pattern=large_pattern)

    obs = await mock_executor.run(action)
    assert '[Grep Error: Invalid regex pattern' in obs.content
    assert 'pattern exceeds maximum length' in obs.content
    assert 'line1' in obs.content


@pytest.mark.asyncio
async def test_cmd_run_background_spawns_session(mock_executor):
    """Test that is_background=True spawns a new session and returns immediately."""
    # Mock the create_session method to return a mock session
    mock_session = MagicMock()
    mock_session.read_output.return_value = 'Background process started'
    mock_executor.session_manager.create_session.return_value = mock_session
    mock_executor.session_manager.get_session.return_value = MagicMock(
        cwd='/tmp'
    )  # Mock default session for cwd fallback

    action = CmdRunAction(command='long_running_task', is_background=True)

    with patch('time.sleep'):  # avoid actual sleep
        obs = await mock_executor.run(action)

    # Assert
    assert 'Background task started' in obs.content
    assert 'bg-' in obs.content

    # Verify session creation call
    mock_executor.session_manager.create_session.assert_called_once()

    # Verify input was written
    mock_session.write_input.assert_called_with('long_running_task\n')


@pytest.mark.asyncio
async def test_windows_with_bash_does_not_rewrite_python3(mock_executor):
    """When Git Bash is available on Windows, keep python3 command unchanged."""
    mock_session = MagicMock()
    mock_obs = CmdOutputObservation(
        content='ok',
        command='python3 --version',
        metadata={'exit_code': 0},
    )
    mock_session.execute.return_value = mock_obs
    mock_executor.session_manager.get_session.return_value = mock_session
    mock_executor.session_manager.tool_registry = MagicMock(
        has_bash=True,
        has_powershell=True,
    )

    action = CmdRunAction(command='python3 --version')
    with patch('sys.platform', 'win32'):
        await mock_executor.run(action)

    assert action.command == 'python3 --version'


@pytest.mark.asyncio
async def test_windows_powershell_rewrites_python3(mock_executor):
    """When bash is unavailable on Windows, rewrite python3 to python."""
    mock_session = MagicMock()
    mock_obs = CmdOutputObservation(
        content='ok',
        command='python --version',
        metadata={'exit_code': 0},
    )
    mock_session.execute.return_value = mock_obs
    mock_executor.session_manager.get_session.return_value = mock_session
    mock_executor.session_manager.tool_registry = MagicMock(
        has_bash=False,
        has_powershell=True,
    )

    action = CmdRunAction(command='python3 --version')
    with patch('sys.platform', 'win32'):
        await mock_executor.run(action)

    assert action.command == 'python --version'


@pytest.mark.asyncio
async def test_repeated_identical_failures_add_pivot_hint(mock_executor):
    """Second identical command failure should include repeated-failure guidance."""
    mock_session = MagicMock()
    mock_executor.session_manager.get_session.return_value = mock_session

    def _mk_fail_obs() -> CmdOutputObservation:
        return CmdOutputObservation(
            content='[ERROR STREAM]\n/bin/bash: line 1: python: command not found',
            command='python --version',
            metadata={'exit_code': 127},
        )

    mock_session.execute.side_effect = [_mk_fail_obs(), _mk_fail_obs()]

    action1 = CmdRunAction(command='python --version')
    action2 = CmdRunAction(command='python --version')

    first = await mock_executor.run(action1)
    second = await mock_executor.run(action2)

    assert 'REPEATED_COMMAND_FAILURE' not in first.content
    assert 'REPEATED_COMMAND_FAILURE' in second.content


@pytest.mark.asyncio
async def test_powershell_syntax_in_bash_adds_shell_mismatch_guidance(mock_executor):
    mock_session = MagicMock()
    mock_executor.session_manager.get_session.return_value = mock_session
    mock_executor.session_manager.tool_registry = MagicMock(
        has_bash=True,
        has_powershell=True,
    )
    mock_session.cwd = '/tmp'
    mock_session.execute.return_value = CmdOutputObservation(
        content='[ERROR STREAM]\n/bin/bash: line 1: Get-Content: command not found',
        command='Write-Output "=== FILE: src/repomentor/index.py ===" ; Get-Content "src/repomentor/index.py" -Encoding UTF8',
        metadata={'exit_code': 127},
    )

    action = CmdRunAction(
        command='Write-Output "=== FILE: src/repomentor/index.py ===" ; Get-Content "src/repomentor/index.py" -Encoding UTF8'
    )

    obs = await mock_executor.run(action)

    assert 'SHELL_MISMATCH' in obs.content
    assert 'Get-Content is a PowerShell command' in obs.content
    assert 'MISSING_TOOL' not in obs.content


@pytest.mark.asyncio
async def test_chained_scaffold_failure_adds_scaffold_guidance(mock_executor):
    mock_session = MagicMock()
    mock_executor.session_manager.get_session.return_value = mock_session
    mock_session.cwd = '/tmp'
    mock_session.execute.return_value = CmdOutputObservation(
        content=(
            "npm error enoent Could not read package.json: Error: ENOENT: no such file or directory, "
            "open '/tmp/react-app/package.json'\n"
            'npm error A complete log of this run can be found in: /tmp/npm-debug.log'
        ),
        command='npm create vite@latest . -- --template react && npm install',
        metadata={'exit_code': 38},
    )

    action = CmdRunAction(
        command='npm create vite@latest . -- --template react && npm install'
    )

    obs = await mock_executor.run(action)

    assert 'SCAFFOLD_SETUP_FAILED' in obs.content
    assert 'Run the generator by itself first' in obs.content
    assert 'MISSING_TOOL' not in obs.content


@pytest.mark.asyncio
async def test_hardened_local_blocks_command_when_default_session_cwd_outside_workspace(
    mock_executor, tmp_path
):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    mock_executor._initial_cwd = str(workspace)
    mock_executor.security_config = SimpleNamespace(execution_profile='hardened_local')

    mock_session = MagicMock(cwd=str(outside))
    mock_executor.session_manager.get_session.return_value = mock_session

    action = CmdRunAction(command='pwd')

    obs = await mock_executor.run(action)

    assert isinstance(obs, ErrorObservation)
    assert 'must stay inside the workspace' in obs.content
    mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_read_blocks_when_session_cwd_drifts_outside_workspace(
    mock_executor, tmp_path
):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'secret.txt').write_text('secret', encoding='utf-8')

    mock_executor._initial_cwd = str(workspace)
    mock_executor.security_config = SimpleNamespace(execution_profile='hardened_local')

    mock_session = MagicMock(cwd=str(outside))
    mock_executor.session_manager.get_session.return_value = mock_session

    obs = await mock_executor.read(FileReadAction(path='secret.txt'))

    assert isinstance(obs, ErrorObservation)
    assert 'only access paths inside the workspace' in obs.content


@pytest.mark.asyncio
async def test_read_allows_relative_file_within_workspace(mock_executor, tmp_path):
    workspace = tmp_path / 'workspace'
    nested = workspace / 'nested'
    nested.mkdir(parents=True)
    (workspace / 'allowed.txt').write_text('allowed', encoding='utf-8')

    mock_executor._initial_cwd = str(workspace)
    mock_executor.security_config = SimpleNamespace(execution_profile='hardened_local')

    mock_session = MagicMock(cwd=str(nested))
    mock_executor.session_manager.get_session.return_value = mock_session

    obs = await mock_executor.read(FileReadAction(path='../allowed.txt'))

    assert isinstance(obs, FileReadObservation)
    assert obs.content == 'allowed'


@pytest.mark.asyncio
async def test_terminal_input_blocks_session_that_escaped_workspace(
    mock_executor, tmp_path
):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()

    mock_executor._initial_cwd = str(workspace)
    mock_executor.security_config = SimpleNamespace(execution_profile='hardened_local')

    session = MagicMock(cwd=str(outside))
    mock_executor.session_manager.get_session.return_value = session

    obs = await mock_executor.terminal_input(
        TerminalInputAction(session_id='term-1', input='ls')
    )

    assert isinstance(obs, ErrorObservation)
    assert 'closed by hardened_local policy' in obs.content
    mock_executor.session_manager.close_session.assert_called_with('term-1')
    session.write_input.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_input_blocks_cd_outside_workspace(mock_executor, tmp_path):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    subdir = workspace / 'subdir'
    subdir.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()

    mock_executor._initial_cwd = str(workspace)
    mock_executor.security_config = SimpleNamespace(execution_profile='hardened_local')

    session = MagicMock(cwd=str(subdir))
    mock_executor.session_manager.get_session.return_value = session

    obs = await mock_executor.terminal_input(
        TerminalInputAction(session_id='term-2', input=f'cd {outside}')
    )

    assert isinstance(obs, ErrorObservation)
    assert 'cannot change directory outside the workspace' in obs.content
    session.write_input.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_input_allows_cd_within_workspace_and_tracks_cwd(
    mock_executor, tmp_path
):
    workspace = tmp_path / 'workspace'
    nested = workspace / 'nested'
    nested.mkdir(parents=True)
    target = workspace / 'allowed'
    target.mkdir()

    mock_executor._initial_cwd = str(workspace)
    mock_executor.security_config = SimpleNamespace(
        execution_profile='hardened_local',
        allow_background_processes=False,
        allow_package_installs=False,
        allow_network_commands=False,
        hardened_local_git_allowlist=[
            'status',
            'diff',
            'log',
            'show',
            'branch',
            'rev-parse',
            'ls-files',
        ],
        hardened_local_package_allowlist=[],
        hardened_local_network_allowlist=[],
    )

    session = MagicMock(cwd=str(nested))
    session.read_output.return_value = 'ok'
    mock_executor.session_manager.get_session.return_value = session

    with patch(
        'backend.execution.action_execution_server.asyncio.sleep', return_value=None
    ):
        obs = await mock_executor.terminal_input(
            TerminalInputAction(session_id='term-3', input=f'cd {target}')
        )

    assert obs.__class__.__name__ == 'TerminalObservation'
    session.write_input.assert_called_once_with(f'cd {target}', is_control=False)
    assert session._cwd == str(target.resolve())


@pytest.mark.asyncio
async def test_terminal_read_blocks_session_that_escaped_workspace(
    mock_executor, tmp_path
):
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()

    mock_executor._initial_cwd = str(workspace)
    mock_executor.security_config = SimpleNamespace(execution_profile='hardened_local')

    session = MagicMock(cwd=str(outside))
    mock_executor.session_manager.get_session.return_value = session

    obs = await mock_executor.terminal_read(TerminalReadAction(session_id='term-4'))

    assert isinstance(obs, ErrorObservation)
    assert 'closed by hardened_local policy' in obs.content
    mock_executor.session_manager.close_session.assert_called_with('term-4')
