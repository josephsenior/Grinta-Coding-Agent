# pyright: reportUnknownParameterType=false, reportMissingParameterType=false, reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.execution.action_execution_server import RuntimeExecutor
from backend.ledger.action import CmdRunAction, FileReadAction
from backend.ledger.action.terminal import (
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
)
from backend.ledger.observation import (
    CmdOutputObservation,
    ErrorObservation,
    FileReadObservation,
)
from backend.utils.regex_limits import MAX_USER_REGEX_PATTERN_CHARS


@pytest.fixture
def mock_executor(tmp_path: Path):
    """Create a minimal mocked RuntimeExecutor to avoid full initialization."""
    with (
        patch("os.makedirs"),
        patch("backend.execution.action_execution_server.SessionManager"),
    ):
        executor = RuntimeExecutor(
            plugins_to_load=[],
            work_dir=str(tmp_path / "test"),
            username="testuser",
            user_id=1000,
            enable_browser=False,
            security_config=SimpleNamespace(execution_profile="standard"),
        )
        # Session manager is mocked by patch, but we can refine it
        executor.session_manager = MagicMock()
        executor.plugins = {}
        return executor


@pytest.mark.asyncio
async def test_cmd_run_grep_pattern(mock_executor):
    # Setup
    mock_session = MagicMock()
    # Mock return value of execute to be an Observation
    mock_obs = CmdOutputObservation(
        content="line1\nmatch this\nline3\nalso match this\nline5",
        command_id=0,
        command="echo test",
    )

    # mock_session.execute is called via call_sync_from_async
    mock_session.execute.return_value = mock_obs

    # Configure session manager to return this session
    mock_executor.session_manager.get_session.return_value = mock_session

    # Create action with grep_pattern
    action = CmdRunAction(command="echo test", grep_pattern="match")

    # Act
    obs = await mock_executor.run(action)

    # Assert
    assert "match this" in obs.content
    assert "also match this" in obs.content
    assert "line1" not in obs.content
    assert "line3" not in obs.content
    assert "line5" not in obs.content


@pytest.mark.asyncio
async def test_cmd_run_grep_pattern_no_match(mock_executor):
    """Test grep_pattern when no lines match."""
    mock_session = MagicMock()
    mock_obs = CmdOutputObservation(
        content="line1\nline2\nline3", command_id=0, command="echo test"
    )
    mock_session.execute.return_value = mock_obs
    mock_executor.session_manager.get_session.return_value = mock_session

    action = CmdRunAction(command="echo test", grep_pattern="nomatch")

    obs = await mock_executor.run(action)
    assert "[Grep: No lines matched pattern 'nomatch']" in obs.content


@pytest.mark.asyncio
async def test_cmd_run_preserves_path_with_workspace_segment(mock_executor):
    """Relative dirs named ``workspace`` must not be rewritten (no virtual /workspace alias)."""
    mock_session = MagicMock()
    mock_obs = CmdOutputObservation(
        content="ok\n", command_id=0, command="ls -F components/workspace/"
    )
    mock_session.execute.return_value = mock_obs
    mock_executor.session_manager.get_session.return_value = mock_session

    cmd = "ls -F components/workspace/"
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
        content="line1\nline2", command_id=0, command="echo test"
    )
    mock_session.execute.return_value = mock_obs
    mock_executor.session_manager.get_session.return_value = mock_session

    # Invalid regex (unbalanced parenthesis)
    action = CmdRunAction(command="echo test", grep_pattern="(")

    obs = await mock_executor.run(action)
    assert "[Grep Error: Invalid regex pattern '('" in obs.content
    assert "line1" in obs.content  # Should return original content on error


@pytest.mark.asyncio
async def test_cmd_run_grep_pattern_oversized_regex(mock_executor):
    """Test grep_pattern with oversized regex rejected by guardrail."""
    mock_session = MagicMock()
    mock_obs = CmdOutputObservation(
        content="line1\nline2", command_id=0, command="echo test"
    )
    mock_session.execute.return_value = mock_obs
    mock_executor.session_manager.get_session.return_value = mock_session

    large_pattern = "a" * (MAX_USER_REGEX_PATTERN_CHARS + 1)
    action = CmdRunAction(command="echo test", grep_pattern=large_pattern)

    obs = await mock_executor.run(action)
    assert "[Grep Error: Invalid regex pattern" in obs.content
    assert "pattern exceeds maximum length" in obs.content
    assert "line1" in obs.content


@pytest.mark.asyncio
async def test_cmd_run_background_spawns_session(mock_executor):
    """Test that is_background=True spawns a new session and returns immediately."""
    # Mock the create_session method to return a mock session
    mock_session = MagicMock()
    mock_session.read_output.return_value = "Background process started"
    mock_executor.session_manager.create_session.return_value = mock_session
    mock_executor.session_manager.get_session.return_value = MagicMock(
        cwd="/project/space"
    )  # Mock default session for cwd fallback

    action = CmdRunAction(command="long_running_task", is_background=True)

    with patch("time.sleep"):  # avoid actual sleep
        obs = await mock_executor.run(action)

    # Assert
    assert "Background task started" in obs.content
    assert "bg-" in obs.content

    # Verify session creation call
    mock_executor.session_manager.create_session.assert_called_once()

    # Verify input was written
    mock_session.write_input.assert_called_with("long_running_task\n")


@pytest.mark.asyncio
async def test_windows_prefers_powershell_rewrites_python3_when_both_available(
    mock_executor,
):
    """When both shells exist on Windows, PowerShell-first contract rewrites python3."""
    mock_session = MagicMock()
    mock_obs = CmdOutputObservation(
        content="ok",
        command="python --version",
        metadata={"exit_code": 0},
    )
    mock_session.execute.return_value = mock_obs
    mock_executor.session_manager.get_session.return_value = mock_session
    mock_executor.session_manager.tool_registry = MagicMock(
        has_bash=True,
        has_powershell=True,
    )

    action = CmdRunAction(command="python3 --version")
    with patch("sys.platform", "win32"):
        await mock_executor.run(action)

    assert action.command == "python --version"


@pytest.mark.asyncio
async def test_windows_powershell_rewrites_python3(mock_executor):
    """When bash is unavailable on Windows, rewrite python3 to python."""
    mock_session = MagicMock()
    mock_obs = CmdOutputObservation(
        content="ok",
        command="python --version",
        metadata={"exit_code": 0},
    )
    mock_session.execute.return_value = mock_obs
    mock_executor.session_manager.get_session.return_value = mock_session
    mock_executor.session_manager.tool_registry = MagicMock(
        has_bash=False,
        has_powershell=True,
    )

    action = CmdRunAction(command="python3 --version")
    with patch("sys.platform", "win32"):
        await mock_executor.run(action)

    assert action.command == "python --version"


def test_init_shell_commands_uses_powershell_helpers_on_windows(mock_executor):
    mock_session = MagicMock()
    mock_executor.session_manager.get_session.return_value = mock_session
    mock_executor.session_manager.tool_registry = MagicMock(
        has_bash=True,
        has_powershell=True,
    )

    with patch("backend.execution.action_execution_server.sys.platform", "win32"):
        mock_executor._init_shell_commands()

    first_command = mock_session.execute.call_args_list[0][0][0].command
    second_command = mock_session.execute.call_args_list[1][0][0].command

    assert "; git config --global user.email " in first_command
    assert "&&" not in first_command
    assert "function global:env_check" in second_command
    assert "Get-PSDrive -PSProvider FileSystem" in second_command
    assert "alias env_check=" not in second_command


def test_init_shell_commands_keeps_bash_helpers_when_not_powershell(mock_executor):
    mock_session = MagicMock()
    mock_executor.session_manager.get_session.return_value = mock_session
    mock_executor.session_manager.tool_registry = MagicMock(
        has_bash=True,
        has_powershell=False,
    )

    with patch("backend.execution.action_execution_server.sys.platform", "win32"):
        mock_executor._init_shell_commands()

    first_command = mock_session.execute.call_args_list[0][0][0].command
    second_command = mock_session.execute.call_args_list[1][0][0].command

    assert "&& git config --global user.email " in first_command
    assert "alias env_check='" in second_command
    assert "python3 --version 2>/dev/null" in second_command


@pytest.mark.asyncio
async def test_powershell_syntax_in_bash_adds_shell_mismatch_guidance(mock_executor):
    mock_session = MagicMock()
    mock_executor.session_manager.get_session.return_value = mock_session
    mock_executor.session_manager.tool_registry = MagicMock(
        has_bash=True,
        has_powershell=False,
    )
    mock_session.cwd = "/project/space"
    mock_session.execute.return_value = CmdOutputObservation(
        content="[ERROR STREAM]\n/bin/bash: line 1: Get-Content: command not found",
        command='Write-Output "=== FILE: src/repomentor/index.py ===" ; Get-Content "src/repomentor/index.py" -Encoding UTF8',
        metadata={"exit_code": 127},
    )

    action = CmdRunAction(
        command='Write-Output "=== FILE: src/repomentor/index.py ===" ; Get-Content "src/repomentor/index.py" -Encoding UTF8'
    )

    obs = await mock_executor.run(action)

    assert "SHELL_MISMATCH" in obs.content
    assert "Get-Content" in obs.content
    assert "PowerShell" in obs.content
    assert "MISSING_TOOL" not in obs.content


@pytest.mark.asyncio
async def test_chained_scaffold_failure_adds_scaffold_guidance(mock_executor):
    mock_session = MagicMock()
    mock_executor.session_manager.get_session.return_value = mock_session
    mock_session.cwd = "/project/space"
    mock_session.execute.return_value = CmdOutputObservation(
        content=(
            "npm error enoent Could not read package.json: Error: ENOENT: no such file or directory, "
            "open '/project/space/react-app/package.json'\n"
            "npm error A complete log of this run can be found in: /project/space/npm-debug.log"
        ),
        command="npm create vite@latest . -- --template react && npm install",
        metadata={"exit_code": 38},
    )

    action = CmdRunAction(
        command="npm create vite@latest . -- --template react && npm install"
    )

    obs = await mock_executor.run(action)

    assert "SCAFFOLD_SETUP_FAILED" in obs.content
    assert "Run the generator by itself first" in obs.content
    assert "MISSING_TOOL" not in obs.content


# ---------------------------------------------------------------------------
# Annotation behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_tool_no_annotation(mock_executor):
    """Raw stderr is returned unchanged; no [MISSING_TOOL] tag is appended."""
    mock_session = MagicMock()
    mock_executor.session_manager.get_session.return_value = mock_session
    mock_session.cwd = "C:/tmp"
    raw_err = "[ERROR STREAM]\n/bin/bash: line 1: poetry: command not found"
    mock_session.execute.return_value = CmdOutputObservation(
        content=raw_err,
        command="poetry --version",
        metadata={"exit_code": 127},
    )

    obs = await mock_executor.run(CmdRunAction(command="poetry --version"))

    assert "MISSING_TOOL" not in obs.content
    assert "command not found" in obs.content


@pytest.mark.asyncio
async def test_repeated_failure_no_annotation(mock_executor):
    """Repeated identical failures are passed through without annotation."""
    mock_session = MagicMock()
    mock_executor.session_manager.get_session.return_value = mock_session

    def _mk_fail_obs() -> CmdOutputObservation:
        return CmdOutputObservation(
            content="[ERROR STREAM]\n/bin/bash: line 1: python: command not found",
            command="python --version",
            metadata={"exit_code": 127},
        )

    mock_session.execute.side_effect = [_mk_fail_obs(), _mk_fail_obs()]

    first = await mock_executor.run(CmdRunAction(command="python --version"))
    second = await mock_executor.run(CmdRunAction(command="python --version"))

    assert "REPEATED_COMMAND_FAILURE" not in first.content
    assert "REPEATED_COMMAND_FAILURE" not in second.content


@pytest.mark.asyncio
async def test_shell_mismatch_always_emitted(mock_executor):
    """Structural tags that the model cannot infer from raw output are always emitted."""
    mock_session = MagicMock()
    mock_executor.session_manager.get_session.return_value = mock_session
    mock_executor.session_manager.tool_registry = MagicMock(
        has_bash=True,
        has_powershell=False,
    )
    mock_session.cwd = "/project/space"
    mock_session.execute.return_value = CmdOutputObservation(
        content="[ERROR STREAM]\n/bin/bash: line 1: Get-Content: command not found",
        command='Get-Content "x.py"',
        metadata={"exit_code": 127},
    )

    obs = await mock_executor.run(CmdRunAction(command='Get-Content "x.py"'))

    assert "SHELL_MISMATCH" in obs.content


@pytest.mark.asyncio
async def test_oom_no_extra_commentary(mock_executor):
    """Exit 137 produces no `[OOM_KILLED] ...` suffix — the exit code itself communicates the kill."""
    mock_session = MagicMock()
    mock_executor.session_manager.get_session.return_value = mock_session
    mock_session.execute.return_value = CmdOutputObservation(
        content="killed",
        command="big_job",
        metadata={"exit_code": 137},
    )

    obs = await mock_executor.run(CmdRunAction(command="big_job"))

    assert "OOM_KILLED" not in obs.content
    assert "out of memory" not in obs.content


@pytest.mark.asyncio
async def test_hardened_local_blocks_command_when_default_session_cwd_outside_workspace(
    mock_executor, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    mock_executor._initial_cwd = str(workspace)
    mock_executor.security_config = SimpleNamespace(execution_profile="hardened_local")

    mock_session = MagicMock(cwd=str(outside))
    mock_executor.session_manager.get_session.return_value = mock_session

    action = CmdRunAction(command="pwd")

    obs = await mock_executor.run(action)

    assert isinstance(obs, ErrorObservation)
    assert "must stay inside the workspace" in obs.content
    mock_session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_sandboxed_local_allows_interactive_terminal_run(mock_executor, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    mock_executor._initial_cwd = str(workspace)
    mock_executor.security_config = SimpleNamespace(execution_profile="sandboxed_local")
    mock_executor.session_manager.sessions = {}
    mock_executor.session_manager.get_session.return_value = None

    session = MagicMock()
    session.read_output.return_value = ""
    mock_executor.session_manager.create_session.return_value = session

    obs = await mock_executor.terminal_run(
        TerminalRunAction(command="python -m http.server")
    )

    assert obs.__class__.__name__ == "TerminalObservation"
    mock_executor.session_manager.create_session.assert_called_once_with(
        session_id="terminal_1", cwd=str(workspace), interactive=True
    )
    session.write_input.assert_called_once_with("python -m http.server\n")


@pytest.mark.asyncio
async def test_read_blocks_when_session_cwd_drifts_outside_workspace(
    mock_executor, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret", encoding="utf-8")

    mock_executor._initial_cwd = str(workspace)
    mock_executor.security_config = SimpleNamespace(execution_profile="hardened_local")

    mock_session = MagicMock(cwd=str(outside))
    mock_executor.session_manager.get_session.return_value = mock_session

    obs = await mock_executor.read(FileReadAction(path="secret.txt"))

    assert isinstance(obs, ErrorObservation)
    assert "only access paths inside the workspace" in obs.content


@pytest.mark.asyncio
async def test_read_allows_relative_file_within_workspace(mock_executor, tmp_path):
    workspace = tmp_path / "workspace"
    nested = workspace / "nested"
    nested.mkdir(parents=True)
    (workspace / "allowed.txt").write_text("allowed", encoding="utf-8")

    mock_executor._initial_cwd = str(workspace)
    mock_executor.security_config = SimpleNamespace(execution_profile="hardened_local")

    mock_session = MagicMock(cwd=str(nested))
    mock_executor.session_manager.get_session.return_value = mock_session

    obs = await mock_executor.read(FileReadAction(path="../allowed.txt"))

    assert isinstance(obs, FileReadObservation)
    assert obs.content == "allowed"


@pytest.mark.asyncio
async def test_terminal_input_blocks_session_that_escaped_workspace(
    mock_executor, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    mock_executor._initial_cwd = str(workspace)
    mock_executor.security_config = SimpleNamespace(execution_profile="hardened_local")

    session = MagicMock(cwd=str(outside))
    mock_executor.session_manager.get_session.return_value = session

    obs = await mock_executor.terminal_input(
        TerminalInputAction(session_id="term-1", input="ls")
    )

    assert isinstance(obs, ErrorObservation)
    assert "closed by hardened_local policy" in obs.content
    mock_executor.session_manager.close_session.assert_called_with("term-1")
    session.write_input.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_input_blocks_cd_outside_workspace(mock_executor, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subdir = workspace / "subdir"
    subdir.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    mock_executor._initial_cwd = str(workspace)
    mock_executor.security_config = SimpleNamespace(execution_profile="hardened_local")

    session = MagicMock(cwd=str(subdir))
    mock_executor.session_manager.get_session.return_value = session

    obs = await mock_executor.terminal_input(
        TerminalInputAction(session_id="term-2", input=f"cd {outside}")
    )

    assert isinstance(obs, ErrorObservation)
    assert "cannot change directory outside the workspace" in obs.content
    session.write_input.assert_not_called()


@pytest.mark.asyncio
async def test_terminal_input_allows_cd_within_workspace_and_tracks_cwd(
    mock_executor, tmp_path
):
    workspace = tmp_path / "workspace"
    nested = workspace / "nested"
    nested.mkdir(parents=True)
    target = workspace / "allowed"
    target.mkdir()

    mock_executor._initial_cwd = str(workspace)
    mock_executor.security_config = SimpleNamespace(
        execution_profile="hardened_local",
        allow_background_processes=False,
        allow_package_installs=False,
        allow_network_commands=False,
        hardened_local_git_allowlist=[
            "status",
            "diff",
            "log",
            "show",
            "branch",
            "rev-parse",
            "ls-files",
        ],
        hardened_local_package_allowlist=[],
        hardened_local_network_allowlist=[],
    )

    session = MagicMock(cwd=str(nested))
    session.read_output.return_value = "ok"
    mock_executor.session_manager.get_session.return_value = session

    with patch(
        "backend.execution.action_execution_server.asyncio.sleep", return_value=None
    ):
        obs = await mock_executor.terminal_input(
            TerminalInputAction(session_id="term-3", input=f"cd {target}")
        )

    assert obs.__class__.__name__ == "TerminalObservation"
    session.write_input.assert_called_once_with(f"cd {target}\n", is_control=False)
    assert session._cwd == str(target.resolve())


@pytest.mark.asyncio
async def test_terminal_read_blocks_session_that_escaped_workspace(
    mock_executor, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    mock_executor._initial_cwd = str(workspace)
    mock_executor.security_config = SimpleNamespace(execution_profile="hardened_local")

    session = MagicMock(cwd=str(outside))
    mock_executor.session_manager.get_session.return_value = session

    obs = await mock_executor.terminal_read(TerminalReadAction(session_id="term-4"))

    assert isinstance(obs, ErrorObservation)
    assert "closed by hardened_local policy" in obs.content
    mock_executor.session_manager.close_session.assert_called_with("term-4")


@pytest.mark.asyncio
async def test_terminal_input_submit_false_does_not_append_newline(
    mock_executor, tmp_path
) -> None:
    workspace = tmp_path / "w"
    workspace.mkdir()
    mock_executor._initial_cwd = str(workspace)

    session = MagicMock()
    session.cwd = str(workspace)
    session.read_output.return_value = ""
    mock_executor.session_manager.get_session.return_value = session

    with patch(
        "backend.execution.action_execution_server.asyncio.sleep", return_value=None
    ):
        obs = await mock_executor.terminal_input(
            TerminalInputAction(session_id="t-sub", input="partial", submit=False)
        )

    assert obs.__class__.__name__ == "TerminalObservation"
    session.write_input.assert_called_once_with("partial", is_control=False)


@pytest.mark.asyncio
async def test_terminal_read_delta_empty_adds_empty_hints(
    mock_executor, tmp_path
) -> None:
    workspace = tmp_path / "w"
    workspace.mkdir()
    mock_executor._initial_cwd = str(workspace)

    session = MagicMock()
    session.cwd = str(workspace)
    session.read_output_since.return_value = ("", 42, 0)
    mock_executor.session_manager.get_session.return_value = session

    obs = await mock_executor.terminal_read(
        TerminalReadAction(session_id="t-hint", offset=10, mode="delta")
    )

    assert obs.__class__.__name__ == "TerminalObservation"
    payload = obs.tool_result["payload"]
    assert payload["delta_empty"] is True
    assert payload["empty_reason"] == "no_new_bytes_since_offset"


@pytest.mark.asyncio
async def test_terminal_input_applies_resize_and_control_field(
    mock_executor, tmp_path
) -> None:
    workspace = tmp_path / "w"
    workspace.mkdir()
    mock_executor._initial_cwd = str(workspace)

    session = MagicMock()
    session.cwd = str(workspace)
    session.read_output.return_value = "out"
    mock_executor.session_manager.get_session.return_value = session

    with patch(
        "backend.execution.action_execution_server.asyncio.sleep", return_value=None
    ):
        obs = await mock_executor.terminal_input(
            TerminalInputAction(
                session_id="t-rsz",
                input="",
                control="C-c",
                rows=30,
                cols=100,
            )
        )

    assert obs.__class__.__name__ == "TerminalObservation"
    session.resize.assert_called_once_with(30, 100)
    assert session.write_input.call_count == 1
    session.write_input.assert_any_call("C-c", is_control=True)


@pytest.mark.asyncio
async def test_terminal_read_applies_resize(mock_executor, tmp_path) -> None:
    workspace = tmp_path / "w"
    workspace.mkdir()
    mock_executor._initial_cwd = str(workspace)

    session = MagicMock()
    session.cwd = str(workspace)
    session.read_output.return_value = "buf"
    mock_executor.session_manager.get_session.return_value = session

    obs = await mock_executor.terminal_read(
        TerminalReadAction(session_id="t-read", rows=24, cols=80)
    )

    assert obs.__class__.__name__ == "TerminalObservation"
    assert obs.content == "buf"
    session.resize.assert_called_once_with(24, 80)
    session.read_output.assert_called_once()


@pytest.mark.asyncio
async def test_terminal_run_uses_simple_incremental_ids(
    mock_executor, tmp_path
) -> None:
    workspace = tmp_path / "w"
    workspace.mkdir()
    mock_executor._initial_cwd = str(workspace)
    mock_executor.session_manager.sessions = {}

    session = MagicMock()
    session.read_output.return_value = ""
    mock_executor.session_manager.create_session.return_value = session

    obs1 = await mock_executor.terminal_run(
        TerminalRunAction(command="echo 1", cwd=str(workspace))
    )
    obs2 = await mock_executor.terminal_run(
        TerminalRunAction(command="echo 2", cwd=str(workspace))
    )

    assert obs1.__class__.__name__ == "TerminalObservation"
    assert obs2.__class__.__name__ == "TerminalObservation"
    assert obs1.session_id == "terminal_1"
    assert obs2.session_id == "terminal_2"


@pytest.mark.asyncio
async def test_terminal_read_rejects_nonexistent_session_with_guidance(
    mock_executor,
) -> None:
    mock_executor.session_manager.get_session.return_value = None
    mock_executor.session_manager.sessions = {
        "default": MagicMock(),
        "terminal_1": MagicMock(),
    }

    obs = await mock_executor.terminal_read(
        TerminalReadAction(session_id="terminal_session_0")
    )

    assert isinstance(obs, ErrorObservation)
    assert "does not exist for action=read" in obs.content
    assert "Do not invent IDs like terminal_session_0" in obs.content
    assert "terminal_1" in obs.content


@pytest.mark.asyncio
async def test_terminal_open_guardrail_blocks_repetitive_open_loop(
    mock_executor, tmp_path
) -> None:
    workspace = tmp_path / "w"
    workspace.mkdir()
    mock_executor._initial_cwd = str(workspace)
    mock_executor.session_manager.sessions = {}

    session = MagicMock()
    session.read_output.return_value = ""
    mock_executor.session_manager.create_session.return_value = session

    # First three opens are allowed to support small batch startup.
    for _ in range(3):
        obs = await mock_executor.terminal_run(
            TerminalRunAction(command="whoami", cwd=str(workspace))
        )
        assert obs.__class__.__name__ == "TerminalObservation"

    # Repeating open with no read/input should be blocked.
    blocked = await mock_executor.terminal_run(
        TerminalRunAction(command="whoami", cwd=str(workspace))
    )
    assert isinstance(blocked, ErrorObservation)
    assert "open loop detected" in blocked.content
    assert "action=read or action=input" in blocked.content
    assert "terminal_1" in blocked.content


@pytest.mark.asyncio
async def test_terminal_open_guardrail_allows_multi_session_batch_with_varied_commands(
    mock_executor, tmp_path
) -> None:
    workspace = tmp_path / "w"
    workspace.mkdir()
    mock_executor._initial_cwd = str(workspace)
    mock_executor.session_manager.sessions = {}

    session = MagicMock()
    session.read_output.return_value = ""
    mock_executor.session_manager.create_session.return_value = session

    commands = ["whoami", "pwd", "hostname", "echo ok", "Get-Date"]
    for cmd in commands:
        obs = await mock_executor.terminal_run(
            TerminalRunAction(command=cmd, cwd=str(workspace))
        )
        assert obs.__class__.__name__ == "TerminalObservation"


@pytest.mark.asyncio
async def test_terminal_run_rejects_invalid_resize_rows(
    mock_executor, tmp_path
) -> None:
    workspace = tmp_path / "w"
    workspace.mkdir()
    mock_executor._initial_cwd = str(workspace)
    mock_executor.session_manager.create_session.return_value = MagicMock()

    obs = await mock_executor.terminal_run(
        TerminalRunAction(command="echo 1", cwd=str(workspace), rows=0, cols=80)
    )

    assert isinstance(obs, ErrorObservation)
    assert "Invalid terminal size" in obs.content
    mock_executor.session_manager.close_session.assert_called()


@pytest.mark.asyncio
async def test_terminal_read_delta_reports_next_offset_and_progress(mock_executor):
    mock_session = MagicMock()
    mock_session.read_output_since.return_value = ("lineA\nlineB\n", 42, 0)
    mock_executor.session_manager.get_session.return_value = mock_session

    obs = await mock_executor.terminal_read(
        TerminalReadAction(session_id="terminal_1", offset=0, mode="delta")
    )

    assert obs.__class__.__name__ == "TerminalObservation"
    assert obs.next_offset == 42
    assert obs.has_new_output is True
    assert obs.state == "SESSION_OUTPUT_DELTA"
    assert isinstance(obs.tool_result, dict)
    assert obs.tool_result.get("payload", {}).get("next_offset") == 42


@pytest.mark.asyncio
async def test_terminal_read_delta_no_new_output_marks_no_progress(mock_executor):
    mock_session = MagicMock()
    mock_session.read_output_since.return_value = ("", 42, 0)
    mock_executor.session_manager.get_session.return_value = mock_session

    obs = await mock_executor.terminal_read(
        TerminalReadAction(session_id="terminal_1", offset=42, mode="delta")
    )

    assert obs.__class__.__name__ == "TerminalObservation"
    assert obs.has_new_output is False
    assert isinstance(obs.tool_result, dict)
    assert obs.tool_result.get("progress") is False


@pytest.mark.asyncio
async def test_terminal_read_delta_uses_stored_cursor_when_offset_none(
    mock_executor,
) -> None:
    """Delta read with offset=None must use last ``next_offset``, not always 0."""
    mock_session = MagicMock()
    mock_session.read_output_since.return_value = ("tail\n", 99, 0)
    mock_executor.session_manager.get_session.return_value = mock_session
    mock_executor._terminal_read_cursor["terminal_1"] = 77

    obs = await mock_executor.terminal_read(
        TerminalReadAction(session_id="terminal_1", mode="delta")
    )

    assert obs.__class__.__name__ == "TerminalObservation"
    mock_session.read_output_since.assert_called_once_with(77)
    assert obs.next_offset == 99
    assert mock_executor._terminal_read_cursor["terminal_1"] == 99


@pytest.mark.asyncio
async def test_terminal_input_post_read_uses_stored_cursor(mock_executor, tmp_path):
    """After input, delta read must use session cursor so we do not re-read from 0."""
    workspace = tmp_path / "w"
    workspace.mkdir()
    mock_executor._initial_cwd = str(workspace)

    offsets_seen: list[int] = []

    def read_since(off: int):
        offsets_seen.append(int(off))
        return ("", 300, 0)

    session = MagicMock()
    session.cwd = str(workspace)
    read_output_since = MagicMock(side_effect=read_since)
    session.read_output_since = read_output_since
    mock_executor.session_manager.get_session.return_value = session
    mock_executor._terminal_read_cursor["t-cursor"] = 250

    with patch(
        "backend.execution.action_execution_server.asyncio.sleep", return_value=None
    ):
        obs = await mock_executor.terminal_input(
            TerminalInputAction(session_id="t-cursor", control="enter")
        )

    assert obs.__class__.__name__ == "TerminalObservation"
    assert offsets_seen == [250]
    assert obs.has_new_output is False
    read_output_since.assert_called_once_with(250)
    assert mock_executor._terminal_read_cursor["t-cursor"] == 300


def test_pty_output_transcript_caption_notes_no_new_bytes_when_flag_false() -> None:
    from backend.cli.event_renderer import _pty_output_transcript_caption

    cap = _pty_output_transcript_caption(
        session_id="t1",
        n_lines=5,
        truncated=False,
        has_output=True,
        has_new_output=False,
    )
    assert "no new bytes since last read" in cap
