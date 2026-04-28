"""In-process LocalRuntime - runs RuntimeExecutor directly without subprocess/HTTP.

This is a simplified version that eliminates the complexity of subprocess management
and HTTP communication for desktop applications that only need local runtime.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.core.config.security_config import SecurityConfig
from backend.core.constants import BROWSER_TOOL_SYNC_TIMEOUT_SECONDS
from backend.core.enums import RuntimeStatus
from backend.core.errors import AgentRuntimeDisconnectedError
from backend.core.logger import app_logger as logger
from backend.core.os_capabilities import OS_CAPS
from backend.execution.action_execution_server import RuntimeExecutor
from backend.execution.capabilities import detect_capabilities
from backend.execution.drivers.action_execution.action_execution_client import (
    ActionExecutionClient,
)
from backend.execution.executor_protocol import RuntimeExecutorProtocol
from backend.execution.plugins import ALL_PLUGINS, Plugin
from backend.ledger.action import (
    CmdRunAction,
    DebuggerAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
    MCPAction,
)
from backend.ledger.action.code_nav import LspQueryAction
from backend.ledger.action.terminal import (
    TerminalInputAction,
    TerminalReadAction,
    TerminalRunAction,
)
from backend.ledger.observation import Observation
from backend.security.analyzer import SecurityAnalyzer
from backend.utils.async_utils import call_async_from_sync

if TYPE_CHECKING:
    from backend.core.config import AppConfig
    from backend.core.provider_types import ProviderTokenType
    from backend.execution.plugins import PluginRequirement
    from backend.inference.llm_registry import LLMRegistry
    from backend.ledger import EventStream


def get_user_info() -> tuple[int, str | None]:
    """Get user ID and username in a cross-platform way."""
    username = os.getenv('USER') or os.getenv('USERNAME')
    uid_getter = getattr(os, 'getuid', None)
    if uid_getter and callable(uid_getter):
        return (uid_getter(), username)  # pylint: disable=not-callable
    return (0, username)


class _PersistentAsyncLoopRunner:
    """Run coroutines on a dedicated long-lived event loop thread.

    Browser sessions maintain internal loop-affine objects (CDP session, tasks).
    Reusing them across short-lived loops can hang. This runner keeps one loop
    alive for all browser tool calls in the LocalRuntime lifecycle.
    """

    def __init__(self, name: str = 'local-runtime-browser-loop') -> None:
        self._name = name
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._run_forever,
            name=self._name,
            daemon=True,
        )
        self._thread.start()

    def _run_forever(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(
        self, corofn: Callable[..., Any], timeout: float, *args: Any, **kwargs: Any
    ) -> Any:
        coro = corofn(*args, **kwargs)
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise TimeoutError(
                f'call_async_from_sync timed out after {timeout}s for '
                f'{getattr(corofn, "__name__", corofn)}'
            ) from exc

    def close(self, timeout: float = 2.0) -> None:
        """Stop and close the dedicated loop thread."""
        if self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=timeout)
        if not self._thread.is_alive():
            self._loop.close()


class LocalRuntimeInProcess(ActionExecutionClient):
    """In-process local runtime that runs RuntimeExecutor directly.

    This eliminates subprocess and HTTP overhead by running RuntimeExecutor
    directly in the same process. Ideal for desktop applications.
    """

    def __init__(
        self,
        config: AppConfig,
        event_stream: EventStream,
        llm_registry: LLMRegistry,
        sid: str = 'default',
        plugins: list[PluginRequirement] | None = None,
        env_vars: dict[str, str] | None = None,
        status_callback: Callable[[str, RuntimeStatus, str], None] | None = None,
        attach_to_existing: bool = False,
        headless_mode: bool = True,
        user_id: str | None = None,
        vcs_provider_tokens: ProviderTokenType | None = None,
        project_root: str | None = None,
    ) -> None:
        """Initialize in-process local runtime."""
        # Initialize parent
        safe_event_stream = event_stream if hasattr(event_stream, 'subscribe') else None
        self.is_windows = OS_CAPS.is_windows

        # Initialize tooling and security
        self._init_tooling_and_platform()

        self.config = config
        self._original_config = config

        # Ensure config compatibility and user info
        self._sanitize_config()
        self._user_id, self._username = get_user_info()

        logger.info(
            'Initializing In-Process LocalRuntime. User ID: %s. Username: %s.',
            self._user_id,
            self._username,
        )

        # Setup workspace
        self._temp_workspace: str | None = project_root
        self._owns_workspace = project_root is None
        self.status_callback = status_callback

        # RuntimeExecutor instance (created in connect()). Typed against the
        # protocol so this driver does not depend on the concrete class at
        # runtime — any executor satisfying the protocol works.
        self._executor: RuntimeExecutorProtocol | None = None
        self._browser_loop_runner: _PersistentAsyncLoopRunner | None = None

        # Apply startup env vars
        if self.config.runtime_config.runtime_startup_env_vars:
            os.environ |= self.config.runtime_config.runtime_startup_env_vars

        # Store plugins for later initialization
        self._plugin_requirements = plugins or []

        super().__init__(
            config,
            safe_event_stream,
            llm_registry,
            sid,
            plugins,
            env_vars,
            status_callback,
            attach_to_existing,
            headless_mode,
            user_id,
            vcs_provider_tokens,
            project_root=project_root,
        )

    async def connect(self) -> None:
        """Initialize RuntimeExecutor in-process."""
        import time

        start_time = time.time()

        self.set_runtime_status(RuntimeStatus.STARTING_RUNTIME)

        # Create workspace directory
        self._setup_workspace_directory()

        # Convert plugin requirements to plugin instances
        plugins_to_load: list[Plugin] = []
        for plugin_req in self._plugin_requirements:
            if plugin_req.name in ALL_PLUGINS:
                plugins_to_load.append(ALL_PLUGINS[plugin_req.name]())
            else:
                logger.warning('Plugin %s not found, skipping', plugin_req.name)

        # Create RuntimeExecutor directly (no subprocess!)
        logger.info('Creating RuntimeExecutor in-process...')
        if self._temp_workspace is None:
            self._setup_workspace_directory()
        if self._temp_workspace is None:
            raise ValueError('Workspace directory must be set')
        work_dir = self._temp_workspace
        os.makedirs(work_dir, exist_ok=True)

        self._executor = RuntimeExecutor(
            plugins_to_load=plugins_to_load,
            work_dir=work_dir,
            username=self._username or 'app',
            user_id=self._user_id,
            enable_browser=self.config.enable_browser,
            tool_registry=self._tool_registry,  # Pass ToolRegistry for cross-platform support
            mcp_config=getattr(self.config, 'mcp', None),
            security_config=self.config.security,
        )

        # Initialize RuntimeExecutor (this sets up bash, plugins, etc.)
        logger.info('Initializing RuntimeExecutor...')
        await self._executor.ainit()

        self.set_runtime_status(RuntimeStatus.READY)
        self._runtime_initialized = True

        # Populate the capability matrix once at startup
        self.capabilities = detect_capabilities(
            enable_browser=self.config.enable_browser,
            mcp_config=getattr(self.config, 'mcp', None),
        )
        if self.capabilities.missing_tools:
            logger.warning(
                'Missing expected tools: %s',
                ', '.join(self.capabilities.missing_tools),
            )

        elapsed = time.time() - start_time
        logger.info('🚀 In-process runtime ready in %.2fs', elapsed)

    def _setup_workspace_directory(self) -> None:
        """Create temporary workspace directory."""
        if self._temp_workspace is None:
            # If project_root is provided in init, use it; otherwise create temp
            base = getattr(self, 'project_root', None)
            self._owns_workspace = not bool(base)
            if base:
                self._temp_workspace = base
                os.makedirs(base, exist_ok=True)
            else:
                self._temp_workspace = tempfile.mkdtemp(
                    prefix=f'app_workspace_{self.sid}_'
                )
            self.config.workspace_mount_path_in_runtime = self._temp_workspace
            logger.info('Using workspace: %s', self._temp_workspace)
            if self._owns_workspace:
                # Temporary workspaces need a disposable git repo for change tracking.
                import subprocess

                try:
                    subprocess.run(
                        ['git', 'init'],
                        cwd=self._temp_workspace,
                        check=True,
                        capture_output=True,
                    )
                except Exception as e:
                    logger.warning('Failed to init git in temp workspace: %s', e)
            return

        self.config.workspace_mount_path_in_runtime = self._temp_workspace

    async def execute_action(self, action: Any) -> Observation:
        """Execute action directly via RuntimeExecutor."""
        if not self._runtime_initialized or self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')

        return await self._executor.run_action(action)

    def hard_kill(self) -> None:
        """Best-effort immediate termination of processes started by this runtime."""
        if self._executor is None:
            return
        try:
            call_async_from_sync(self._executor.hard_kill, 5.0)
        except Exception:
            logger.debug('LocalRuntimeInProcess hard_kill failed', exc_info=True)

    def run(self, action: CmdRunAction) -> Observation:
        """Execute command via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        # Use the action's own timeout (set by _set_action_timeout) plus a
        # buffer for thread-pool scheduling, instead of the fixed 15s which
        # was too short for commands with larger timeouts.
        timeout = (action.timeout or 120) + 10
        return call_async_from_sync(self._executor.run, timeout, action)

    def read(self, action: FileReadAction) -> Observation:
        """Read file via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return call_async_from_sync(self._executor.read, 15.0, action)

    def write(self, action: FileWriteAction) -> Observation:
        """Write file via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return call_async_from_sync(self._executor.write, 15.0, action)

    def edit(self, action: FileEditAction) -> Observation:
        """Edit file via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return call_async_from_sync(self._executor.edit, 15.0, action)

    def terminal_run(self, action: TerminalRunAction) -> Observation:
        """Start an interactive terminal session via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return call_async_from_sync(self._executor.terminal_run, 130.0, action)

    def terminal_input(self, action: TerminalInputAction) -> Observation:
        """Send input to a terminal session via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return call_async_from_sync(self._executor.terminal_input, 30.0, action)

    def terminal_read(self, action: TerminalReadAction) -> Observation:
        """Read terminal output via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return call_async_from_sync(self._executor.terminal_read, 30.0, action)

    def debugger(self, action: DebuggerAction) -> Observation:
        """Execute a debugger action via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return call_async_from_sync(self._executor.debugger, 60.0, action)

    def lsp_query(self, action: LspQueryAction) -> Observation:
        """Execute LSP query via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return call_async_from_sync(self._executor.lsp_query, 15.0, action)

    def browser_tool(self, action: Any) -> Observation:
        """Native browser-use tool via RuntimeExecutor."""
        from backend.ledger.action.browser_tool import BrowserToolAction

        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        if not isinstance(action, BrowserToolAction):
            raise TypeError('expected BrowserToolAction')
        try:
            if self._browser_loop_runner is None:
                self._browser_loop_runner = _PersistentAsyncLoopRunner()
            return self._browser_loop_runner.submit(
                self._executor.browser_tool,
                BROWSER_TOOL_SYNC_TIMEOUT_SECONDS,
                action,
            )
        except TimeoutError as exc:
            sub = getattr(action, 'command', '') or ''
            raise TimeoutError(
                f'call_async_from_sync timed out after {BROWSER_TOOL_SYNC_TIMEOUT_SECONDS}s '
                f'for browser_tool (subcommand={sub!r}). '
                'Typical causes: Chromium first-time download inside browser.start(), '
                'a slow CDP navigate, or async teardown blocked — use GRINTA_BROWSER_TRACE=1, '
                'CALL_ASYNC_LOOP_SHUTDOWN_WAIT_SEC, CALL_ASYNC_LOOP_FINALIZE_WAIT_SEC; '
                'run `uvx browser-use install` once in a normal shell if cold start is slow.'
            ) from exc

    def list_files(self, path: str | None = None, recursive: bool = False) -> list[str]:
        """List files in the specified path."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')

        # Resolve path
        full_path = self._resolve_list_files_path(path)

        # Check if path exists and is a directory (handle Windows edge cases)
        try:
            if not os.path.exists(full_path):
                return []
            # On Windows, os.path.isdir() can raise for invalid paths
            if not os.path.isdir(full_path):
                return []
        except (OSError, ValueError) as e:
            # Path is invalid or inaccessible
            logger.warning('Invalid path for list_files: %s - %s', full_path, e)
            return []

        # Get sorted directory entries
        try:
            entries = os.listdir(full_path)
        except (OSError, NotADirectoryError) as e:
            # Path is not a directory or cannot be listed
            logger.warning('Cannot list directory %s: %s', full_path, e)
            return []

        directories, files = self._process_directory_entries(
            full_path, entries, path or '', recursive
        )

        directories.sort(key=lambda s: s.lower())
        files.sort(key=lambda s: s.lower())

        return directories + files

    def _resolve_list_files_path(self, path: str | None) -> str:
        """Resolve the path for file listing."""
        assert self._executor is not None, 'Runtime not initialized'
        if not path:
            return self._executor.initial_cwd

        try:
            from backend.core.type_safety.path_validation import SafePath

            safe_path = SafePath.validate(
                path,
                workspace_root=self._executor.initial_cwd,
                must_be_relative=True,
            )
            return str(safe_path.path)
        except Exception:
            # Fallback
            if os.path.isabs(path):
                return path
            return os.path.join(self._executor.initial_cwd, path)

    def _process_directory_entries(
        self, full_path: str, entries: list[str], path: str, recursive: bool
    ) -> tuple[list[str], list[str]]:
        """Process directory entries and return (directories, files)."""
        directories = []
        files = []

        for entry in entries:
            entry_relative = entry.lstrip('/').split('/')[-1]
            full_entry_path = os.path.join(full_path, entry_relative)

            try:
                if os.path.exists(full_entry_path):
                    if os.path.isdir(full_entry_path):
                        directories.append(entry.rstrip('/') + '/')
                        if recursive:
                            sub_path = os.path.join(path, entry) if path else entry
                            sub_files = self.list_files(sub_path, recursive=True)
                            files.extend([f'{entry}/{f}' for f in sub_files])
                    else:
                        files.append(entry)
            except (OSError, ValueError):
                continue
        return directories, files

    def copy_to(
        self, host_src: str, runtime_dest: str, recursive: bool = False
    ) -> None:
        """Copy file from host to runtime."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        # For in-process, just use shutil
        import shutil

        if os.path.isdir(host_src):
            if recursive:
                shutil.copytree(host_src, runtime_dest, dirs_exist_ok=True)
            else:
                raise ValueError('Cannot copy directory without recursive=True')
        else:
            os.makedirs(os.path.dirname(runtime_dest), exist_ok=True)
            shutil.copy2(host_src, runtime_dest)

    def copy_from(self, path: str) -> Any:
        """Copy file from runtime to host."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        # For in-process, file is already accessible
        return Path(path)  # pylint: disable=redefined-outer-name,reimported

    def get_mcp_config(self, extra_servers: list[Any] | None = None) -> Any:
        """Get MCP configuration."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        # MCP is handled by RuntimeExecutor if available
        return self.config.mcp if hasattr(self.config, 'mcp') else None

    async def call_tool_mcp(self, action: MCPAction) -> Observation:
        """Call MCP tool via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        # RuntimeExecutor handles MCP through run_action
        return await self._executor.run_action(action)

    def close(self) -> None:
        """Clean up runtime resources."""
        if self._browser_loop_runner is not None:
            try:
                self._browser_loop_runner.close()
            except Exception:
                logger.debug(
                    'LocalRuntimeInProcess browser loop close failed', exc_info=True
                )
            self._browser_loop_runner = None
        if self._executor:
            # RuntimeExecutor cleanup (this is synchronous)
            if hasattr(self._executor, 'close'):
                self._executor.close()
            self._executor = None

        # Wait a bit for processes to release file handles before removing workspace
        import time

        time.sleep(0.5)  # Brief wait for Windows file handle release

        # Clean up workspace with retry logic, but never remove a user workspace.
        if (
            self._owns_workspace
            and self._temp_workspace
            and os.path.exists(self._temp_workspace)
        ):
            import shutil

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    shutil.rmtree(self._temp_workspace)
                    break
                except (PermissionError, OSError) as e:
                    if attempt < max_retries - 1:
                        time.sleep(1.0)  # Wait before retry
                        continue
                    # Last attempt failed, log warning but don't raise
                    try:
                        logger.warning(
                            'Failed to remove workspace %s after %s attempts: %s',
                            self._temp_workspace,
                            max_retries,
                            e,
                        )
                    except Exception:
                        # Logger might be closed, ignore
                        pass

        super().close()

    @property
    def workspace_root(self) -> Path:
        """Return the workspace root path."""
        return (
            Path(self._temp_workspace) if self._temp_workspace else Path('.')
        )  # pylint: disable=redefined-outer-name,reimported

    @workspace_root.setter
    def workspace_root(self, value: Path) -> None:
        self._temp_workspace = str(value)

    @property
    def runtime_initialized(self) -> bool:
        """Check if runtime is initialized."""
        return self._runtime_initialized

    @runtime_initialized.setter
    def runtime_initialized(self, value: bool) -> None:
        self._runtime_initialized = bool(value)

    def _init_tooling_and_platform(self) -> None:
        """Initialize ToolRegistry and platform-specific tooling."""
        from backend.execution.utils.tool_registry import ToolRegistry

        logger.info('Initializing ToolRegistry for cross-platform support...')
        self._tool_registry = ToolRegistry()

        # Initialize Security Analyzer for default safety
        self._security_analyzer = SecurityAnalyzer()

        # Check for required tools
        if not self._tool_registry.has_git:
            logger.error(
                'Git is required but not found. Please install Git from: https://git-scm.com/downloads'
            )

        # Log platform-specific warnings
        if self.is_windows:
            logger.info(
                'Running on Windows with %s shell',
                self._tool_registry.shell_type,
            )
        else:
            if not self._tool_registry.has_tmux:
                logger.warning(
                    'tmux not found. Using simple subprocess-based Bash session. '
                    'Install tmux for better command management: sudo apt install tmux'
                )

    def _sanitize_config(self) -> None:
        """Sanitize configuration and ensure compatibility."""
        security_cfg = getattr(self.config, 'security', None)
        if not isinstance(security_cfg, SecurityConfig):
            self.config.security = SecurityConfig()
