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
from backend.core.constants import (
    TERMINAL_RUN_EXECUTION_TIMEOUT_SECONDS,
    TOOL_BRIDGE_TIMEOUT_BUFFER,
    TOOL_BRIDGE_TIMEOUT_FILE_IO,
    TOOL_BRIDGE_TIMEOUT_READ_ONLY,
    TOOL_BRIDGE_TIMEOUT_TERMINAL_IO,
    TOOL_BRIDGE_TIMEOUT_TERMINAL_RUN,
)
from backend.core.enums import RuntimeStatus
from backend.core.errors import AgentRuntimeDisconnectedError
from backend.core.logging.logger import app_logger as logger
from backend.core.os_capabilities import OS_CAPS
from backend.core.timeouts.timeout_policy import (
    browser_tool_sync_bridge_timeout_seconds,
    cmd_run_sync_bridge_timeout_seconds,
)
from backend.execution.capabilities import detect_capabilities
from backend.execution.drivers.action_execution.action_execution_client import (
    ActionExecutionClient,
)
from backend.execution.executor_protocol import RuntimeExecutorProtocol
from backend.execution.plugins import ALL_PLUGINS, Plugin
from backend.execution.server.action_execution_server import RuntimeExecutor
from backend.ledger.action import (
    CmdRunAction,
    DebuggerAction,
    FileEditAction,
    FileReadAction,
    MCPAction,
)
from backend.ledger.action.code_nav import LspQueryAction
from backend.ledger.action.search import (
    AnalyzeProjectStructureAction,
    FindSymbolsAction,
    GlobAction,
    GrepAction,
)
from backend.ledger.action.terminal import (
    TerminalCloseAction,
    TerminalInputAction,
    TerminalListAction,
    TerminalReadAction,
    TerminalRunAction,
    TerminalWaitAction,
)
from backend.ledger.observation import ErrorObservation, Observation
from backend.security.analyzer import SecurityAnalyzer
from backend.utils.async_helpers.async_utils import call_async_from_sync

if TYPE_CHECKING:
    from backend.core.config import AppConfig
    from backend.core.providers.provider_models import ProviderTokenType
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

    def cancel_pending(self) -> None:
        """Cancel pending tasks on the dedicated loop after a bridge timeout."""
        if self._loop.is_closed():
            return

        async def _cancel_pending() -> None:
            current = asyncio.current_task()
            tasks = [
                task
                for task in asyncio.all_tasks(self._loop)
                if task is not current and not task.done()
            ]
            if not tasks:
                return
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        future = asyncio.run_coroutine_threadsafe(_cancel_pending(), self._loop)
        try:
            future.result(timeout=2.0)
        except Exception:
            logger.debug(
                'Persistent browser loop pending-task cancellation did not finish',
                exc_info=True,
            )

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
        self.project_root = project_root
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
        if self._executor is not None:
            try:
                call_async_from_sync(self._executor.hard_kill, 5.0)
            except Exception:
                logger.debug('LocalRuntimeInProcess hard_kill failed', exc_info=True)

        # ``hard_kill`` is a destructive lifecycle boundary. Keep runtime state
        # honest so subsequent tool calls fail fast via the reconnect path
        # instead of running against a partially torn-down executor.
        self._runtime_initialized = False
        self._executor = None

    def run(self, action: CmdRunAction) -> Observation:
        """Execute command via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        # Align with ``CommandTimeoutMixin`` / pending floors (see
        # :func:`backend.core.timeout_policy.cmd_run_sync_bridge_timeout_seconds`).
        timeout = cmd_run_sync_bridge_timeout_seconds(action)
        return call_async_from_sync(self._executor.run, timeout, action)

    def read(self, action: FileReadAction) -> Observation:
        """Read file via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return call_async_from_sync(
            self._executor.read, TOOL_BRIDGE_TIMEOUT_FILE_IO, action
        )

    def edit(self, action: FileEditAction) -> Observation:
        """Edit file via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return call_async_from_sync(
            self._executor.edit, TOOL_BRIDGE_TIMEOUT_FILE_IO, action
        )

    def terminal_run(self, action: TerminalRunAction) -> Observation:
        """Start an interactive terminal session via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        # Do not inherit inflated action.timeout (e.g. 900s runtime cap) for open.
        timeout = min(
            TOOL_BRIDGE_TIMEOUT_TERMINAL_RUN,
            TERMINAL_RUN_EXECUTION_TIMEOUT_SECONDS + TOOL_BRIDGE_TIMEOUT_BUFFER,
        )
        return call_async_from_sync(self._executor.terminal_run, timeout, action)

    def terminal_input(self, action: TerminalInputAction) -> Observation:
        """Send input to a terminal session via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        timeout = self._bridge_timeout(action, TOOL_BRIDGE_TIMEOUT_TERMINAL_IO)
        return call_async_from_sync(self._executor.terminal_input, timeout, action)

    def terminal_read(self, action: TerminalReadAction) -> Observation:
        """Read terminal output via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        timeout = self._bridge_timeout(action, TOOL_BRIDGE_TIMEOUT_TERMINAL_IO)
        return call_async_from_sync(self._executor.terminal_read, timeout, action)

    def terminal_wait(self, action: TerminalWaitAction) -> Observation:
        """Wait for terminal output pattern via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        wait_timeout = max(1, int(getattr(action, 'timeout', 30) or 30))
        timeout = max(
            self._bridge_timeout(action, TOOL_BRIDGE_TIMEOUT_TERMINAL_IO),
            float(wait_timeout) + 5.0,
        )
        return call_async_from_sync(self._executor.terminal_wait, timeout, action)

    def terminal_list(self, action: TerminalListAction) -> Observation:
        """List terminal sessions via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        timeout = self._bridge_timeout(action, TOOL_BRIDGE_TIMEOUT_TERMINAL_IO)
        return call_async_from_sync(self._executor.terminal_list, timeout, action)

    def terminal_close(self, action: TerminalCloseAction) -> Observation:
        """Close a terminal session via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        timeout = self._bridge_timeout(action, TOOL_BRIDGE_TIMEOUT_TERMINAL_IO)
        return call_async_from_sync(self._executor.terminal_close, timeout, action)

    def debugger(self, action: DebuggerAction) -> Observation:
        """Execute a debugger action via :meth:`DAPDebugManager.handle`.

        ``run_action`` runs ``LocalRuntimeInProcess.debugger`` on asyncio's default
        executor (sync bridge). Avoid ``RuntimeExecutor.debugger`` here: that path
        uses ``asyncio.to_thread(handle, ...)`` on a nested event loop, and on Windows
        the inner default pool could still queue ``handle`` for tens of seconds under
        load — ``app.log`` then showed ``_handle_action START DebuggerAction`` with no
        ``DEBUGGER_DISPATCH``. Calling sync ``handle`` on this worker matches the
        intended offload (we are already off the agent event loop) and removes the
        extra scheduling hop.

        Pending-action timeouts are enforced by the controller; see
        ``pending_action_service`` for debugger ceilings.
        """
        if not self._agent_debugger_enabled():
            return ErrorObservation(
                content=(
                    'Interactive debugger is disabled for this session '
                    '(dap_config.enabled is false). '
                    'Set dap_config.enabled=true in settings.json to use the DAP debugger tool.'
                )
            )
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return self._executor.debug_manager.handle(action)

    def lsp_query(self, action: LspQueryAction) -> Observation:
        """Execute LSP query via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        timeout = self._bridge_timeout(action, TOOL_BRIDGE_TIMEOUT_READ_ONLY)
        return call_async_from_sync(self._executor.lsp_query, timeout, action)

    def grep(self, action: GrepAction) -> Observation:
        """Execute grep search via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        timeout = self._bridge_timeout(action, TOOL_BRIDGE_TIMEOUT_READ_ONLY)
        return call_async_from_sync(self._executor.grep, timeout, action)

    def glob(self, action: GlobAction) -> Observation:
        """Execute glob listing via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        timeout = self._bridge_timeout(action, TOOL_BRIDGE_TIMEOUT_READ_ONLY)
        return call_async_from_sync(self._executor.glob, timeout, action)

    def find_symbols(self, action: FindSymbolsAction) -> Observation:
        """Execute symbol discovery via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        timeout = self._bridge_timeout(action, TOOL_BRIDGE_TIMEOUT_READ_ONLY)
        return call_async_from_sync(self._executor.find_symbols, timeout, action)

    def analyze_project_structure(
        self, action: AnalyzeProjectStructureAction
    ) -> Observation:
        """Execute APS analysis via RuntimeExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        timeout = self._bridge_timeout(action, TOOL_BRIDGE_TIMEOUT_READ_ONLY)
        return call_async_from_sync(
            self._executor.analyze_project_structure, timeout, action
        )

    def checkpoint(self, action: Any) -> Observation:
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return call_async_from_sync(
            self._executor.checkpoint, TOOL_BRIDGE_TIMEOUT_FILE_IO, action
        )

    def working_memory(self, action: Any) -> Observation:
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return call_async_from_sync(
            self._executor.working_memory, TOOL_BRIDGE_TIMEOUT_FILE_IO, action
        )

    def memory_persist(self, action: Any) -> Observation:
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return call_async_from_sync(
            self._executor.memory_persist, TOOL_BRIDGE_TIMEOUT_FILE_IO, action
        )

    def memory_recall(self, action: Any) -> Observation:
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return call_async_from_sync(
            self._executor.memory_recall, TOOL_BRIDGE_TIMEOUT_READ_ONLY, action
        )

    def scratchpad_note(self, action: Any) -> Observation:
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return call_async_from_sync(
            self._executor.scratchpad_note, TOOL_BRIDGE_TIMEOUT_FILE_IO, action
        )

    def scratchpad_recall(self, action: Any) -> Observation:
        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        return call_async_from_sync(
            self._executor.scratchpad_recall, TOOL_BRIDGE_TIMEOUT_FILE_IO, action
        )

    @staticmethod
    def _bridge_timeout(action: Any, fallback_ceiling: float) -> float:
        """Pick a sync-bridge timeout that respects the action's own timeout.

        Returns ``action.timeout + buffer`` when the action carries a timeout,
        otherwise falls back to ``fallback_ceiling``. This keeps the bridge in
        lock-step with controller-level pending-action timeouts so we never
        time out the bridge while the controller still considers the action live.
        """
        own = getattr(action, 'timeout', None)
        if own is None or own <= 0:
            return fallback_ceiling
        return float(own) + TOOL_BRIDGE_TIMEOUT_BUFFER

    def set_browser_structured_extract(self, fn: Any | None) -> None:
        """Wire orchestrator LLM extract callback into RuntimeExecutor (``browser extract``)."""
        if self._executor is None:
            return
        self._executor.set_browser_structured_extract(fn)

    def browser_tool(self, action: Any) -> Observation:
        """Native browser-use tool via RuntimeExecutor."""
        from backend.ledger.action.browser_tool import BrowserToolAction

        if self._executor is None:
            raise AgentRuntimeDisconnectedError('Runtime not initialized')
        if not isinstance(action, BrowserToolAction):
            raise TypeError('expected BrowserToolAction')
        session_ready = False
        native_browser = getattr(self._executor, '_native_browser', None)
        if native_browser is not None:
            session_ready = getattr(native_browser, '_session', None) is not None
        timeout = browser_tool_sync_bridge_timeout_seconds(
            action,
            session_ready=session_ready,
        )
        try:
            if self._browser_loop_runner is None:
                self._browser_loop_runner = _PersistentAsyncLoopRunner()
            return self._browser_loop_runner.submit(
                self._executor.browser_tool,
                timeout,
                action,
            )
        except TimeoutError:
            sub = getattr(action, 'command', '') or ''
            if self._browser_loop_runner is not None:
                self._browser_loop_runner.cancel_pending()
                self._browser_loop_runner.close()
                self._browser_loop_runner = None
            if native_browser is not None:
                setattr(self._executor, '_native_browser', None)
            return ErrorObservation(
                content=(
                    f'ERROR: Browser tool timed out after {timeout:.0f}s '
                    f'(subcommand={sub!r}). '
                    'Try `browser snapshot` for DOM state, or retry the browser command; '
                    'the local browser loop was reset after the timeout.'
                )
            )

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

        from backend.core.type_safety.path_validation import (
            PathValidationError,
            SafePath,
        )
        from backend.core.workspace_resolution import workspace_grinta_root
        from backend.execution.aes.security_enforcement import path_is_within_workspace

        workspace = Path(self._executor.initial_cwd).resolve()
        app_workspace_root = workspace_grinta_root(workspace).resolve()
        try:
            safe_path = SafePath.validate(
                path,
                workspace_root=workspace,
                must_be_relative=not os.path.isabs(path),
            )
            resolved = safe_path.path.resolve()
        except PathValidationError:
            logger.warning('Rejected invalid list_files path: %s', path, exc_info=True)
            raise
        except (OSError, ValueError) as exc:
            raise PathValidationError(f'Invalid list_files path: {exc}', path) from exc

        if not (
            path_is_within_workspace(resolved, workspace)
            or path_is_within_workspace(resolved, app_workspace_root)
        ):
            raise PathValidationError(
                f'Path outside workspace boundary: {path}',
                path,
            )
        return str(resolved)

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

        # Offload blocking cleanup to a thread when an event loop is running
        # so we don't stall the async controller / REPL.
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            asyncio.create_task(self._async_close_cleanup())
        else:
            self._sync_close_cleanup()

        super().close()

    def _sync_close_cleanup(self) -> None:
        """Synchronous workspace teardown (safe for atexit / non-async callers)."""
        import shutil
        import time

        time.sleep(0.5)
        self._remove_workspace(shutil, time)

    async def _async_close_cleanup(self) -> None:
        """Asynchronous workspace teardown (non-blocking for async callers)."""
        import shutil
        import time

        await asyncio.sleep(0.5)
        self._remove_workspace(shutil, time)

    def _remove_workspace(self, shutil_mod: Any, time_mod: Any) -> None:
        """Remove the temporary workspace with retry logic."""
        if (
            self._owns_workspace
            and self._temp_workspace
            and os.path.exists(self._temp_workspace)
        ):
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    shutil_mod.rmtree(self._temp_workspace)
                    break
                except (PermissionError, OSError) as e:
                    if attempt < max_retries - 1:
                        time_mod.sleep(1.0)
                        continue
                    try:
                        logger.warning(
                            'Failed to remove workspace %s after %s attempts: %s',
                            self._temp_workspace,
                            max_retries,
                            e,
                        )
                    except Exception:
                        pass

    @property
    def workspace_root(self) -> Path:
        """Return the workspace root path."""
        return Path(self._temp_workspace) if self._temp_workspace else Path('.')  # pylint: disable=redefined-outer-name,reimported

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
                logger.info(
                    'tmux not found; using simple subprocess-based Bash session. '
                    'Grinta installs tmux automatically on Linux when possible.'
                )

    def additional_agent_instructions(self) -> str:
        """Provide runtime-specific instructions about the local environment and paths."""
        from backend.core.os_capabilities import OS_CAPS

        workspace_root = self.workspace_root.absolute()
        project_root = (
            Path(self.project_root).absolute() if self.project_root else workspace_root
        )
        platform_name = (
            'Windows'
            if OS_CAPS.is_windows
            else ('macOS' if OS_CAPS.is_macos else 'Linux')
        )

        return (
            '### Local Environment Context\n'
            f'- **Workspace Root (Absolute)**: {workspace_root}\n'
            f'- **Project Root (Absolute)**: {project_root}\n'
            f'- **Platform**: {platform_name}\n'
            'Always use absolute paths when referencing files in the project tree to avoid ambiguity '
            'between nested source directories (e.g. `src/` vs `flask/src/`).'
        )

    def _sanitize_config(self) -> None:
        """Sanitize configuration and ensure compatibility."""
        security_cfg = getattr(self.config, 'security', None)
        if not isinstance(security_cfg, SecurityConfig):
            self.config.security = SecurityConfig()
