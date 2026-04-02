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
from typing import TYPE_CHECKING, Any, cast

from binaryornot.check import is_binary
from fastapi import FastAPI
from pydantic import BaseModel
from uvicorn import run

from backend.core.enums import FileEditSource, FileReadSource
from backend.core.logger import app_logger as logger
from backend.execution.browser_init import init_browser
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
    FileEditAction,
    FileReadAction,
    FileWriteAction,
)
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
from backend.utils.async_utils import call_sync_from_async
from backend.utils.regex_limits import try_compile_user_regex

if TYPE_CHECKING:
    from backend.execution.browser.browser_env import BrowserEnv


WORKSPACE_VIRTUAL_ROOT = '/workspace'
_WORKSPACE_TOKEN_RE = re.compile(r'/workspace(?=/|$)')
_ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*m')

# Note: Import is deferred to avoid executing windows_bash.py on non-Windows platforms
if sys.platform == 'win32':
    pass


def _module_attr(name: str):
    """Return the latest attribute from this module for monkeypatched helpers."""
    return getattr(sys.modules[__name__], name)


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
        self.enable_browser = enable_browser
        self.browser: BrowserEnv | None = None

        self.tool_registry = tool_registry

        # Initialize SessionManager — uses the same work_dir as FileEditor
        self.session_manager = SessionManager(
            work_dir=work_dir,
            username=username,
            tool_registry=tool_registry,
            max_memory_gb=None,  # Will be updated in ainit
        )

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
        self.downloads_directory = os.path.join(work_dir, 'downloads')
        # Ensure downloads directory exists
        os.makedirs(self.downloads_directory, exist_ok=True)

        # Track repeated identical command failures to nudge strategy pivots
        # before the circuit breaker is the only recovery mechanism.
        self._last_cmd_failure_signature: tuple[str, int, str] | None = None
        self._same_cmd_failure_count: int = 0

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

    async def _init_browser_async(self) -> None:
        """Initialize the browser asynchronously."""
        self.browser = await init_browser(self.enable_browser)

    async def _ensure_browser_ready(self) -> None:
        """Ensure the browser is ready for use."""
        if self.browser:
            if not self.browser.check_alive(timeout=5):
                self.browser.init_browser()

    def _create_bash_session(self, cwd: str | None = None):
        """Create a shell session appropriate for the current platform."""
        # Delegated to SessionManager
        return self.session_manager.create_session(cwd=cwd)

    async def hard_kill(self) -> None:
        """Best-effort immediate termination of processes started by this runtime."""
        self.session_manager.close_all()
        if self.browser:
            self.browser.close()

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
            logger.info('Step 1/5: Initializing default shell session...')
            self.session_manager.create_session(session_id='default')

            # Step 2: Initialize browser in background if enabled
            if self.enable_browser:
                logger.info('Step 2/5: Starting browser initialization (background)...')
                # We don't await here to parallelize startup, but _init_browser_async handles it
                # Logic in constructor sets up background task usually?
                # or await here? original code had `asyncio.create_task` in `main`?
                # Original `ainit` (Step 238) didn't show task creation.
                # But `_init_browser_async` was called.
                # Let's check original `main` logic... no `ainit` called there?
                # Ah, `lifespan` called `_initialize_background` which called `client.ainit()`.
                # So we should await here for serial initialization or fire task.
                # Original `ainit` (Step 238) didn't show code.
                # I'll fire task to not block if browser is slow?
                # But subsequent steps might depend on browser? No.
                # However `_init_browser_async` logs success.
                # I'll await it if it's fast, or start it.
                # Ideally start it.
                self._browser_init_task = asyncio.create_task(
                    self._init_browser_async()
                )
            else:
                logger.info('Step 2/5: Browser disabled, skipping...')

            # Step 3: Initialize plugins
            logger.info('Step 3/5: Initializing plugins...')
            self.plugins = await init_plugins(self.plugins_to_load, self.username)

            # Step 4: Initialize bash commands/aliases
            logger.info('Step 4/5: Setting up bash commands...')
            self._init_bash_commands()

            # Step 5: Start memory monitoring
            logger.info('Step 5/5: Starting memory monitor...')
            self.memory_monitor.start_monitoring()

            logger.info('All initialization steps completed successfully')
            self._initialized = True
        except Exception as e:
            logger.error(
                'RuntimeExecutor initialization failed at step: %s',
                e,
                exc_info=True,
            )
            # Ensure we clean up if initialization fails
            await self.hard_kill()
            raise

    def initialized(self) -> bool:
        """Check if action execution server has completed initialization."""
        return self._initialized

    def _init_bash_commands(self):
        # We need to set up some aliases and functions in bash for better UX
        bash_session = self.session_manager.get_session('default')
        assert bash_session is not None

        # Init git configuration
        bash_session.execute(
            CmdRunAction(
                command=f'git config --global user.name "{self.username}" && git config --global user.email "{self.username}@example.com"',
            )
        )

        # Set up env_check alias for diagnosing environment issues after
        # cascading failures.  Shows Python version, key packages, disk
        # usage, and memory stats in one command.
        bash_session.execute(
            CmdRunAction(
                command=(
                    "alias env_check='"
                    'echo "=== PYTHON ===" && python3 --version 2>/dev/null || python --version 2>/dev/null && '
                    'echo "=== KEY PACKAGES ===" && pip list --format=freeze 2>/dev/null | head -30 && '
                    'echo "=== DISK ===" && df -h . 2>/dev/null && '
                    'echo "=== MEMORY ===" && free -h 2>/dev/null || vm_stat 2>/dev/null; '
                    "true'"
                ),
            )
        )

        # Initialize plugins commands
        for plugin in self.plugins.values():
            init_cmds = plugin.get_init_bash_commands()
            if init_cmds:
                for cmd in init_cmds:
                    bash_session.execute(CmdRunAction(command=cmd))

    async def run_action(self, action) -> Observation:
        """Execute any action through action execution server."""
        async with self.lock:
            action_type = action.action
            obs = await getattr(self, action_type)(action)

        # Replace the real workspace temp path with /workspace in all
        # observation text so the LLM's perspective stays consistent.
        if hasattr(obs, 'content') and isinstance(obs.content, str):
            obs.content = self._denormalize_obs_text(obs.content)
        if hasattr(obs, 'path') and isinstance(obs.path, str):
            obs.path = self._denormalize_obs_text(obs.path)
        if hasattr(obs, 'message') and isinstance(obs.message, str):
            try:
                obs.message = self._denormalize_obs_text(obs.message)
            except AttributeError:
                pass  # message is read-only (e.g. MCPObservation); content already denormalized
        return obs

    def _normalize_workspace_path(self, path: str) -> str:
        """Translate /workspace/... virtual paths to the actual workspace directory.

        When running outside a container the real workspace is a temp directory
        (e.g. /tmp/app_workspace_<sid>_... on Linux/macOS or under %%TEMP%%
        on Windows).  The LLM always uses the /workspace virtual prefix, so
        this method strips it and returns the corresponding absolute path
        inside the real workspace root.
        """
        norm = path.replace('\\', '/')
        if norm == WORKSPACE_VIRTUAL_ROOT:
            return self._initial_cwd
        workspace_prefix = f'{WORKSPACE_VIRTUAL_ROOT}/'
        if norm.startswith(workspace_prefix):
            rel = norm[len(workspace_prefix) :]
            return os.path.join(self._initial_cwd, rel)
        return path

    def _rewrite_workspace_tokens(self, text: str) -> str:
        """Replace virtual /workspace path tokens with the actual workspace path."""
        if not text or WORKSPACE_VIRTUAL_ROOT not in text:
            return text
        workspace_root = self._initial_cwd.replace('\\', '/')
        return _WORKSPACE_TOKEN_RE.sub(workspace_root, text)

    def _denormalize_obs_text(self, text: str) -> str:
        """Replace the real workspace temp path with /workspace in observation text.

        This keeps the LLM's perspective consistent: it always sees /workspace
        paths regardless of the underlying temp directory location.
        Without this, the LLM sees path mismatches (it sends /workspace/foo but
        gets back the real app_workspace temp path) and loops trying to
        reconcile them.

        Also strips ANSI color codes so terminal output is clean for the LLM.
        """
        if not text:
            return text
        # Strip ANSI escape codes from PowerShell / terminal output.
        text = _ANSI_ESCAPE_RE.sub('', text)
        if not self._initial_cwd:
            return text
        # Replace both forward-slash and backslash variants of the temp path.
        ws = self._initial_cwd.replace('\\', '/')
        ws_back = self._initial_cwd.replace('/', '\\')
        text = text.replace(ws_back, '/workspace')
        text = text.replace(ws, '/workspace')
        # Also replace any mixed-slash variant: normalize then replace.
        text = re.sub(
            re.escape(self._initial_cwd).replace('\\\\', r'[/\\]'),
            WORKSPACE_VIRTUAL_ROOT,
            text,
        )
        return text

    def _should_rewrite_python3_to_python(self) -> bool:
        """Return True only when running in Windows PowerShell mode.

        On Windows with Git Bash available, commands should remain bash-native,
        and python3 should not be rewritten.
        """
        if sys.platform != 'win32':
            return False

        tool_registry = getattr(self.session_manager, 'tool_registry', None)
        if tool_registry is not None:
            has_bash = bool(getattr(tool_registry, 'has_bash', False))
            if has_bash:
                return False
            has_powershell = bool(getattr(tool_registry, 'has_powershell', False))
            if has_powershell:
                return True

        # Fallback when tool registry details are unavailable in tests/mocks.
        default_session = self.session_manager.get_session('default')
        session_name = (
            default_session.__class__.__name__.lower() if default_session else ''
        )
        return 'powershell' in session_name

    @staticmethod
    def _extract_failure_signature(content: str) -> str:
        """Build a compact error signature for repeated-failure detection."""
        if not content:
            return ''
        lines = [line.strip().lower() for line in content.splitlines() if line.strip()]
        if not lines:
            return ''
        # Prefer the tail where shell errors usually appear.
        tail = ' | '.join(lines[-3:])
        return tail[:300]

    def _workspace_root(self) -> Path:
        return Path(self._initial_cwd).resolve()

    def _is_hardened_local(self) -> bool:
        return (
            getattr(self.security_config, 'execution_profile', 'standard')
            == 'hardened_local'
        )

    def _validate_interactive_session_scope(
        self, session_id: str, session: Any
    ) -> ErrorObservation | None:
        if not self._is_hardened_local():
            return None

        current_cwd = Path(getattr(session, 'cwd', self._initial_cwd)).resolve()
        if path_is_within_workspace(current_cwd, self._workspace_root()):
            return None

        self.session_manager.close_session(session_id)
        return ErrorObservation(
            content=(
                'Interactive terminal session closed by hardened_local policy: '
                f'session cwd escaped the workspace. Session: {session_id} | cwd={current_cwd}'
            )
        )

    def _predict_interactive_cwd_change(
        self, command: str, current_cwd: Path
    ) -> tuple[Path | None, str | None]:
        tokens = tokenize_command(command)
        if not tokens:
            return (None, None)

        op = tokens[0].strip().lower()
        if op not in {'cd', 'pushd', 'set-location', 'sl'}:
            return (None, None)

        if len(tokens) < 2 or tokens[1].strip() in {
            '',
            '~',
            '$HOME',
            '%USERPROFILE%',
            '-',
        }:
            return (
                None,
                'Action blocked by hardened_local policy: interactive directory changes must target an explicit path inside the workspace.',
            )

        target = Path(self._rewrite_workspace_tokens(tokens[1]))
        predicted = (
            target.resolve()
            if target.is_absolute()
            else (current_cwd / target).resolve()
        )
        if not path_is_within_workspace(predicted, self._workspace_root()):
            return (
                None,
                'Action blocked by hardened_local policy: interactive terminal sessions cannot change directory outside the workspace. '
                f'Requested cwd: {predicted}',
            )
        return (predicted, None)

    def _evaluate_interactive_terminal_command(
        self, command: str, current_cwd: Path
    ) -> tuple[Path | None, ErrorObservation | None]:
        if not self._is_hardened_local():
            return (None, None)

        stripped = command.strip()
        if not stripped:
            return (None, None)

        if any(separator in stripped for separator in ('\n', '&&', ';', '||')):
            return (
                None,
                ErrorObservation(
                    content=(
                        'Action blocked by hardened_local policy: interactive terminal input cannot contain chained or multiline commands.'
                    )
                ),
            )

        block_message = evaluate_hardened_local_command_policy(
            command=stripped,
            security_config=self.security_config,
            workspace_root=self._workspace_root(),
            requested_cwd=str(current_cwd),
            base_cwd=str(current_cwd),
            is_background=stripped.endswith('&'),
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
        if not self._is_hardened_local():
            return None

        workspace_root = self._workspace_root()
        effective_cwd = self._resolve_effective_cwd(requested_cwd, base_cwd)
        try:
            effective_cwd.relative_to(workspace_root)
        except ValueError:
            return ErrorObservation(
                content=(
                    'Action blocked by hardened_local policy: command execution must stay inside the workspace. '
                    f'Command: {command} | cwd={effective_cwd}'
                )
            )
        return None

    def _resolve_workspace_file_path(self, path: str, working_dir: str) -> str:
        return str(resolve_workspace_path(path, working_dir, self._initial_cwd))

    def _maybe_mark_repeated_cmd_failure(
        self, action: CmdRunAction, observation: CmdOutputObservation
    ) -> None:
        """Annotate repeated identical command failures to force a strategy pivot."""
        exit_code = int(getattr(observation.metadata, 'exit_code', 0) or 0)
        if exit_code == 0:
            self._last_cmd_failure_signature = None
            self._same_cmd_failure_count = 0
            return

        # Annotate fatal signals with actionable guidance so the LLM knows
        # *why* the process died instead of blindly retrying.
        if exit_code == 137:
            observation.content += (
                '\n\n[OOM_KILLED] The command was killed by the kernel (exit 137 — '
                'out of memory or SIGKILL). Reduce memory usage, process data in '
                'smaller chunks, or increase available memory before retrying.'
            )
        elif exit_code == 139:
            observation.content += (
                '\n\n[SEGFAULT] The command crashed with a segmentation fault '
                '(exit 139 — SIGSEGV). This indicates a bug in the program, not '
                'a configuration issue. Inspect the code for memory errors.'
            )

        signature = (
            action.command.strip(),
            exit_code,
            self._extract_failure_signature(observation.content),
        )
        if signature == self._last_cmd_failure_signature:
            self._same_cmd_failure_count += 1
        else:
            self._last_cmd_failure_signature = signature
            self._same_cmd_failure_count = 1

        if self._same_cmd_failure_count >= 2:
            observation.content += (
                '\n\n[REPEATED_COMMAND_FAILURE] '
                f'The same command failed {self._same_cmd_failure_count} times with the same error signature. '
                'Do NOT retry unchanged. Pivot now: inspect available tools/interpreters, '
                'adjust environment, or choose a different command/tool.'
            )

    # Patterns for common environment errors → (regex, tag, guidance).
    _ENV_ERROR_PATTERNS: list[tuple[str, str, str]] = [
        (
            r"ModuleNotFoundError:\s*No module named ['\"]?(\S+?)['\"]?",
            '[MISSING_MODULE]',
            'Install with: pip install {match}',
        ),
        (
            r'ImportError:\s*cannot import name',
            '[IMPORT_ERROR]',
            'Check that the correct package version is installed and the name is spelled correctly.',
        ),
        (
            r'(\S+):\s*command not found',
            '[MISSING_TOOL]',
            'Install with: apt-get install {match} (or check PATH)',
        ),
        (
            r'No space left on device',
            '[DISK_FULL]',
            'Free disk space before retrying. Check usage with: df -h',
        ),
        (
            r'Permission denied',
            '[PERMISSION_ERROR]',
            'Check file ownership/permissions. You may need chmod or to run as a different user.',
        ),
    ]

    def _annotate_environment_errors(self, observation: CmdOutputObservation) -> None:
        """Detect environment-level errors and append actionable guidance.

        Scans the observation content for common environment failures
        (missing modules, missing tools, disk full, permission denied)
        and appends a tagged annotation so the LLM gets explicit guidance
        instead of having to infer the root cause.
        """
        content = observation.content
        if not content:
            return

        exit_code = int(getattr(observation.metadata, 'exit_code', 0) or 0)
        if exit_code == 0:
            return

        for pattern, tag, guidance_template in self._ENV_ERROR_PATTERNS:
            m = re.search(pattern, content)
            if m:
                # Use the first capture group as {match} if available.
                match_text = m.group(1) if m.lastindex and m.lastindex >= 1 else ''
                guidance = guidance_template.format(match=match_text)
                observation.content += f'\n\n{tag} {guidance}'
                # Only annotate the first matching pattern to avoid noise.
                return

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
            # Replace /workspace virtual path with the real workspace directory.
            # Outside containers /workspace doesn't point at the temp workspace.
            if action.command:
                action.command = self._rewrite_workspace_tokens(action.command)

            # Rewrite python3->python only in Windows PowerShell mode.
            if self._should_rewrite_python3_to_python() and action.command:
                action.command = re.sub(r'\bpython3\b', 'python', action.command)

            default_session = self.session_manager.get_session('default')
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

            self._maybe_mark_repeated_cmd_failure(action, observation)

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
                    observation, self.session_manager.get_session('default')
                )

            return observation
        except Exception as e:
            logger.error('Error running command: %s', e)
            return ErrorObservation(str(e))

    async def _run_background_cmd(self, action: CmdRunAction) -> TerminalObservation:
        """Start a background command in a new session.

        Creates a dedicated session, writes the command, waits briefly for
        initial output, and returns a TerminalObservation with the session ID
        for later checking.
        """
        session_id = f'bg-{uuid.uuid4().hex[:8]}'
        default_session = self.session_manager.get_session('default')
        cwd = str(
            self._resolve_effective_cwd(
                action.cwd,
                (default_session.cwd if default_session else None) or self._initial_cwd,
            )
        )
        session = self.session_manager.create_session(session_id=session_id, cwd=cwd)
        logger.debug(
            'Starting background task in session %s: %s', session_id, action.command
        )
        session.write_input(action.command + '\n')
        await asyncio.sleep(0.5)
        content = session.read_output()
        return TerminalObservation(
            session_id=session_id,
            content=f'Background task started. Session ID: {session_id}\nInitial Output:\n{content}',
        )

    async def _run_foreground_cmd(
        self, action: CmdRunAction
    ) -> CmdOutputObservation | ErrorObservation:
        """Execute command in foreground (static or default session).

        Routes to _run_static_cmd for isolated execution, or uses the default
        session for normal foreground commands.
        """
        if action.is_static:
            return await self._run_static_cmd(action)
        bash_session = self.session_manager.get_session('default')
        if bash_session is None:
            return ErrorObservation('Default shell session not initialized')
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
        temp_id = f'static-{uuid.uuid4().hex[:8]}'
        default_session = self.session_manager.get_session('default')
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
        result = '\n'.join(filtered)
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
        logger.info('🚀 Adding detected server to observation extras: %s', detected.url)
        if not hasattr(observation, 'extras'):
            observation.extras = {}  # type: ignore[attr-defined]
        observation.extras['server_ready'] = {  # type: ignore[attr-defined]
            'port': detected.port,
            'url': detected.url,
            'protocol': detected.protocol,
            'health_status': detected.health_status,
        }

    async def terminal_run(self, action: TerminalRunAction) -> Observation:
        """Start a new interactive terminal session."""
        try:
            # Generate a unique session ID
            session_id = f'term-{uuid.uuid4().hex[:8]}'

            # Determine working directory
            # Prefer provided CWD -> default session CWD -> initial CWD
            default_session = self.session_manager.get_session('default')
            cwd = action.cwd
            if not cwd and default_session:
                cwd = default_session.cwd
            if not cwd:
                cwd = self._initial_cwd

            cwd_error = self._validate_workspace_scoped_cwd(
                action.command or '<interactive terminal>',
                action.cwd,
                cwd,
            )
            if cwd_error is not None:
                return cwd_error

            cwd = str(self._resolve_effective_cwd(action.cwd, cwd))

            # Create the new session via manager
            session = self.session_manager.create_session(
                session_id=session_id, cwd=cwd
            )

            if action.command:
                action.command = self._rewrite_workspace_tokens(action.command)
                predicted_cwd, policy_error = (
                    self._evaluate_interactive_terminal_command(
                        action.command,
                        Path(cwd).resolve(),
                    )
                )
                if policy_error is not None:
                    self.session_manager.close_session(session_id)
                    return policy_error
                # Send the initial command if provided
                logger.debug(
                    'Running initial command in terminal %s: %s',
                    session_id,
                    action.command,
                )
                # Attempt to write input. If underlying session doesn't support input,
                # it will log a warning but not crash.
                session.write_input(action.command + '\n')
                if predicted_cwd is not None and hasattr(session, '_cwd'):
                    session._cwd = str(predicted_cwd)  # type: ignore[attr-defined]

            # Return initial output
            content = session.read_output()
            return TerminalObservation(session_id=session_id, content=content)

        except Exception as e:
            logger.error('Error starting terminal session: %s', e, exc_info=True)
            return ErrorObservation(f'Failed to start terminal: {e}')

    async def terminal_input(self, action: TerminalInputAction) -> Observation:
        """Send input to an interactive terminal session."""
        session = self.session_manager.get_session(action.session_id)
        if not session:
            return ErrorObservation(f'Terminal session {action.session_id} not found.')

        scope_error = self._validate_interactive_session_scope(
            action.session_id, session
        )
        if scope_error is not None:
            return scope_error

        try:
            write_content = self._rewrite_workspace_tokens(action.input)
            # Add newline if not a control sequence, unless user explicitly handles it?
            # TerminalInputAction usually implies raw input.
            # If user types "ls", they usually mean "ls\n".
            # Control sequences are separate.

            predicted_cwd: Path | None = None
            if not action.is_control:
                predicted_cwd, policy_error = (
                    self._evaluate_interactive_terminal_command(
                        write_content,
                        Path(getattr(session, 'cwd', self._initial_cwd)).resolve(),
                    )
                )
                if policy_error is not None:
                    return policy_error

            session.write_input(write_content, is_control=action.is_control)
            if predicted_cwd is not None and hasattr(session, '_cwd'):
                session._cwd = str(predicted_cwd)  # type: ignore[attr-defined]
            # Wait briefly for output to appear
            await asyncio.sleep(0.2)
            content = session.read_output()
            return TerminalObservation(session_id=action.session_id, content=content)
        except Exception as e:
            logger.error('Error sending input to terminal %s: %s', action.session_id, e)
            return ErrorObservation(f'Failed to send input: {e}')

    async def terminal_read(self, action: TerminalReadAction) -> Observation:
        """Read the output of an interactive terminal session."""
        session = self.session_manager.get_session(action.session_id)
        if not session:
            return ErrorObservation(
                f'Terminal session {action.session_id} not found or closed.'
            )

        scope_error = self._validate_interactive_session_scope(
            action.session_id, session
        )
        if scope_error is not None:
            return scope_error

        try:
            content = session.read_output()
            return TerminalObservation(session_id=action.session_id, content=content)
        except Exception as e:
            logger.error('Error reading terminal %s: %s', action.session_id, e)
            return ErrorObservation(f'Failed to read terminal: {e}')

    def _resolve_path(self, path: str, working_dir: str) -> str:
        """Resolve a relative or absolute path to an absolute path with security validation."""
        return self._resolve_workspace_file_path(path, working_dir)

    def _handle_aci_file_read(self, action: FileReadAction) -> FileReadObservation:
        """Handle file reading using the FILE_EDITOR implementation."""
        result_str, _ = execute_file_editor(
            self.file_editor,
            command='view_file',
            path=action.path,
            view_range=action.view_range,
        )
        return FileReadObservation(
            content=result_str, path=action.path, impl_source=FileReadSource.FILE_EDITOR
        )

    async def read(self, action: FileReadAction) -> Observation:
        """Read a file and return its content as an observation."""
        bash_session = self.session_manager.get_session('default')
        if bash_session is None:
            return ErrorObservation('Default shell session not initialized')

        # Translate /workspace/ virtual paths to the actual workspace directory.
        action.path = self._normalize_workspace_path(action.path)

        # Check for binary files (skip probe if path is missing — avoids noisy errors)
        if os.path.isfile(action.path) and is_binary(action.path):
            return ErrorObservation('ERROR_BINARY_FILE')

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
            if filepath.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                return read_image_file(filepath)
            if filepath.lower().endswith('.pdf'):
                return read_pdf_file(filepath)
            if filepath.lower().endswith(('.mp4', '.webm', '.ogg')):
                return read_video_file(filepath)
            return read_text_file(filepath, action)
        except Exception:
            return handle_file_read_errors(filepath, working_dir)

    async def write(self, action: FileWriteAction) -> Observation:
        """Write a file and return an observation."""
        bash_session = self.session_manager.get_session('default')
        if bash_session is None:
            return ErrorObservation('Default shell session not initialized')

        # Translate /workspace/ virtual paths to the actual workspace directory.
        action.path = self._normalize_workspace_path(action.path)

        working_dir = bash_session.cwd
        try:
            filepath = self._resolve_workspace_file_path(action.path, working_dir)
        except PermissionError as e:
            return ErrorObservation(f'Permission error on {action.path}: {e}')

        try:
            ensure_directory_exists(filepath)
            file_exists = os.path.exists(filepath)
            error_obs = write_file_content(filepath, action, file_exists)
            if error_obs:
                return error_obs
            return FileWriteObservation(
                content=f'Wrote file: {action.path}',
                path=action.path,
            )
        except Exception as e:
            logger.error('Error writing file %s: %s', action.path, e, exc_info=True)
            return ErrorObservation(f'Failed to write file {action.path}: {e}')

    def _edit_try_directory_view(
        self, filepath: str, path_for_obs: str, action: FileEditAction
    ) -> Observation | None:
        """Return directory view observation if path is dir and viewable; else None."""
        try:
            if os.path.isdir(filepath) and (
                action.command == 'view_file' or not action.command
            ):
                return handle_directory_view(filepath, path_for_obs)
        except Exception:
            pass
        return None

    def _edit_via_file_editor(self, action: FileEditAction) -> Observation:
        """Execute FILE_EDITOR-style edit and return observation."""
        command = action.command or 'write'
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
            enable_linting=enable_lint,
        )
        if result_str.startswith('ERROR:'):
            return ErrorObservation(result_str)
        max_chars = get_max_edit_observation_chars()
        result_str = truncate_large_text(result_str, max_chars, label='edit')
        # P1-B: Append a short unified diff to the observation so the LLM can
        # confirm what changed without a follow-up view call.
        if (
            old_content is not None
            and new_content is not None
            and command != 'view_file'
        ):
            try:
                diff = get_diff(old_content, new_content, action.path)
                if diff:
                    result_str = result_str + '\n\n[EDIT_DIFF]\n' + diff
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
        command = action.command or 'edit'
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
        if result_str.startswith('ERROR:'):
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
        if command == 'view_file' or new_content is None:
            return base_content
        try:
            from backend.utils.blast_radius import check_blast_radius_from_code

            warning = check_blast_radius_from_code(action_path, new_content)
            if warning:
                return base_content + warning
        except Exception as e:
            logger.debug('Failed to check blast radius: %s', e)
        return base_content

    def _is_auto_lint_enabled(self) -> bool:
        """Return whether auto-lint should run after editor mutations."""
        return os.environ.get('ENABLE_AUTO_LINT', '').lower() in {
            '1',
            'true',
            'yes',
        }

    async def edit(self, action: FileEditAction) -> Observation:
        """Edit a file (FILE_EDITOR or LLM-based) and return an observation."""
        bash_session = self.session_manager.get_session('default')
        if bash_session is None:
            return ErrorObservation('Default shell session not initialized')
        # Translate /workspace/ virtual paths to the actual workspace directory.
        action.path = self._normalize_workspace_path(action.path)
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
            logger.error('Error editing file %s: %s', action.path, e, exc_info=True)
            return ErrorObservation(f'Failed to edit file {action.path}: {e}')

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

                servers = getattr(cfg, 'servers', []) or []
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
                    getattr(cfg, 'mcp_exposed_name_reserved', None) or frozenset()
                )
                prepare_mcp_tool_exposed_names(self._mcp_clients, set(_reserved))

            observation = await call_tool_mcp(
                self._mcp_clients,
                action,
                configured_servers=self._mcp_servers_resolved,
            )  # type: ignore[arg-type]

            # Apply truncation to large MCP outputs
            if hasattr(observation, 'content') and isinstance(observation.content, str):
                max_chars = (
                    get_max_edit_observation_chars()
                )  # Reuse same limit or similar logic
                observation.content = truncate_large_text(
                    observation.content, max_chars, label=f'MCP:{action.name}'
                )

            return observation
        except Exception as e:
            logger.error('MCP call failed for %s: %s', action.name, e, exc_info=True)
            return ErrorObservation(
                content=(
                    f"MCP tool call failed for '{action.name}': {type(e).__name__}: {e}. "
                    'Use non-MCP tools as a fallback or check MCP configuration.'
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
                symbol=getattr(action, 'symbol', ''),
            )

            latency_ms = int((time.perf_counter() - start) * 1000)
            obs = LspQueryObservation(
                content=result.format_text(action.command),
                available=bool(result.available),
            )
            obs.tool_result = {
                'tool': 'lsp_query',
                'command': action.command,
                'file': action.file,
                'latency_ms': latency_ms,
                'available': bool(result.available),
                'has_error': bool(result.error),
            }
            logger.info(
                'LSP query completed: command=%s available=%s latency_ms=%d',
                action.command,
                bool(result.available),
                latency_ms,
            )
            return obs
        except Exception as e:
            latency_ms = int((time.perf_counter() - start) * 1000)
            logger.error('LSP query failed: %s', e, exc_info=True)
            err = ErrorObservation(
                f'LSP query failed: {e}. Check if python-lsp-server is installed.'
            )
            err.tool_result = {
                'tool': 'lsp_query',
                'command': action.command,
                'file': action.file,
                'latency_ms': latency_ms,
                'available': False,
                'has_error': True,
            }
            return err

    async def signal_progress(self, action: SignalProgressAction) -> Observation:
        """Handle a progress signal from the agent."""
        # The actual decrementation happens in SessionOrchestrator. We just return ack here.
        return SignalProgressObservation(acknowledged=True)

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
                    except BaseExceptionGroup as eg:
                        logger.debug(
                            'MCP executor disconnect (exception group): %s', eg
                        )
                    except Exception as e:
                        logger.debug('MCP executor disconnect: %s', e, exc_info=True)
                    await asyncio.sleep(0)

            try:
                from backend.core.constants import GENERAL_TIMEOUT
                from backend.utils.async_utils import call_async_from_sync

                call_async_from_sync(_disconnect_mcp, GENERAL_TIMEOUT)
            except Exception as exc:
                logger.debug('MCP disconnect during RuntimeExecutor.close: %s', exc)

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


# Initialize global variables for client and proxies
client: RuntimeExecutor | None = None
mcp_proxy_manager: MCPProxyManager | None = None


# Initializers for routes
def get_client() -> RuntimeExecutor:
    if client is None:
        logger.warning('Runtime executor not initialized')
        raise ReferenceError('Runtime executor not initialized')
    return client


def get_mcp_proxy() -> MCPProxyManager | None:
    return mcp_proxy_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage FastAPI application lifespan."""
    global initialization_task
    logger.info('Starting server (initialization will run in background)...')

    # Start initialization in background task
    initialize_background = globals().get('_initialize_background')
    if not callable(initialize_background):

        async def _noop_initialize(_: FastAPI) -> None:
            return

        initialize_background = _noop_initialize
    initialization_task = asyncio.create_task(initialize_background(app))

    # Yield immediately so server can start accepting requests
    yield

    # Cleanup on shutdown
    logger.info('Shutting down...')
    global mcp_proxy_manager, client
    if initialization_task and not initialization_task.done():
        logger.info('Cancelling initialization task...')
        initialization_task.cancel()
        try:
            await initialization_task
        except asyncio.CancelledError:
            pass

    logger.info('Shutting down MCP Proxy Manager...')
    if mcp_proxy_manager:
        try:
            # MCP Proxy doesn't have a close/cleanup method?
            # It handles cleanup via destructors usually or just stops.
            # Original code just deleted it.
            # We'll check if it has a cleanup method?
            pass
        except Exception:
            pass

    logger.info('Closing RuntimeExecutor...')
    if client:
        try:
            client.close()
            logger.info('RuntimeExecutor closed successfully.')
        except Exception as e:
            logger.error('Error closing RuntimeExecutor: %s', e, exc_info=True)

    logger.info('Shutdown complete.')


app = FastAPI(lifespan=lifespan)
register_exception_handlers(app)
register_routes(app, get_client, get_mcp_proxy)


def get_uvicorn_json_log_config() -> dict[str, Any]:
    """Return a minimal uvicorn log configuration."""
    return {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {
            'default': {
                'format': '%(levelname)s %(asctime)s %(name)s %(message)s',
                'use_colors': None,
            },
            'access': {
                'format': '%(levelname)s %(asctime)s %(message)s',
                'use_colors': None,
            },
        },
        'handlers': {
            'default': {
                'class': 'logging.StreamHandler',
                'formatter': 'default',
            }
        },
        'loggers': {
            'uvicorn': {'handlers': ['default'], 'level': 'INFO'},
            'uvicorn.error': {'handlers': ['default'], 'level': 'INFO'},
            'uvicorn.access': {'handlers': ['default'], 'level': 'INFO'},
        },
    }


if __name__ == '__main__':
    logger.warning('Starting Action Execution Server')
    parser = argparse.ArgumentParser()
    parser.add_argument('port', type=int, help='Port to listen on')
    parser.add_argument('--working-dir', type=str, help='Working directory')
    parser.add_argument('--plugins', type=str, help='Plugins to initialize', nargs='+')
    parser.add_argument('--username', type=str, help='User to run as', default='app')
    parser.add_argument('--user-id', type=int, help='User ID to run as', default=1000)
    parser.add_argument(
        '--enable-browser',
        action=argparse.BooleanOptionalAction,
        default=True,
        help='Enable the browser environment',
    )
    args = parser.parse_args()

    logger.info('Starting file viewer server')
    _file_viewer_port = find_available_tcp_port(
        min_port=args.port + 1, max_port=min(args.port + 1024, 65535)
    )
    server_url, _ = start_file_viewer_server(port=_file_viewer_port)
    logger.info('File viewer server started at %s', server_url)

    plugins_to_load: list[Plugin] = []
    if args.plugins:
        for plugin in args.plugins:
            if plugin not in ALL_PLUGINS:
                msg = f'Plugin {plugin} not found'
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
            logger.info('Initializing RuntimeExecutor...')
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
                'RuntimeExecutor instance created. Starting async initialization...'
            )

            init_timeout = int(os.environ.get('ACTION_EXECUTOR_INIT_TIMEOUT', '300'))
            try:
                await asyncio.wait_for(client.ainit(), timeout=init_timeout)
                logger.info('RuntimeExecutor initialized successfully.')
            except TimeoutError as exc:
                error_msg = f'RuntimeExecutor initialization timed out after {init_timeout} seconds.'
                logger.error(error_msg)
                initialization_error = RuntimeError(error_msg)
                raise initialization_error from exc

            is_windows = sys.platform == 'win32'
            if is_windows:
                logger.info('Skipping MCP Proxy initialization on Windows')
                mcp_proxy_manager = None
            else:
                logger.info('Initializing MCP Proxy Manager...')
                mcp_proxy_manager = MCPProxyManager(
                    auth_enabled=False,
                    api_key=None,
                    logger_level=logger.getEffectiveLevel(),
                )
                app_config = load_app_config()
                mcp_proxy_manager.initialize(app_config.mcp.servers)
                allowed_origins = ['*']
                try:
                    await mcp_proxy_manager.mount_to_app(app, allowed_origins)
                    logger.info('MCP Proxy Manager mounted to app successfully')
                except Exception as e:
                    logger.error('Error mounting MCP Proxy: %s', e, exc_info=True)
                    logger.warning('Continuing without MCP Proxy mounting')

        except Exception as e:
            logger.error(
                'Failed to initialize RuntimeExecutor: %s',
                e,
                exc_info=True,
            )
            initialization_error = e

    logger.debug('Starting action execution API on port %d', args.port)
    log_config = None
    if os.getenv('LOG_JSON', '0') in ('1', 'true', 'True'):
        log_config = get_uvicorn_json_log_config()
    run(app, host='0.0.0.0', port=args.port, log_config=log_config, use_colors=False)
