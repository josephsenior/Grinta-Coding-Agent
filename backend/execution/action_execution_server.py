"""This is the main file for the runtime client.

It is responsible for executing actions received from app backend and producing observations.

NOTE: this executes inside the local runtime environment.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, cast

from binaryornot.check import is_binary
from fastapi import FastAPI
from pydantic import BaseModel
from uvicorn import Config, Server

from backend.core.enums import FileEditSource, FileReadSource
from backend.core.logger import app_logger as logger
from backend.execution.debugger import DAPDebugManager
from backend.execution.file_operations import (
    ensure_directory_exists,
    execute_file_editor,
    get_max_edit_observation_chars,
    handle_directory_view,
    handle_file_read_errors,
    read_image_file,
    read_pdf_file,
    read_text_file,
    read_video_file,
    truncate_cmd_output,
    truncate_large_text,
    write_file_content,
)
from backend.execution.file_viewer_server import start_file_viewer_server
from backend.execution.mcp.proxy import MCPProxyManager
from backend.execution.plugin_loader import init_plugins
from backend.execution.plugins import ALL_PLUGINS, Plugin
from backend.execution.sandboxing import (
    is_sandboxed_local_profile,
    is_workspace_restricted_profile,
)
from backend.execution.security_enforcement import (
    evaluate_hardened_local_command_policy,
    path_is_within_workspace,
    tokenize_command,
)
from backend.execution.server_routes import (
    register_exception_handlers,
    register_routes,
)
from backend.execution.utils import find_available_tcp_port
from backend.execution.utils.diff import get_diff
from backend.execution.utils.file_editor import FileEditor
from backend.execution.utils.files import resolve_path as resolve_workspace_path
from backend.execution.utils.memory_monitor import MemoryMonitor
from backend.execution.utils.session_manager import SessionManager
from backend.ledger.action import (
    CmdRunAction,
    DebuggerAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
)
from backend.ledger.action.browser_tool import BrowserToolAction
from backend.ledger.action.code_nav import LspQueryAction
from backend.ledger.action.mcp import MCPAction
from backend.ledger.action.signal import SignalProgressAction
from backend.ledger.action.terminal import (
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
)
from backend.ledger.observation import (
    CmdOutputObservation,
    ErrorObservation,
    FileEditObservation,
    FileReadObservation,
    FileWriteObservation,
    LspQueryObservation,
    Observation,
)
from backend.ledger.observation.signal import SignalProgressObservation
from backend.ledger.observation.terminal import TerminalObservation
from backend.persistence.locations import get_workspace_downloads_dir
from backend.utils.async_utils import call_sync_from_async
from backend.utils.regex_limits import try_compile_user_regex

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
_POWERSHELL_BUILTIN_COMMANDS = frozenset(
    {
        "Get-Content",
        "Write-Output",
        "Get-ChildItem",
        "Select-String",
        "Set-Location",
        "Select-Object",
        "Measure-Object",
        "Out-File",
        "Test-Path",
        "Remove-Item",
    }
)

# Note: Import is deferred to avoid executing windows_bash.py on non-Windows platforms
if sys.platform == "win32":
    pass


class ActionRequest(BaseModel):
    """Incoming action execution request envelope sent to runtime server."""

    event: dict[str, Any]


class RuntimeExecutor:
    """RuntimeExecutor runs inside the local runtime environment.

    It is responsible for executing actions received from app backend and producing observations.
    """

    def __init__(
        self,
        plugins_to_load: list[Plugin],
        work_dir: str,
        username: str,
        user_id: int,
        enable_browser: bool,
        tool_registry: Any | None = None,  # ToolRegistry for cross-platform support
        mcp_config: Any | None = None,
        security_config: Any | None = None,
    ) -> None:
        """Create runtime executor, initialize workspace, and prepare tooling integrations."""
        self.username = username
        self.user_id = user_id
        self._initial_cwd = work_dir
        self.max_memory_gb: int | None = None  # Will be set during ainit if available
        self.tool_registry = tool_registry

        # Initialize SessionManager — uses the same work_dir as FileEditor
        self.session_manager = SessionManager(
            work_dir=work_dir,
            username=username,
            tool_registry=tool_registry,
            max_memory_gb=None,  # Will be updated in ainit
        )
        self.session_manager.security_config = security_config

        if self.session_manager.tool_registry is not None:
            from backend.engine.tools.prompt import set_active_tool_registry

            set_active_tool_registry(self.session_manager.tool_registry)

        # Legacy attribute; native browser uses GrintaNativeBrowser (optional browser-use).
        self.browser: Any | None = None
        self.enable_browser = enable_browser
        self._native_browser: Any | None = None

        # Keep a separate cancellation service for non-session tasks if needed,
        # or just rely on session manager for shell tasks.
        # But RuntimeExecutor might have other tasks? For now, let's keep it minimal.

        self.lock = asyncio.Lock()
        self.plugins: dict[str, Plugin] = {}
        # We need the file editor for ACI actions (view) even if we use helper functions
        self.file_editor = FileEditor(workspace_root=self._initial_cwd)
        self.plugins_to_load = plugins_to_load
        self._initialized = False
        self.memory_monitor = MemoryMonitor()
        self.start_time = time.time()
        self.last_execution_time = time.time()
        self.downloaded_files: list[str] = []
        self.downloads_directory = get_workspace_downloads_dir(work_dir)
        self.debug_manager = DAPDebugManager(work_dir)

        self._terminal_session_seq: int = 0
        self._terminal_sessions_awaiting_interaction: list[str] = []
        self._terminal_open_commands_no_interaction: list[str] = []
        # Per interactive session: last delta-read byte cursor (``next_offset`` from PTY).
        # Keeps ``terminal_input`` post-write reads from using offset=0, which would
        # re-fetch the whole retained buffer and falsely signal progress every time.
        self._terminal_read_cursor: dict[str, int] = {}

        # MCP clients are created lazily on first use.
        self._mcp_config = mcp_config
        self.security_config = security_config
        self._mcp_clients: list[Any] | None = None
        # Same server list passed to create_mcps (after Windows stdio filter), for diagnostics.
        self._mcp_servers_resolved: list[Any] | None = None

    @property
    def initial_cwd(self) -> str:
        """Get the initial working directory for the action execution server."""
        return self._initial_cwd

    def _create_bash_session(self, cwd: str | None = None):
        """Create a shell session appropriate for the current platform."""
        # Delegated to SessionManager
        return self.session_manager.create_session(cwd=cwd)

    async def hard_kill(self) -> None:
        """Best-effort immediate termination of processes started by this runtime."""
        self.debug_manager.close_all()
        self.session_manager.close_all()

    async def ainit(self) -> None:
        """Initialize action execution server asynchronously."""
        try:
            # Set memory limit from environment or system stats
            import psutil as _psutil

            total_mem_gb = int(_psutil.virtual_memory().total / (1024**3))
            # Reserve 2GB for system/other processes
            self.max_memory_gb = max(1, total_mem_gb - 2)

            # Update session manager with memory limit
            self.session_manager.max_memory_gb = self.max_memory_gb

            # Step 1: Initialize bash session
            logger.info("Step 1/4: Initializing default shell session...")
            self.session_manager.create_session(session_id="default")

            # Step 2: Initialize plugins
            logger.info("Step 2/4: Initializing plugins...")
            self.plugins = await init_plugins(self.plugins_to_load, self.username)

            # Step 3: Initialize shell commands/aliases
            logger.info("Step 3/4: Setting up shell commands...")
            self._init_shell_commands()

            # Step 4: Start memory monitoring
            logger.info("Step 4/4: Starting memory monitor...")
            self.memory_monitor.start_monitoring()

            logger.info("All initialization steps completed successfully")
            self._initialized = True
        except Exception as e:
            logger.error(
                "RuntimeExecutor initialization failed at step: %s",
                e,
                exc_info=True,
            )
            # Ensure we clean up if initialization fails
            await self.hard_kill()
            raise

    def initialized(self) -> bool:
        """Check if action execution server has completed initialization."""
        return self._initialized

    def _init_shell_commands(self):
        # We need to set up shell-native aliases and functions for better UX.
        shell_session = self.session_manager.get_session("default")
        assert shell_session is not None

        use_powershell = self._uses_powershell_shell_contract()

        shell_session.execute(
            CmdRunAction(
                command=self._build_shell_git_config_command(use_powershell),
            )
        )

        # Set up env_check helper for diagnosing environment issues after
        # cascading failures. Shows Python version, key packages, disk
        # usage, and memory stats in one command.
        shell_session.execute(
            CmdRunAction(command=self._build_env_check_command(use_powershell))
        )

        # Initialize plugin commands.
        for plugin in self.plugins.values():
            init_cmds = plugin.get_init_bash_commands()
            if init_cmds:
                for cmd in init_cmds:
                    shell_session.execute(CmdRunAction(command=cmd))

    def _build_shell_git_config_command(self, use_powershell: bool) -> str:
        separator = ";" if use_powershell else "&&"
        return (
            f'git config --global user.name "{self.username}" '
            f'{separator} git config --global user.email "{self.username}@example.com"'
        )

    @staticmethod
    def _build_env_check_command(use_powershell: bool) -> str:
        if use_powershell:
            return (
                "function global:env_check { "
                "Write-Output '=== PYTHON ==='; "
                "if (Get-Command python -ErrorAction SilentlyContinue) { python --version } "
                "elseif (Get-Command python3 -ErrorAction SilentlyContinue) { python3 --version } "
                "else { Write-Output 'python not found' }; "
                "Write-Output '=== KEY PACKAGES ==='; "
                "if (Get-Command pip -ErrorAction SilentlyContinue) { "
                "pip list --format=freeze | Select-Object -First 30 "
                "}; "
                "Write-Output '=== DISK ==='; "
                "Get-PSDrive -PSProvider FileSystem; "
                "Write-Output '=== MEMORY ==='; "
                "if (Get-Command Get-CimInstance -ErrorAction SilentlyContinue) { "
                "Get-CimInstance Win32_OperatingSystem | Select-Object "
                "@{Name='FreeMemoryMB';Expression={[math]::Round($_.FreePhysicalMemory / 1024, 1)}}, "
                "@{Name='TotalMemoryMB';Expression={[math]::Round($_.TotalVisibleMemorySize / 1024, 1)}} "
                "} "
                "}"
            )

        return (
            "alias env_check='"
            'echo "=== PYTHON ===" && python3 --version 2>/dev/null || python --version 2>/dev/null && '
            'echo "=== KEY PACKAGES ===" && pip list --format=freeze 2>/dev/null | head -30 && '
            'echo "=== DISK ===" && df -h . 2>/dev/null && '
            'echo "=== MEMORY ===" && free -h 2>/dev/null || vm_stat 2>/dev/null; '
            "true'"
        )

    def _uses_powershell_shell_contract(self) -> bool:
        """Return True only when the active Windows terminal contract is PowerShell."""
        if sys.platform != "win32":
            return False

        tool_registry = getattr(self.session_manager, "tool_registry", None)
        if tool_registry is not None:
            from backend.execution.utils.tool_registry import (
                resolve_windows_powershell_preference,
            )

            has_bash_raw = getattr(tool_registry, "has_bash", False)
            has_powershell_raw = getattr(tool_registry, "has_powershell", False)
            has_bash = has_bash_raw if isinstance(has_bash_raw, bool) else False
            has_powershell = (
                has_powershell_raw if isinstance(has_powershell_raw, bool) else False
            )

            if has_bash or has_powershell:
                return resolve_windows_powershell_preference(
                    has_bash=has_bash,
                    has_powershell=has_powershell,
                )

        # Fallback when tool registry details are unavailable in tests/mocks.
        default_session = self.session_manager.get_session("default")
        session_name = (
            default_session.__class__.__name__.lower() if default_session else ""
        )
        return "powershell" in session_name

    async def run_action(self, action) -> Observation:
        """Execute any action through action execution server."""
        async with self.lock:
            action_type = action.action
            obs = await getattr(self, action_type)(action)

        # Strip ANSI from text fields for consistent CLI / log display.
        if hasattr(obs, "content") and isinstance(obs.content, str):
            obs.content = self._strip_ansi_obs_text(obs.content)
        if hasattr(obs, "path") and isinstance(obs.path, str):
            obs.path = self._strip_ansi_obs_text(obs.path)
        if hasattr(obs, "message") and isinstance(obs.message, str):
            try:
                obs.message = self._strip_ansi_obs_text(obs.message)
            except AttributeError:
                pass  # message is read-only (e.g. MCPObservation); content already sanitized
        return obs

    @staticmethod
    def _strip_ansi_obs_text(text: str) -> str:
        """Strip ANSI escape codes from observation text."""
        if not text:
            return text
        return _ANSI_ESCAPE_RE.sub("", text)

    def _should_rewrite_python3_to_python(self) -> bool:
        """Return True only when active Windows terminal contract is PowerShell.

        On Windows in bash mode, commands should remain bash-native and python3
        should not be rewritten.
        """
        return self._uses_powershell_shell_contract()

    @staticmethod
    def _extract_failure_signature(content: str) -> str:
        """Build a compact error signature for repeated-failure detection."""
        if not content:
            return ""
        lines = [line.strip().lower() for line in content.splitlines() if line.strip()]
        if not lines:
            return ""
        # Prefer the tail where shell errors usually appear.
        tail = " | ".join(lines[-3:])
        return tail[:300]

    def _workspace_root(self) -> Path:
        return Path(self._initial_cwd).resolve()

    def _is_workspace_restricted_profile(self) -> bool:
        return is_workspace_restricted_profile(self.security_config)

    def _is_sandboxed_local(self) -> bool:
        return is_sandboxed_local_profile(self.security_config)

    def _validate_interactive_session_scope(
        self, session_id: str, session: Any
    ) -> ErrorObservation | None:
        if not self._is_workspace_restricted_profile():
            return None

        current_cwd = Path(getattr(session, "cwd", self._initial_cwd)).resolve()
        if path_is_within_workspace(current_cwd, self._workspace_root()):
            return None

        self.session_manager.close_session(session_id)
        self._clear_terminal_read_cursor(session_id)
        return ErrorObservation(
            content=(
                "Interactive terminal session closed by hardened_local policy: "
                f"session cwd escaped the workspace. Session: {session_id} | cwd={current_cwd}"
            )
        )

    def _predict_interactive_cwd_change(
        self, command: str, current_cwd: Path
    ) -> tuple[Path | None, str | None]:
        tokens = tokenize_command(command)
        if not tokens:
            return (None, None)

        op = tokens[0].strip().lower()
        if op not in {"cd", "pushd", "set-location", "sl"}:
            return (None, None)

        if len(tokens) < 2 or tokens[1].strip() in {
            "",
            "~",
            "$HOME",
            "%USERPROFILE%",
            "-",
        }:
            return (
                None,
                "Action blocked by hardened_local policy: interactive directory changes must target an explicit path inside the workspace.",
            )

        target = Path(tokens[1])
        predicted = (
            target.resolve()
            if target.is_absolute()
            else (current_cwd / target).resolve()
        )
        if not path_is_within_workspace(predicted, self._workspace_root()):
            return (
                None,
                "Action blocked by hardened_local policy: interactive terminal sessions cannot change directory outside the workspace. "
                f"Requested cwd: {predicted}",
            )
        return (predicted, None)

    def _evaluate_interactive_terminal_command(
        self, command: str, current_cwd: Path
    ) -> tuple[Path | None, ErrorObservation | None]:
        if not self._is_workspace_restricted_profile():
            return (None, None)

        stripped = command.strip()
        if not stripped:
            return (None, None)

        if any(separator in stripped for separator in ("\n", "&&", ";", "||")):
            return (
                None,
                ErrorObservation(
                    content=(
                        "Action blocked by hardened_local policy: interactive terminal input cannot contain chained or multiline commands."
                    )
                ),
            )

        block_message = evaluate_hardened_local_command_policy(
            command=stripped,
            security_config=self.security_config,
            workspace_root=self._workspace_root(),
            requested_cwd=str(current_cwd),
            base_cwd=str(current_cwd),
            is_background=stripped.endswith("&"),
        )
        if block_message is not None:
            return (None, ErrorObservation(content=block_message))

        predicted_cwd, cwd_error = self._predict_interactive_cwd_change(
            stripped, current_cwd
        )
        if cwd_error is not None:
            return (None, ErrorObservation(content=cwd_error))

        return (predicted_cwd, None)

    def _resolve_effective_cwd(
        self, requested_cwd: str | None, base_cwd: str | None = None
    ) -> Path:
        workspace_root = self._workspace_root()
        base_path = Path(base_cwd).resolve() if base_cwd else workspace_root
        if not requested_cwd:
            return base_path
        requested = Path(requested_cwd)
        if requested.is_absolute():
            return requested.resolve()
        return (base_path / requested).resolve()

    def _validate_workspace_scoped_cwd(
        self,
        command: str,
        requested_cwd: str | None,
        base_cwd: str | None = None,
    ) -> ErrorObservation | None:
        if not self._is_workspace_restricted_profile():
            return None

        workspace_root = self._workspace_root()
        effective_cwd = self._resolve_effective_cwd(requested_cwd, base_cwd)
        try:
            effective_cwd.relative_to(workspace_root)
        except ValueError:
            return ErrorObservation(
                content=(
                    "Action blocked by hardened_local policy: command execution must stay inside the workspace. "
                    f"Command: {command} | cwd={effective_cwd}"
                )
            )
        return None

    def _resolve_workspace_file_path(self, path: str, working_dir: str) -> str:
        return str(resolve_workspace_path(path, working_dir, self._initial_cwd))

    def _annotate_environment_errors(self, observation: CmdOutputObservation) -> None:
        """Append structural tags for errors the model cannot infer from raw output alone."""
        content = observation.content
        if not content:
            return

        exit_code = int(getattr(observation.metadata, "exit_code", 0) or 0)
        if exit_code == 0:
            return

        shell_mismatch = self._detect_powershell_in_bash_mismatch(
            getattr(observation, "command", ""),
            content,
        )
        if shell_mismatch:
            observation.content += f"\n\n[SHELL_MISMATCH] {shell_mismatch}"
            return

        scaffold_failure = self._detect_scaffold_setup_failure(
            getattr(observation, "command", ""),
            content,
        )
        if scaffold_failure:
            observation.content += f"\n\n[SCAFFOLD_SETUP_FAILED] {scaffold_failure}"

    @staticmethod
    def _detect_powershell_in_bash_mismatch(command: str, content: str) -> str | None:
        """Return guidance when PowerShell syntax appears to be running in bash."""
        if not command or not content:
            return None

        lower_content = content.lower()
        if "/bin/bash" not in lower_content and "bash:" not in lower_content:
            return None
        if (
            "command not found" not in lower_content
            and "not recognized as" not in lower_content
        ):
            return None

        _bash_fix = (
            "This terminal is Git Bash — rewrite the command using bash syntax only "
            "(ls, cat, grep, find, echo, cd, mkdir, rm, pwd). "
            "Do NOT use any PowerShell cmdlets."
        )

        missing_match = re.search(
            r"([A-Za-z][A-Za-z0-9-]*)\s*:\s*command not found", content
        )
        if missing_match:
            missing_cmd = missing_match.group(1)
            if missing_cmd in _POWERSHELL_BUILTIN_COMMANDS:
                return (
                    f"`{missing_cmd}` is a PowerShell cmdlet, not available in bash. "
                    f"{_bash_fix}"
                )

        command_tokens = set(re.findall(r"\b[A-Za-z][A-Za-z0-9-]*\b", command))
        for token in _POWERSHELL_BUILTIN_COMMANDS:
            if token in command_tokens:
                return (
                    f"`{token}` is a PowerShell cmdlet, not available in bash. "
                    f"{_bash_fix}"
                )

        return None

    @staticmethod
    def _detect_scaffold_setup_failure(command: str, content: str) -> str | None:
        """Return guidance when a chained project scaffold never produced package.json."""
        if not command or not content:
            return None

        lower_command = command.lower()
        if "&&" not in lower_command:
            return None

        scaffold_tokens = (
            "create-vite",
            "npm create vite",
            "npm init vite",
            "create-next-app",
            "create-react-app",
            "cargo new",
        )
        if not any(token in lower_command for token in scaffold_tokens):
            return None

        lower_content = content.lower()
        if "could not read package.json" not in lower_content:
            return None
        if (
            "enoent" not in lower_content
            and "no such file or directory" not in lower_content
        ):
            return None

        return (
            "The scaffold step did not create a project before follow-up install commands ran. "
            "Run the generator by itself first, inspect its output, and if the current directory "
            'is not empty scaffold into a fresh subdirectory instead of ".".'
        )

    async def run(
        self, action: CmdRunAction
    ) -> CmdOutputObservation | ErrorObservation | TerminalObservation:
        """Execute bash/shell command.

        Handles background execution (new session), static execution (temporary
        session), and foreground execution (default session). Applies grep filtering
        if requested, truncates output, and attaches detected server info to
        observation extras when relevant.
        """
        try:
            # Rewrite python3->python only in Windows PowerShell mode.
            if self._should_rewrite_python3_to_python() and action.command:
                action.command = re.sub(r"\bpython3\b", "python", action.command)

            default_session = self.session_manager.get_session("default")
            base_cwd = default_session.cwd if default_session else self._initial_cwd
            cwd_error = self._validate_workspace_scoped_cwd(
                action.command,
                action.cwd,
                base_cwd,
            )
            if cwd_error is not None:
                return cwd_error

            if action.is_background:
                return await self._run_background_cmd(action)

            observation = await self._run_foreground_cmd(action)
            if isinstance(observation, ErrorObservation):
                return observation

            if action.grep_pattern and isinstance(observation.content, str):
                observation.content = self._apply_grep_filter(
                    observation.content, action.grep_pattern
                )
            if isinstance(observation.content, str):
                observation.content = truncate_cmd_output(observation.content)

            # Annotate environment-level failures with actionable guidance.
            self._annotate_environment_errors(observation)

            if not action.is_static:
                self._attach_detected_server(
                    observation, self.session_manager.get_session("default")
                )

            return observation
        except Exception as e:
            logger.error("Error running command: %s", e)
            return ErrorObservation(str(e))

    async def _run_background_cmd(self, action: CmdRunAction) -> TerminalObservation:
        """Start a background command in a new session.

        Creates a dedicated session, writes the command, waits briefly for
        initial output, and returns a TerminalObservation with the session ID
        for later checking.
        """
        session_id = f"bg-{uuid.uuid4().hex[:8]}"
        default_session = self.session_manager.get_session("default")
        cwd = str(
            self._resolve_effective_cwd(
                action.cwd,
                (default_session.cwd if default_session else None) or self._initial_cwd,
            )
        )
        session = self.session_manager.create_session(session_id=session_id, cwd=cwd)
        logger.debug(
            "Starting background task in session %s: %s", session_id, action.command
        )
        session.write_input(action.command + "\n")
        await asyncio.sleep(0.5)
        content = session.read_output()
        return TerminalObservation(
            session_id=session_id,
            content=f"Background task started. Session ID: {session_id}\nInitial Output:\n{content}",
        )

    async def debugger(self, action: DebuggerAction) -> Observation:
        """Execute a debugger action through the DAP manager."""
        return self.debug_manager.handle(action)

    async def _run_foreground_cmd(
        self, action: CmdRunAction
    ) -> CmdOutputObservation | ErrorObservation:
        """Execute command in foreground (static or default session).

        Routes to _run_static_cmd for isolated execution, or uses the default
        session for normal foreground commands.
        """
        if action.is_static:
            return await self._run_static_cmd(action)
        bash_session = self.session_manager.get_session("default")
        if bash_session is None:
            return ErrorObservation("Default shell session not initialized")
        return cast(
            CmdOutputObservation,
            await call_sync_from_async(bash_session.execute, action),
        )

    async def _run_static_cmd(
        self, action: CmdRunAction
    ) -> CmdOutputObservation | ErrorObservation:
        """Execute in a temporary static session.

        Creates a short-lived session, runs the command, and closes the
        session immediately. Used for isolated/one-off executions.
        """
        temp_id = f"static-{uuid.uuid4().hex[:8]}"
        default_session = self.session_manager.get_session("default")
        cwd = str(
            self._resolve_effective_cwd(
                action.cwd,
                (default_session.cwd if default_session else None) or self._initial_cwd,
            )
        )
        bash_session = self.session_manager.create_session(session_id=temp_id, cwd=cwd)
        try:
            return cast(
                CmdOutputObservation,
                await call_sync_from_async(bash_session.execute, action),
            )
        finally:
            self.session_manager.close_session(temp_id)

    def _apply_grep_filter(self, content: str, pattern_str: str) -> str:
        """Filter content lines by grep pattern.

        Returns only lines matching the regex. On invalid pattern, prepends
        an error message to the content.
        """
        pattern, err = try_compile_user_regex(pattern_str)
        if pattern is None:
            return (
                f"[Grep Error: Invalid regex pattern '{pattern_str}': {err}]\n{content}"
            )

        lines = content.splitlines()
        filtered = [line for line in lines if pattern.search(line)]
        result = "\n".join(filtered)
        return result or f"[Grep: No lines matched pattern '{pattern_str}']"

    def _attach_detected_server(
        self, observation: CmdOutputObservation, bash_session: Any
    ) -> None:
        """Attach detected server info to observation extras if present.

        When the bash session detected a running server (e.g. dev server),
        adds port, url, protocol, and health_status to observation.extras
        for client processing.
        """
        if bash_session is None:
            return
        detected = cast(Any, bash_session.get_detected_server())
        if not detected:
            return
        logger.info("🚀 Adding detected server to observation extras: %s", detected.url)
        if not hasattr(observation, "extras"):
            observation.extras = {}  # type: ignore[attr-defined]
        observation.extras["server_ready"] = {  # type: ignore[attr-defined]
            "port": detected.port,
            "url": detected.url,
            "protocol": detected.protocol,
            "health_status": detected.health_status,
        }

    def _apply_terminal_resize_if_requested(
        self, session: Any, rows: int | None, cols: int | None
    ) -> ErrorObservation | None:
        """Resize the TTY if ``rows`` and ``cols`` are set; return an error on bad input."""
        if rows is None and cols is None:
            return None
        if rows is None or cols is None:
            return ErrorObservation(
                "Terminal resize requires both `rows` and `cols` (or omit both)."
            )
        r, c = int(rows), int(cols)
        if not (1 <= r <= 500 and 1 <= c <= 2000):
            return ErrorObservation(
                f"Invalid terminal size: rows={r}, cols={c} "
                "(allowed: rows 1–500, cols 1–2000)."
            )
        try:
            session.resize(r, c)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Terminal resize not applied: %s", exc)
        return None

    def _next_terminal_session_id(self) -> str:
        """Return a human-friendly unique terminal id for this runtime."""
        sessions_obj = getattr(self.session_manager, "sessions", None)
        existing_ids = (
            set(sessions_obj.keys()) if isinstance(sessions_obj, dict) else set()
        )
        while True:
            self._terminal_session_seq += 1
            candidate = f"terminal_{self._terminal_session_seq}"
            if candidate not in existing_ids:
                return candidate

    @staticmethod
    def _normalize_terminal_command(command: str) -> str:
        """Normalize command text for loop detection comparisons."""
        return " ".join((command or "").strip().lower().split())

    def _mark_terminal_session_interaction(self, session_id: str) -> None:
        """Mark a terminal session as used (read/input happened)."""
        if session_id in self._terminal_sessions_awaiting_interaction:
            self._terminal_sessions_awaiting_interaction = [
                sid
                for sid in self._terminal_sessions_awaiting_interaction
                if sid != session_id
            ]
        # Once progress is made, clear no-interaction open history so new batches are valid.
        self._terminal_open_commands_no_interaction.clear()

    def _terminal_open_guardrail_error(self, command: str) -> ErrorObservation | None:
        """Block pathological open-only loops while allowing valid batch session opens."""
        pending = list(self._terminal_sessions_awaiting_interaction)
        if len(pending) < 3:
            return None

        normalized = self._normalize_terminal_command(command)
        recent = self._terminal_open_commands_no_interaction[-3:]
        # Repetitive opens with no reads/inputs usually indicate a stuck loop.
        repetitive = bool(recent) and all(c == normalized for c in recent)

        # Hard cap keeps runaway loops bounded even if commands vary.
        if not repetitive and len(pending) < 6:
            return None

        sample_ids = ", ".join(pending[:8]) if pending else "none"
        return ErrorObservation(
            "terminal_manager open loop detected: multiple sessions were opened but "
            "none were used via action=read or action=input. "
            f"Current command={command!r}. "
            f"Use one of these existing session_id values next: {sample_ids}."
        )

    def _missing_terminal_session_error(
        self, session_id: str, *, operation: str
    ) -> ErrorObservation:
        """Return a clear agent-facing message for nonexistent terminal IDs."""
        sessions_obj = getattr(self.session_manager, "sessions", None)
        active_ids = (
            sorted(k for k in sessions_obj if k != "default")
            if isinstance(sessions_obj, dict)
            else []
        )
        if active_ids:
            suggestion = (
                f"Active session IDs: {', '.join(active_ids[:8])}. "
                "Use one returned by terminal_manager action=open."
            )
        else:
            suggestion = (
                "No active terminal sessions exist right now. "
                "Call terminal_manager with action=open first, then reuse that session_id."
            )
        return ErrorObservation(
            f"Terminal session '{session_id}' does not exist for action={operation}. "
            f"Do not invent IDs like terminal_session_0. {suggestion}"
        )

    @staticmethod
    def _terminal_mode(mode: str | None) -> str:
        normalized = (mode or "delta").strip().lower()
        if normalized not in {"delta", "snapshot"}:
            return "delta"
        return normalized

    @staticmethod
    def _terminal_read_empty_hints(
        *, mode: str, has_new_output: bool
    ) -> dict[str, Any]:
        """Structured hints when a read returns no new bytes (honest, not heuristics)."""
        if has_new_output:
            return {}
        if mode == "delta":
            return {
                "delta_empty": True,
                "empty_reason": "no_new_bytes_since_offset",
            }
        return {
            "snapshot_empty": True,
            "empty_reason": "no_printable_output_in_buffer",
        }

    def _read_terminal_with_mode(
        self,
        *,
        session: Any,
        mode: str,
        offset: int | None,
    ) -> tuple[str, int | None, bool, int | None]:
        """Read terminal output using either delta cursor or snapshot semantics."""
        if mode == "snapshot":
            content = session.read_output()
            has_new_output = bool((content or "").strip())
            return content, None, has_new_output, None

        safe_offset = max(0, int(offset or 0))
        read_since = getattr(session, "read_output_since", None)
        if callable(read_since):
            try:
                result = read_since(safe_offset)
                if (
                    isinstance(result, tuple)
                    and len(result) == 3
                    and isinstance(result[0], str)
                ):
                    content, next_offset, dropped_chars = result
                else:
                    raise ValueError("invalid read_output_since result shape")
            except Exception:
                content = session.read_output()
                next_offset = len(content or "")
                dropped_chars = None
        else:
            # Fallback for older/alternate session implementations.
            content = session.read_output()
            next_offset = len(content or "")
            dropped_chars = None
        has_new_output = bool(content)
        return content, int(next_offset), has_new_output, dropped_chars

    def _get_terminal_read_cursor(self, session_id: str) -> int:
        return int(self._terminal_read_cursor.get(session_id, 0))

    def _advance_terminal_read_cursor(
        self, session_id: str, next_offset: int | None, *, mode: str = "delta"
    ) -> None:
        if (mode or "").lower() != "delta" or next_offset is None:
            return
        self._terminal_read_cursor[session_id] = int(next_offset)

    def _clear_terminal_read_cursor(self, session_id: str) -> None:
        self._terminal_read_cursor.pop(session_id, None)

    async def terminal_run(self, action: TerminalRunAction) -> Observation:
        """Start a new interactive terminal session."""
        try:
            guard_err = self._terminal_open_guardrail_error(action.command or "")
            if guard_err is not None:
                return guard_err

            # Generate a simple human-friendly session ID.
            session_id = self._next_terminal_session_id()

            # Determine working directory
            # Prefer provided CWD -> default session CWD -> initial CWD
            default_session = self.session_manager.get_session("default")
            cwd = action.cwd
            if not cwd and default_session:
                cwd = default_session.cwd
            if not cwd:
                cwd = self._initial_cwd

            cwd_error = self._validate_workspace_scoped_cwd(
                action.command or "<interactive terminal>",
                action.cwd,
                cwd,
            )
            if cwd_error is not None:
                return cwd_error

            cwd = str(self._resolve_effective_cwd(action.cwd, cwd))

            # Create the new session via manager.  ``interactive=True`` picks
            # the OS-agnostic PTY backend so ``write_input`` / ``read_output``
            # work on Windows and on POSIX without tmux (with graceful fallback
            # if the PTY backend is unavailable).
            session = self.session_manager.create_session(
                session_id=session_id, cwd=cwd, interactive=True
            )

            resize_err = self._apply_terminal_resize_if_requested(
                session, action.rows, action.cols
            )
            if resize_err is not None:
                self.session_manager.close_session(session_id)
                self._clear_terminal_read_cursor(session_id)
                return resize_err

            if action.command:
                predicted_cwd, policy_error = (
                    self._evaluate_interactive_terminal_command(
                        action.command,
                        Path(cwd).resolve(),
                    )
                )
                if policy_error is not None:
                    self.session_manager.close_session(session_id)
                    self._clear_terminal_read_cursor(session_id)
                    return policy_error
                # Send the initial command if provided
                logger.debug(
                    "Running initial command in terminal %s: %s",
                    session_id,
                    action.command,
                )
                # Attempt to write input. If underlying session doesn't support input,
                # it will log a warning but not crash.
                session.write_input(action.command + "\n")
                if predicted_cwd is not None and hasattr(session, "_cwd"):
                    session._cwd = str(predicted_cwd)  # type: ignore[attr-defined]

            # Return initial output as typed structured envelope.
            content, next_offset, has_new_output, dropped_chars = (
                self._read_terminal_with_mode(
                    session=session,
                    mode="delta",
                    offset=0,
                )
            )
            self._terminal_sessions_awaiting_interaction.append(session_id)
            self._terminal_open_commands_no_interaction.append(
                self._normalize_terminal_command(action.command or "")
            )
            obs = TerminalObservation(
                session_id=session_id,
                content=content,
                next_offset=next_offset,
                has_new_output=has_new_output,
                dropped_chars=dropped_chars,
                state="SESSION_OPENED",
            )
            empty_hints = self._terminal_read_empty_hints(
                mode="delta", has_new_output=has_new_output
            )
            obs.tool_result = {
                "tool": "terminal_manager",
                "ok": True,
                "error_code": None,
                "retryable": False,
                "state": "SESSION_OPENED",
                "next_actions": ["read", "input"],
                "payload": {
                    "session_id": session_id,
                    "mode": "delta",
                    "next_offset": next_offset,
                    "has_new_output": has_new_output,
                    "dropped_chars": dropped_chars,
                    **empty_hints,
                },
                "progress": bool(has_new_output),
            }
            self._advance_terminal_read_cursor(session_id, next_offset, mode="delta")
            return obs

        except Exception as e:
            logger.error("Error starting terminal session: %s", e, exc_info=True)
            return ErrorObservation(f"Failed to start terminal: {e}")

    async def terminal_input(self, action: TerminalInputAction) -> Observation:
        """Send input to an interactive terminal session."""
        session = self.session_manager.get_session(action.session_id)
        if not session:
            return self._missing_terminal_session_error(
                action.session_id, operation="input"
            )

        scope_error = self._validate_interactive_session_scope(
            action.session_id, session
        )
        if scope_error is not None:
            return scope_error

        try:
            resize_err = self._apply_terminal_resize_if_requested(
                session, action.rows, action.cols
            )
            if resize_err is not None:
                return resize_err

            if action.control is not None and str(action.control).strip() != "":
                session.write_input(str(action.control), is_control=True)

            write_content = action.input
            predicted_cwd: Path | None = None
            if write_content:
                if not action.is_control:
                    policy_line = write_content.rstrip("\r\n")
                    predicted_cwd, policy_error = (
                        self._evaluate_interactive_terminal_command(
                            policy_line,
                            Path(getattr(session, "cwd", self._initial_cwd)).resolve(),
                        )
                    )
                    if policy_error is not None:
                        return policy_error

                to_send = write_content
                if (
                    action.submit
                    and not action.is_control
                    and to_send
                    and not to_send.endswith(("\n", "\r\n"))
                ):
                    to_send = f"{to_send}\n"

                session.write_input(to_send, is_control=action.is_control)
            if predicted_cwd is not None and hasattr(session, "_cwd"):
                session._cwd = str(predicted_cwd)  # type: ignore[attr-defined]
            # Wait briefly for output to appear
            await asyncio.sleep(0.2)
            read_offset = self._get_terminal_read_cursor(action.session_id)
            content, next_offset, has_new_output, dropped_chars = (
                self._read_terminal_with_mode(
                    session=session,
                    mode="delta",
                    offset=read_offset,
                )
            )
            self._advance_terminal_read_cursor(
                action.session_id, next_offset, mode="delta"
            )
            self._mark_terminal_session_interaction(action.session_id)
            empty_hints = self._terminal_read_empty_hints(
                mode="delta", has_new_output=has_new_output
            )
            obs = TerminalObservation(
                session_id=action.session_id,
                content=content,
                next_offset=next_offset,
                has_new_output=has_new_output,
                dropped_chars=dropped_chars,
                state="SESSION_INTERACTED",
            )
            obs.tool_result = {
                "tool": "terminal_manager",
                "ok": True,
                "error_code": None,
                "retryable": False,
                "state": "SESSION_INTERACTED",
                "next_actions": ["read", "input"],
                "payload": {
                    "session_id": action.session_id,
                    "mode": "delta",
                    "next_offset": next_offset,
                    "has_new_output": has_new_output,
                    "dropped_chars": dropped_chars,
                    **empty_hints,
                },
                "progress": bool(has_new_output),
            }
            return obs
        except Exception as e:
            logger.error("Error sending input to terminal %s: %s", action.session_id, e)
            return ErrorObservation(f"Failed to send input: {e}")

    async def terminal_read(self, action: TerminalReadAction) -> Observation:
        """Read the output of an interactive terminal session."""
        session = self.session_manager.get_session(action.session_id)
        if not session:
            return self._missing_terminal_session_error(
                action.session_id, operation="read"
            )

        scope_error = self._validate_interactive_session_scope(
            action.session_id, session
        )
        if scope_error is not None:
            return scope_error

        try:
            resize_err = self._apply_terminal_resize_if_requested(
                session, action.rows, action.cols
            )
            if resize_err is not None:
                return resize_err

            mode = self._terminal_mode(action.mode)
            read_offset = (
                action.offset
                if action.offset is not None
                else (
                    self._get_terminal_read_cursor(action.session_id)
                    if mode == "delta"
                    else 0
                )
            )
            content, next_offset, has_new_output, dropped_chars = (
                self._read_terminal_with_mode(
                    session=session,
                    mode=mode,
                    offset=read_offset,
                )
            )
            self._advance_terminal_read_cursor(
                action.session_id, next_offset, mode=mode
            )
            self._mark_terminal_session_interaction(action.session_id)
            empty_hints = self._terminal_read_empty_hints(
                mode=mode, has_new_output=has_new_output
            )
            obs = TerminalObservation(
                session_id=action.session_id,
                content=content,
                next_offset=next_offset,
                has_new_output=has_new_output,
                dropped_chars=dropped_chars,
                state=(
                    "SESSION_OUTPUT_DELTA"
                    if mode == "delta"
                    else "SESSION_OUTPUT_SNAPSHOT"
                ),
            )
            obs.tool_result = {
                "tool": "terminal_manager",
                "ok": True,
                "error_code": None,
                "retryable": False,
                "state": (
                    "SESSION_OUTPUT_DELTA"
                    if mode == "delta"
                    else "SESSION_OUTPUT_SNAPSHOT"
                ),
                "next_actions": ["read", "input"],
                "payload": {
                    "session_id": action.session_id,
                    "mode": mode,
                    "request_offset": action.offset,
                    "next_offset": next_offset,
                    "has_new_output": has_new_output,
                    "dropped_chars": dropped_chars,
                    **empty_hints,
                },
                "progress": bool(has_new_output),
            }
            return obs
        except Exception as e:
            logger.error("Error reading terminal %s: %s", action.session_id, e)
            return ErrorObservation(f"Failed to read terminal: {e}")

    def _resolve_path(self, path: str, working_dir: str) -> str:
        """Resolve a relative or absolute path to an absolute path with security validation."""
        return self._resolve_workspace_file_path(path, working_dir)

    def _handle_aci_file_read(self, action: FileReadAction) -> FileReadObservation:
        """Handle file reading using the FILE_EDITOR implementation."""
        result_str, _ = execute_file_editor(
            self.file_editor,
            command="read_file",
            path=action.path,
            view_range=action.view_range,
        )
        return FileReadObservation(
            content=result_str, path=action.path, impl_source=FileReadSource.FILE_EDITOR
        )

    async def read(self, action: FileReadAction) -> Observation:
        """Read a file and return its content as an observation."""
        bash_session = self.session_manager.get_session("default")
        if bash_session is None:
            return ErrorObservation("Default shell session not initialized")

        # Check for binary files (skip probe if path is missing — avoids noisy errors)
        if os.path.isfile(action.path) and is_binary(action.path):
            return ErrorObservation("ERROR_BINARY_FILE")

        # Handle FILE_EDITOR implementation
        if action.impl_source == FileReadSource.FILE_EDITOR:
            return self._handle_aci_file_read(action)

        # Resolve file path
        working_dir = bash_session.cwd
        try:
            filepath = self._resolve_workspace_file_path(action.path, working_dir)
        except PermissionError:
            return ErrorObservation(
                f"You're not allowed to access this path: {action.path}. You can only access paths inside the workspace."
            )

        try:
            # Handle different file types
            if filepath.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
                return read_image_file(filepath)
            if filepath.lower().endswith(".pdf"):
                return read_pdf_file(filepath)
            if filepath.lower().endswith((".mp4", ".webm", ".ogg")):
                return read_video_file(filepath)
            return read_text_file(filepath, action)
        except Exception:
            return handle_file_read_errors(filepath, working_dir)

    async def write(self, action: FileWriteAction) -> Observation:
        """Write a file and return an observation."""
        bash_session = self.session_manager.get_session("default")
        if bash_session is None:
            return ErrorObservation("Default shell session not initialized")

        working_dir = bash_session.cwd
        try:
            filepath = self._resolve_workspace_file_path(action.path, working_dir)
        except PermissionError as e:
            return ErrorObservation(f"Permission error on {action.path}: {e}")

        try:
            ensure_directory_exists(filepath)
            file_exists = os.path.exists(filepath)
            error_obs = write_file_content(filepath, action, file_exists)
            if error_obs:
                return error_obs
            return FileWriteObservation(
                content=f"Wrote file: {action.path}",
                path=action.path,
            )
        except Exception as e:
            logger.error("Error writing file %s: %s", action.path, e, exc_info=True)
            return ErrorObservation(f"Failed to write file {action.path}: {e}")

    def _edit_try_directory_view(
        self, filepath: str, path_for_obs: str, action: FileEditAction
    ) -> Observation | None:
        """Return directory view observation if path is dir and viewable; else None."""
        try:
            if os.path.isdir(filepath) and (
                action.command == "read_file" or not action.command
            ):
                return handle_directory_view(filepath, path_for_obs)
        except Exception:
            pass
        return None

    def _edit_via_file_editor(self, action: FileEditAction) -> Observation:
        """Execute FILE_EDITOR-style edit and return observation."""
        command = action.command or "write"
        enable_lint = self._is_auto_lint_enabled()
        result_str, (old_content, new_content) = execute_file_editor(
            self.file_editor,
            command=command,
            path=action.path,
            file_text=action.file_text,
            view_range=action.view_range,
            old_str=action.old_str,
            new_str=action.new_str,
            insert_line=action.insert_line,
            start_line=getattr(action, "start_line", None),
            end_line=getattr(action, "end_line", None),
            normalize_ws=action.normalize_ws,
            enable_linting=enable_lint,
            edit_mode=getattr(action, "edit_mode", None),
            format_kind=getattr(action, "format_kind", None),
            format_op=getattr(action, "format_op", None),
            format_path=getattr(action, "format_path", None),
            format_value=getattr(action, "format_value", None),
            anchor_type=getattr(action, "anchor_type", None),
            anchor_value=getattr(action, "anchor_value", None),
            anchor_occurrence=getattr(action, "anchor_occurrence", None),
            section_action=getattr(action, "section_action", None),
            section_content=getattr(action, "section_content", None),
            patch_text=getattr(action, "patch_text", None),
            expected_hash=getattr(action, "expected_hash", None),
            expected_file_hash=getattr(action, "expected_file_hash", None),
        )
        if result_str.startswith("ERROR:"):
            return ErrorObservation(result_str)
        max_chars = get_max_edit_observation_chars()
        result_str = truncate_large_text(result_str, max_chars, label="edit")
        # P1-B: Append a short unified diff to the observation so the LLM can
        # confirm what changed without a follow-up view call.
        if (
            old_content is not None
            and new_content is not None
            and command != "read_file"
        ):
            try:
                diff = get_diff(old_content, new_content, action.path)
                if diff:
                    result_str = result_str + "\n\n[EDIT_DIFF]\n" + diff
            except Exception:
                pass  # diff is a nice-to-have; never block the observation
        # Blast Radius Hook
        # If the edit is successful and there's new content, check symbol references
        result_str = self._append_blast_radius_warning(
            result_str,
            command=command,
            action_path=action.path,
            new_content=new_content,
        )

        return FileEditObservation(
            content=result_str,
            path=action.path,
            prev_exist=old_content is not None,
            old_content=old_content,
            new_content=new_content,
            impl_source=FileEditSource.FILE_EDITOR,
        )

    def _edit_via_llm(self, action: FileEditAction) -> Observation:
        """Execute LLM-based range edit and return observation."""
        command = action.command or "edit"
        enable_lint = self._is_auto_lint_enabled()
        result_str, (old_content, new_content) = execute_file_editor(
            self.file_editor,
            command=command,
            path=action.path,
            file_text=action.content,
            start_line=action.start,
            end_line=action.end,
            enable_linting=enable_lint,
        )
        if result_str.startswith("ERROR:"):
            return ErrorObservation(result_str)
        if old_content and new_content:
            diff = get_diff(old_content, new_content, action.path)

            diff = self._append_blast_radius_warning(
                diff,
                command=command,
                action_path=action.path,
                new_content=new_content,
            )

            return FileEditObservation(
                content=diff,
                path=action.path,
                prev_exist=old_content is not None,
                old_content=old_content,
                new_content=new_content,
                impl_source=FileEditSource.LLM_BASED_EDIT,
            )
        result_str = self._append_blast_radius_warning(
            result_str,
            command=command,
            action_path=action.path,
            new_content=new_content,
        )

        return FileEditObservation(
            content=result_str,
            path=action.path,
            prev_exist=old_content is not None,
            old_content=old_content,
            new_content=new_content,
            impl_source=FileEditSource.LLM_BASED_EDIT,
        )

    def _append_blast_radius_warning(
        self,
        base_content: str,
        *,
        command: str,
        action_path: str,
        new_content: str | None,
    ) -> str:
        """Append blast-radius warning text when available, without interrupting edits."""
        if command == "read_file" or new_content is None:
            return base_content
        try:
            from backend.utils.blast_radius import check_blast_radius_from_code

            warning = check_blast_radius_from_code(action_path, new_content)
            if warning:
                return base_content + warning
        except Exception as e:
            logger.debug("Failed to check blast radius: %s", e)
        return base_content

    def _is_auto_lint_enabled(self) -> bool:
        """Return whether auto-lint should run after editor mutations."""
        return os.environ.get("ENABLE_AUTO_LINT", "").lower() in {
            "1",
            "true",
            "yes",
        }

    async def edit(self, action: FileEditAction) -> Observation:
        """Edit a file (FILE_EDITOR or LLM-based) and return an observation."""
        bash_session = self.session_manager.get_session("default")
        if bash_session is None:
            return ErrorObservation("Default shell session not initialized")
        working_dir = bash_session.cwd
        try:
            filepath = self._resolve_workspace_file_path(action.path, working_dir)
        except PermissionError:
            return ErrorObservation(
                f"You're not allowed to access this path: {action.path}. You can only access paths inside the workspace."
            )

        dir_view = self._edit_try_directory_view(filepath, action.path, action)
        if dir_view is not None:
            return dir_view

        if action.impl_source == FileEditSource.FILE_EDITOR or action.command:
            return self._edit_via_file_editor(action)

        try:
            return self._edit_via_llm(action)
        except Exception as e:
            logger.error("Error editing file %s: %s", action.path, e, exc_info=True)
            return ErrorObservation(f"Failed to edit file {action.path}: {e}")

    async def call_tool_mcp(self, action: MCPAction) -> Observation:
        """Execute an MCP tool call using App's MCP client integration."""
        try:
            from backend.core.config.config_loader import load_app_config
            from backend.core.config.mcp_config import _filter_windows_stdio_servers
            from backend.integrations.mcp.mcp_utils import (
                call_tool_mcp,
                create_mcps,
            )

            if self._mcp_clients is None:
                # Prefer injected config (e.g. in-process runtime), fallback to load.
                cfg = self._mcp_config
                if cfg is None:
                    cfg = load_app_config().mcp

                servers = getattr(cfg, "servers", []) or []
                # Apply the same allowlist-based Windows filter used during
                # config loading so that explicitly-allowed stdio servers are
                # kept while unknown ones are still blocked.
                servers = _filter_windows_stdio_servers(list(servers))
                self._mcp_servers_resolved = list(servers)
                self._mcp_clients = await create_mcps(servers)
                from backend.integrations.mcp.mcp_tool_aliases import (
                    prepare_mcp_tool_exposed_names,
                )

                _reserved = (
                    getattr(cfg, "mcp_exposed_name_reserved", None) or frozenset()
                )
                prepare_mcp_tool_exposed_names(self._mcp_clients, set(_reserved))

            observation = await call_tool_mcp(
                self._mcp_clients,
                action,
                configured_servers=self._mcp_servers_resolved,
            )  # type: ignore[arg-type]

            # Apply truncation to large MCP outputs
            if hasattr(observation, "content") and isinstance(observation.content, str):
                max_chars = (
                    get_max_edit_observation_chars()
                )  # Reuse same limit or similar logic
                observation.content = truncate_large_text(
                    observation.content, max_chars, label=f"MCP:{action.name}"
                )

            return observation
        except Exception as e:
            logger.error("MCP call failed for %s: %s", action.name, e, exc_info=True)
            return ErrorObservation(
                content=(
                    f"MCP tool call failed for '{action.name}': {type(e).__name__}: {e}. "
                    "Use non-MCP tools as a fallback or check MCP configuration."
                )
            )

    async def lsp_query(self, action: LspQueryAction) -> Observation:
        """Execute an LSP query using the lsp_client."""
        from backend.utils.lsp_client import LspClient

        start = time.perf_counter()
        try:
            client = LspClient()
            result = client.query(
                command=action.command,
                file=action.file,
                line=action.line,
                column=action.column,
                symbol=getattr(action, "symbol", ""),
            )

            latency_ms = int((time.perf_counter() - start) * 1000)
            obs = LspQueryObservation(
                content=result.format_text(action.command),
                available=bool(result.available),
            )
            obs.tool_result = {
                "tool": "code_intelligence",
                "command": action.command,
                "file": action.file,
                "latency_ms": latency_ms,
                "available": bool(result.available),
                "has_error": bool(result.error),
            }
            logger.info(
                "LSP query completed: command=%s available=%s latency_ms=%d",
                action.command,
                bool(result.available),
                latency_ms,
            )
            return obs
        except Exception as e:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.error("LSP query failed: %s", e, exc_info=True)
            err = ErrorObservation(
                f"LSP query failed: {e}. Check if python-lsp-server is installed."
            )
            err.tool_result = {
                "tool": "code_intelligence",
                "command": action.command,
                "file": action.file,
                "latency_ms": latency_ms,
                "available": False,
                "has_error": True,
            }
            return err

    async def signal_progress(self, action: SignalProgressAction) -> Observation:
        """Handle a progress signal from the agent."""
        # The actual decrementation happens in SessionOrchestrator. We just return ack here.
        return SignalProgressObservation(acknowledged=True)

    async def browser_tool(self, action: BrowserToolAction) -> Observation:
        """Run native browser-use commands (in-process; optional dependency)."""
        if not self.enable_browser:
            return ErrorObservation(
                content=(
                    "ERROR: Browser runtime is disabled for this session "
                    "(enable_browser=false on the runtime)."
                )
            )
        from backend.execution.browser import GrintaNativeBrowser

        if self._native_browser is None:
            self._native_browser = GrintaNativeBrowser(self.downloads_directory)
        ctl: GrintaNativeBrowser = self._native_browser
        return await ctl.execute(action.command, action.params)

    def close(self) -> None:
        """Clean up resources owned by the in-process executor."""
        if self._mcp_clients:
            _clients = list(self._mcp_clients)
            self._mcp_clients = None

            async def _disconnect_mcp() -> None:
                for c in _clients:
                    try:
                        await c.disconnect()
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        logger.debug("MCP executor disconnect: %s", exc, exc_info=True)
                    await asyncio.sleep(0)

            try:
                from backend.core.constants import GENERAL_TIMEOUT
                from backend.utils.async_utils import call_async_from_sync

                call_async_from_sync(_disconnect_mcp, GENERAL_TIMEOUT)
            except Exception as exc:
                logger.debug("MCP disconnect during RuntimeExecutor.close: %s", exc)

        try:
            self.debug_manager.close_all()
        except Exception:
            pass

        try:
            self.session_manager.close_all()
        except Exception:
            pass
        try:
            self.memory_monitor.stop_monitoring()
        except Exception:
            pass

        if self.browser is not None:
            try:
                self.browser.close()
            except Exception:
                pass
            self.browser = None
        if self._native_browser is not None:
            try:
                from backend.core.constants import GENERAL_TIMEOUT
                from backend.utils.async_utils import call_async_from_sync

                call_async_from_sync(self._native_browser.shutdown, GENERAL_TIMEOUT)
            except Exception:
                pass
            self._native_browser = None


# Initialize global variables for client and proxies
client: RuntimeExecutor | None = None
mcp_proxy_manager: MCPProxyManager | None = None


# Initializers for routes
def get_client() -> RuntimeExecutor:
    if client is None:
        logger.warning("Runtime executor not initialized")
        raise ReferenceError("Runtime executor not initialized")
    return client


def get_mcp_proxy() -> MCPProxyManager | None:
    return mcp_proxy_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage FastAPI application lifespan."""
    global initialization_task
    logger.info("Starting server (prewarm check for local models)...")

    # Run prewarm check synchronously (in a thread) so we fail startup fast if
    # prebundled model artifacts are missing.
    try:
        from backend.utils.model_prewarm import (
            ensure_models_available,
            get_default_models_to_prewarm,
        )

        prebundle_env = os.getenv("PREBUNDLED_MODELS", "")
        models = get_default_models_to_prewarm()
        if prebundle_env:
            models += [m.strip() for m in prebundle_env.split(",") if m.strip()]
        # snapshot_download is blocking; run it in a thread to avoid blocking the loop.
        await asyncio.to_thread(ensure_models_available, models, True)
        logger.info("Prewarm check succeeded: required models available locally")
    except Exception as e:
        logger.error("Prewarm model check failed: %s", e, exc_info=True)
        # Raise to prevent yielding readiness — startup should fail fast when artifacts are missing.
        raise

    # Start initialization in background task
    initialize_background = globals().get("_initialize_background")
    if not callable(initialize_background):

        async def _noop_initialize(_: FastAPI) -> None:
            return

        initialize_background = _noop_initialize
    initialization_task = asyncio.create_task(initialize_background(app))

    # Yield after prewarm so server can start accepting requests
    yield

    # Cleanup on shutdown
    logger.info("Shutting down...")
    global mcp_proxy_manager, client
    if initialization_task and not initialization_task.done():
        logger.info("Cancelling initialization task...")
        initialization_task.cancel()
        try:
            await initialization_task
        except asyncio.CancelledError:
            pass

    logger.info("Shutting down MCP Proxy Manager...")
    if mcp_proxy_manager:
        try:
            # MCP Proxy doesn't have a close/cleanup method?
            # It handles cleanup via destructors usually or just stops.
            # Original code just deleted it.
            # We'll check if it has a cleanup method?
            pass
        except Exception:
            pass

    logger.info("Closing RuntimeExecutor...")
    if client:
        try:
            client.close()
            logger.info("RuntimeExecutor closed successfully.")
        except Exception as e:
            logger.error("Error closing RuntimeExecutor: %s", e, exc_info=True)

    logger.info("Shutdown complete.")


app = FastAPI(lifespan=lifespan)
register_exception_handlers(app)
register_routes(app, get_client, get_mcp_proxy)


def get_uvicorn_json_log_config() -> dict[str, Any]:
    """Return a minimal uvicorn log configuration."""
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(levelname)s %(asctime)s %(name)s %(message)s",
                "use_colors": None,
            },
            "access": {
                "format": "%(levelname)s %(asctime)s %(message)s",
                "use_colors": None,
            },
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "default",
            }
        },
        "loggers": {
            "uvicorn": {"handlers": ["default"], "level": "INFO"},
            "uvicorn.error": {"handlers": ["default"], "level": "INFO"},
            "uvicorn.access": {"handlers": ["default"], "level": "INFO"},
        },
    }


if __name__ == "__main__":
    logger.warning("Starting Action Execution Server")
    parser = argparse.ArgumentParser()
    parser.add_argument("port", type=int, help="Port to listen on")
    parser.add_argument("--working-dir", type=str, help="Working directory")
    parser.add_argument("--plugins", type=str, help="Plugins to initialize", nargs="+")
    parser.add_argument("--username", type=str, help="User to run as", default="app")
    parser.add_argument("--user-id", type=int, help="User ID to run as", default=1000)
    parser.add_argument(
        "--enable-browser",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable the browser environment",
    )
    args = parser.parse_args()

    logger.info("Starting file viewer server")
    _file_viewer_port = find_available_tcp_port(
        min_port=args.port + 1, max_port=min(args.port + 1024, 65535)
    )
    server_url, _ = start_file_viewer_server(port=_file_viewer_port)
    logger.info("File viewer server started at %s", server_url)

    plugins_to_load: list[Plugin] = []
    if args.plugins:
        for plugin in args.plugins:
            if plugin not in ALL_PLUGINS:
                msg = f"Plugin {plugin} not found"
                raise ValueError(msg)
            plugins_to_load.append(ALL_PLUGINS[plugin]())

    client: RuntimeExecutor | None = None  # type: ignore[no-redef]
    mcp_proxy_manager: MCPProxyManager | None = None  # type: ignore[no-redef]
    initialization_task: asyncio.Task | None = None
    initialization_error: Exception | None = None

    async def _initialize_background(app: FastAPI):
        """Initialize RuntimeExecutor and MCP Proxy Manager in the background."""
        global client, mcp_proxy_manager, initialization_error
        try:
            logger.info("Initializing RuntimeExecutor...")
            from backend.core.config.config_loader import load_app_config

            client = RuntimeExecutor(
                plugins_to_load,
                work_dir=args.working_dir,
                username=args.username,
                user_id=args.user_id,
                enable_browser=args.enable_browser,
                security_config=load_app_config().security,
            )
            logger.info(
                "RuntimeExecutor instance created. Starting async initialization..."
            )

            init_timeout = int(os.environ.get("ACTION_EXECUTOR_INIT_TIMEOUT", "300"))
            try:
                await asyncio.wait_for(client.ainit(), timeout=init_timeout)
                logger.info("RuntimeExecutor initialized successfully.")
            except TimeoutError as exc:
                error_msg = f"RuntimeExecutor initialization timed out after {init_timeout} seconds."
                logger.error(error_msg)
                initialization_error = RuntimeError(error_msg)
                raise initialization_error from exc

            is_windows = sys.platform == "win32"
            if is_windows:
                logger.info("Skipping MCP Proxy initialization on Windows")
                mcp_proxy_manager = None
            else:
                logger.info("Initializing MCP Proxy Manager...")
                mcp_proxy_manager = MCPProxyManager(
                    auth_enabled=False,
                    api_key=None,
                    logger_level=logger.getEffectiveLevel(),
                )
                app_config = load_app_config()
                mcp_proxy_manager.initialize(app_config.mcp.servers)
                allowed_origins = ["*"]
                try:
                    await mcp_proxy_manager.mount_to_app(app, allowed_origins)
                    logger.info("MCP Proxy Manager mounted to app successfully")
                except Exception as e:
                    logger.error("Error mounting MCP Proxy: %s", e, exc_info=True)
                    logger.warning("Continuing without MCP Proxy mounting")

        except Exception as e:
            logger.error(
                "Failed to initialize RuntimeExecutor: %s",
                e,
                exc_info=True,
            )
            initialization_error = e

    logger.debug("Starting action execution API on port %d", args.port)
    log_config = None
    if os.getenv("LOG_JSON", "0") in ("1", "true", "True"):
        log_config = get_uvicorn_json_log_config()
    server_host = os.getenv("ACTION_EXECUTION_HOST", "127.0.0.1")
    server = Server(
        Config(
            app,
            host=server_host,
            port=args.port,
            log_config=log_config,
            use_colors=False,
        )
    )
    server.run()
