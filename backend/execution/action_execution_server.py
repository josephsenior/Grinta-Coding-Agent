"""This is the main file for the runtime client.

It is responsible for executing actions received from app backend and producing observations.

NOTE: this executes inside the local runtime environment.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from backend.core.enums import FileEditSource, FileReadSource
from backend.core.logger import app_logger as logger
from backend.core.os_capabilities import OS_CAPS
from backend.execution.action_execution_server_io import (
    RuntimeExecutorIOAndTerminalMixin,
)
from backend.execution.debugger import DAPDebugManager
from backend.execution.file_operations import (
    execute_file_editor,
    get_max_edit_observation_chars,
    handle_directory_view,
    truncate_large_text,
)
from backend.execution.security_enforcement import (
    evaluate_hardened_local_command_policy,
    path_is_within_workspace,
    tokenize_command,
)
from backend.execution.mcp.proxy import MCPProxyManager
from backend.execution.plugin_loader import init_plugins
from backend.execution.plugins import Plugin
from backend.execution.server_routes import (
    register_exception_handlers,
    register_routes,
)
from backend.execution.utils.diff import get_diff
from backend.execution.utils.file_editor import FileEditor
from backend.execution.utils.memory_monitor import MemoryMonitor
from backend.execution.utils.session_manager import SessionManager
from backend.ledger.action.browser_tool import BrowserToolAction
from backend.ledger.action.commands import CmdRunAction
from backend.ledger.action.code_nav import LspQueryAction
from backend.ledger.action.mcp import MCPAction
from backend.ledger.observation import (
    ErrorObservation,
    LspQueryObservation,
    Observation,
)
from backend.ledger.observation.files import FileEditObservation, FileReadObservation
from backend.persistence.locations import get_workspace_downloads_dir
from backend.utils.regex_limits import try_compile_user_regex


def resolve_workspace_path(path: str, working_dir: str, workspace_root: str) -> Path:
    """Resolve a workspace-relative path against *working_dir* (session cwd)."""
    base = Path(working_dir).resolve()
    candidate = Path(path)
    return candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()

_ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*m')
_POWERSHELL_BUILTIN_COMMANDS = frozenset(
    {
        'Get-Content',
        'Write-Output',
        'Get-ChildItem',
        'Select-String',
        'Set-Location',
        'Select-Object',
        'Measure-Object',
        'Out-File',
        'Test-Path',
        'Remove-Item',
    }
)

# Note: Import is deferred to avoid executing windows_bash.py on non-Windows platforms
if OS_CAPS.is_windows:
    pass


class ActionRequest(BaseModel):
    """Incoming action execution request envelope sent to runtime server."""

    event: dict[str, Any]


class RuntimeExecutor(RuntimeExecutorIOAndTerminalMixin):
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
            logger.info('Step 1/4: Initializing default shell session...')
            self.session_manager.create_session(session_id='default')

            # Step 2: Initialize plugins
            logger.info('Step 2/4: Initializing plugins...')
            self.plugins = await init_plugins(self.plugins_to_load, self.username)

            # Step 3: Initialize shell commands/aliases
            logger.info('Step 3/4: Setting up shell commands...')
            self._init_shell_commands()

            # Step 4: Start memory monitoring
            logger.info('Step 4/4: Starting memory monitor...')
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
                symbol=getattr(action, 'symbol', ''),
            )

            latency_ms = int((time.perf_counter() - start) * 1000)
            obs = LspQueryObservation(
                content=result.format_text(action.command),
                available=bool(result.available),
            )
            obs.tool_result = {
                'tool': 'code_intelligence',
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
                'tool': 'code_intelligence',
                'command': action.command,
                'file': action.file,
                'latency_ms': latency_ms,
                'available': False,
                'has_error': True,
            }
            return err

    async def browser_tool(self, action: BrowserToolAction) -> Observation:
        """Run native browser-use commands (in-process; optional dependency)."""
        if not self.enable_browser:
            return ErrorObservation(
                content=(
                    'ERROR: Browser runtime is disabled for this session '
                    '(enable_browser=false on the runtime).'
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
                        logger.debug('MCP executor disconnect: %s', exc, exc_info=True)
                    await asyncio.sleep(0)

            try:
                from backend.core.constants import GENERAL_TIMEOUT
                from backend.utils.async_utils import call_async_from_sync

                call_async_from_sync(_disconnect_mcp, GENERAL_TIMEOUT)
            except Exception as exc:
                logger.debug('MCP disconnect during RuntimeExecutor.close: %s', exc)

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
initialization_task: asyncio.Task[None] | None = None


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
    logger.info('Starting server (prewarm check for local models)...')

    # Run prewarm check synchronously (in a thread) so we fail startup fast if
    # prebundled model artifacts are missing.
    try:
        from backend.utils.model_prewarm import (
            ensure_models_available,
            get_default_models_to_prewarm,
        )

        prebundle_env = os.getenv('PREBUNDLED_MODELS', '')
        models = get_default_models_to_prewarm()
        if prebundle_env:
            models += [m.strip() for m in prebundle_env.split(',') if m.strip()]
        # snapshot_download is blocking; run it in a thread to avoid blocking the loop.
        await asyncio.to_thread(ensure_models_available, models, True)
        logger.info('Prewarm check succeeded: required models available locally')
    except Exception as e:
        logger.error('Prewarm model check failed: %s', e, exc_info=True)
        # Raise to prevent yielding readiness — startup should fail fast when artifacts are missing.
        raise

    # Start initialization in background task
    initialize_background = globals().get('_initialize_background')
    if not callable(initialize_background):

        async def _noop_initialize(_: FastAPI) -> None:
            return

        initialize_background = _noop_initialize
    initialization_task = asyncio.create_task(initialize_background(app))

    # Yield after prewarm so server can start accepting requests
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
    raise SystemExit(
        'CLI-only product: direct HTTP/OpenAPI launch via '
        'backend.execution.action_execution_server is retired.'
    )
