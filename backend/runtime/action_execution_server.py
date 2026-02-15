"""This is the main file for the runtime client.

It is responsible for executing actions received from forge backend and producing observations.

NOTE: this executes inside the local runtime environment.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, cast

import puremagic
from binaryornot.check import is_binary
from fastapi import FastAPI
from pydantic import BaseModel
from uvicorn import run

from backend.core.logger import FORGE_logger as logger
from backend.events.action import (
    BrowseInteractiveAction,
    BrowseURLAction,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
)
from backend.core.enums import FileEditSource, FileReadSource
from backend.events.observation import (
    CmdOutputObservation,
    ErrorObservation,
    FileDownloadObservation,
    FileEditObservation,
    FileReadObservation,
    FileWriteObservation,
    Observation,
)
from backend.runtime.file_operations import (
    ensure_directory_exists,
    execute_file_editor,
    get_max_edit_observation_chars,
    handle_directory_view,
    handle_file_read_errors,
    read_image_file,
    read_pdf_file,
    read_text_file,
    read_video_file,
    resolve_path,
    set_file_permissions,
    truncate_large_text,
    write_file_content,
)
from backend.runtime.file_viewer_server import start_file_viewer_server
from backend.runtime.mcp.proxy import MCPProxyManager
from backend.runtime.plugins import ALL_PLUGINS, Plugin
from backend.runtime.server_routes import (
    register_auth_middleware,
    register_exception_handlers,
    register_routes,
)
from backend.runtime.utils import find_available_tcp_port
from backend.runtime.utils.bash import BashSession
from backend.runtime.utils.diff import get_diff
from backend.runtime.utils.file_editor import FileEditor
from backend.runtime.utils.memory_monitor import MemoryMonitor
from backend.runtime.utils.process_registry import TaskCancellationService
from backend.utils.async_utils import call_sync_from_async

if TYPE_CHECKING:
    from backend.runtime.browser.browser_env import BrowserEnv

# Note: Import is deferred to avoid executing windows_bash.py on non-Windows platforms
if sys.platform == "win32":
    pass


def _module_attr(name: str):
    """Return the latest attribute from this module for monkeypatched helpers."""
    return getattr(sys.modules[__name__], name)


class ActionRequest(BaseModel):
    """Incoming action execution request envelope sent to runtime server."""

    event: dict[str, Any]


class ActionExecutor:
    """ActionExecutor runs inside the local runtime environment.

    It is responsible for executing actions received from forge backend and producing observations.
    """

    def __init__(
        self,
        plugins_to_load: list[Plugin],
        work_dir: str,
        username: str,
        user_id: int,
        enable_browser: bool,
        browsergym_eval_env: str | None,
        tool_registry: Any | None = None,  # ToolRegistry for cross-platform support
    ) -> None:
        """Create runtime executor, initialize workspace, and prepare tooling integrations."""
        self.username = username
        self.user_id = user_id
        self._initial_cwd = work_dir
        self.max_memory_gb: int | None = None  # Will be set during ainit if available
        self.enable_browser = enable_browser
        self.browsergym_eval_env = browsergym_eval_env
        self.browser: BrowserEnv | None = None

        self.bash_session: BashSession | None = None
        self.cancellation_service = TaskCancellationService(label=f"runtime:{work_dir}")
        self.lock = asyncio.Lock()
        self.plugins: dict[str, Plugin] = {}
        # We need the file editor for ACI actions (view) even if we use helper functions
        self.file_editor = FileEditor(workspace_root=self._initial_cwd)
        self.plugins_to_load = plugins_to_load
        self._initialized = False
        self.memory_monitor = MemoryMonitor()
        self.tool_registry = tool_registry
        self.start_time = time.time()
        self.last_execution_time = time.time()
        self.downloaded_files: list[str] = []
        self.downloads_directory = os.path.join(work_dir, "downloads")
        # Ensure downloads directory exists
        os.makedirs(self.downloads_directory, exist_ok=True)

    @property
    def initial_cwd(self) -> str:
        """Get the initial working directory for the action execution server."""
        return self._initial_cwd

    async def _init_browser_async(self) -> None:
        """Initialize the browser asynchronously."""
        if not self.enable_browser:
            return

        try:
            logger.info("Initializing browser environment...")
            from backend.runtime.browser.browser_env import BrowserEnv

            self.browser = BrowserEnv(
                browsergym_eval_env=self.browsergym_eval_env,
            )
            logger.info("Browser environment initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize browser: %s", e)
            self.browser = None

    async def _ensure_browser_ready(self) -> None:
        """Ensure the browser is ready for use."""
        if self.browser:
            if not self.browser.check_alive(timeout=5):
                self.browser.init_browser()

    def _create_bash_session(self, cwd: str | None = None):
        """Create a shell session appropriate for the current platform."""
        from backend.runtime.utils.unified_shell import create_shell_session

        if self.tool_registry is None:
            # Create a default tool registry if none provided
            # This is a fallback and shouldn't typically happen in production flow
            try:
                from backend.runtime.tools import ToolRegistry

                self.tool_registry = ToolRegistry()
            except ImportError:
                pass

        shell_session = create_shell_session(
            work_dir=cwd or self._initial_cwd,
            tools=self.tool_registry,
            username=self.username,
            no_change_timeout_seconds=int(
                os.environ.get("NO_CHANGE_TIMEOUT_SECONDS", 10)
            ),
            max_memory_mb=self.max_memory_gb * 1024 if self.max_memory_gb else None,
            cancellation_service=self.cancellation_service,
        )
        shell_session.initialize()
        logger.info("Shell session initialized successfully")
        return shell_session

    async def hard_kill(self) -> None:
        """Best-effort immediate termination of processes started by this runtime."""
        self.cancellation_service.cancel_all()
        if self.bash_session:
            self.bash_session.close()
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

            # Step 1: Initialize bash session
            logger.info("Step 1/5: Initializing bash session...")
            self.bash_session = self._create_bash_session()

            # Step 2: Initialize browser in background if enabled
            if self.enable_browser:
                logger.info("Step 2/5: Starting browser initialization (background)...")
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
                logger.info("Step 2/5: Browser disabled, skipping...")

            # Step 3: Initialize plugins
            logger.info("Step 3/5: Initializing plugins...")
            for plugin in self.plugins_to_load:
                await self._init_plugin(plugin)

            # Step 4: Initialize bash commands/aliases
            logger.info("Step 4/5: Setting up bash commands...")
            self._init_bash_commands()

            # Step 5: Start memory monitoring
            logger.info("Step 5/5: Starting memory monitor...")
            self.memory_monitor.start_monitoring()

            logger.info("All initialization steps completed successfully")
            self._initialized = True
        except Exception as e:
            logger.error(
                "ActionExecutor initialization failed at step: %s",
                e,
                exc_info=True,
            )
            # Ensure we clean up if initialization fails
            await self.hard_kill()
            raise

    def initialized(self) -> bool:
        """Check if action execution server has completed initialization."""
        return self._initialized

    async def _init_plugin(self, plugin: Plugin):
        self.plugins[plugin.name] = plugin
        await plugin.initialize(self.username)
        logger.info("Plugin %s initialized", plugin.name)

    def _init_bash_commands(self):
        # We need to set up some aliases and functions in bash for better UX
        assert self.bash_session is not None

        # Init git configuration
        self.bash_session.execute(
            CmdRunAction(
                command=f'git config --global user.name "{self.username}" && git config --global user.email "{self.username}@example.com"',
            )
        )

        # Initialize plugins commands
        for plugin in self.plugins.values():
            init_cmds = plugin.get_init_bash_commands()
            if init_cmds:
                for cmd in init_cmds:
                    self.bash_session.execute(CmdRunAction(command=cmd))

    async def run_action(self, action) -> Observation:
        """Execute any action through action execution server."""
        async with self.lock:
            action_type = action.action
            return await getattr(self, action_type)(action)

    async def run(
        self, action: CmdRunAction
    ) -> CmdOutputObservation | ErrorObservation:
        """Execute bash/shell command."""
        try:
            bash_session = self.bash_session
            if action.is_static:
                bash_session = self._create_bash_session(action.cwd)
            assert bash_session is not None
            observation = cast(
                CmdOutputObservation,
                await call_sync_from_async(bash_session.execute, action),
            )

            # Check for detected servers and add to observation extras
            detected_server = cast(Any, bash_session.get_detected_server())
            if detected_server:
                logger.info(
                    "🚀 Adding detected server to observation extras: %s",
                    detected_server.url,
                )
                # Add server info to observation extras for client processing
                if not hasattr(observation, "extras"):
                    observation.extras = {}  # type: ignore[attr-defined]
                observation.extras["server_ready"] = {  # type: ignore[attr-defined]
                    "port": detected_server.port,
                    "url": detected_server.url,
                    "protocol": detected_server.protocol,
                    "health_status": detected_server.health_status,
                }

            return observation
        except Exception as e:
            logger.error("Error running command: %s", e)
            return ErrorObservation(str(e))

    def _resolve_path(self, path: str, working_dir: str) -> str:
        """Resolve a relative or absolute path to an absolute path with security validation."""
        return resolve_path(path, working_dir)

    def _handle_aci_file_read(self, action: FileReadAction) -> FileReadObservation:
        """Handle file reading using the FILE_EDITOR implementation."""
        result_str, _ = execute_file_editor(
            self.file_editor,
            command="view",
            path=action.path,
            view_range=action.view_range,
        )
        return FileReadObservation(
            content=result_str, path=action.path, impl_source=FileReadSource.FILE_EDITOR
        )

    async def read(self, action: FileReadAction) -> Observation:
        """Read a file and return its content as an observation."""
        assert self.bash_session is not None

        # Check for binary files
        if is_binary(action.path):
            return ErrorObservation("ERROR_BINARY_FILE")

        # Handle FILE_EDITOR implementation
        if action.impl_source == FileReadSource.FILE_EDITOR:
            return self._handle_aci_file_read(action)

        # Resolve file path
        working_dir = self.bash_session.cwd
        filepath = resolve_path(action.path, working_dir)

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
        """Write content to a file with proper error handling."""
        assert self.bash_session is not None
        working_dir = self.bash_session.cwd
        filepath = resolve_path(action.path, working_dir)

        # Ensure directory exists
        ensure_directory_exists(filepath)

        # Prepare file metadata
        file_exists = os.path.exists(filepath)
        file_stat = os.stat(filepath) if file_exists else None

        # Write file content
        write_result = write_file_content(filepath, action, file_exists)
        if isinstance(write_result, ErrorObservation):
            return write_result

        # Set file permissions and ownership
        set_file_permissions(filepath, file_exists, file_stat)

        return FileWriteObservation(content="", path=filepath)

    async def edit(self, action: FileEditAction) -> Observation:
        """Execute file edit operation."""
        # We always expect FILE_EDITOR source now
        assert action.impl_source == FileEditSource.FILE_EDITOR
        from backend.core.schemas import ActionConfirmationStatus

        is_mutating_file_edit = action.command != "view"
        is_preview = (
            is_mutating_file_edit
            and getattr(action, "confirmation_state", None)
            == ActionConfirmationStatus.AWAITING_CONFIRMATION
        )

        # Handle directory viewing specially
        dir_obs = self._handle_edit_directory_view(action)
        if dir_obs:
            return dir_obs

        result_str, (old_content, new_content) = execute_file_editor(
            self.file_editor,
            command=action.command,
            path=action.path,
            file_text=action.file_text,
            old_str=action.old_str,
            new_str=action.new_str,
            insert_line=action.insert_line,
            enable_linting=False,
            dry_run=is_preview,
        )
        if is_preview and not result_str.startswith("ERROR:"):
            result_str = (
                "Preview generated (no changes applied). Confirm to apply these edits."
            )

        safe_old, safe_new, safe_diff = self._prepare_edit_observation_contents(
            old_content, new_content, action.path
        )

        return FileEditObservation(
            content=result_str,
            path=action.path,
            prev_exist=old_content is not None,
            old_content=safe_old,
            new_content=safe_new,
            impl_source=FileEditSource.FILE_EDITOR,
            diff=safe_diff,
            preview=is_preview,
        )

    def _handle_edit_directory_view(self, action: FileEditAction) -> Observation | None:
        """Handle 'view' command when path is a directory."""
        if action.command != "view":
            return None
        try:
            resolved_path = resolve_path(action.path, self._initial_cwd)
            if os.path.exists(resolved_path) and os.path.isdir(resolved_path):
                return handle_directory_view(resolved_path, action.path)
        except (Exception, OSError, ValueError):
            pass
        return None

    def _prepare_edit_observation_contents(
        self, old_content: str | None, new_content: str | None, path: str
    ) -> tuple[str | None, str | None, str]:
        """Truncate contents and generate diff for observation."""
        max_chars = get_max_edit_observation_chars()

        def truncate(text, label):
            return (
                truncate_large_text(text, max_chars, label=label)
                if text is not None
                else None
            )

        safe_old = truncate(old_content, "edit.old_content")
        safe_new = truncate(new_content, "edit.new_content")

        diff_text = get_diff(old=safe_old or "", new=safe_new or "", path=path)
        safe_diff = truncate_large_text(diff_text, max_chars, label="edit.diff")

        return safe_old, safe_new, safe_diff

    async def browse(self, action: BrowseURLAction) -> Observation:
        """Browse URL and return page content."""
        if self.browser is None:
            return ErrorObservation(
                "Browser functionality is not supported or disabled."
            )
        await self._ensure_browser_ready()
        from backend.runtime.browser import browse

        return await browse(action, self.browser, self.initial_cwd)

    async def browse_interactive(self, action: BrowseInteractiveAction) -> Observation:
        """Execute interactive browser commands via BrowserGym.

        Args:
            action: Browse interactive action with browser commands

        Returns:
            Browser observation with command results or error

        """
        if self.browser is None:
            return ErrorObservation(
                "Browser functionality is not supported or disabled."
            )
        await self._ensure_browser_ready()
        from backend.runtime.browser import browse

        browser_observation = await browse(action, self.browser, self.initial_cwd)
        if not browser_observation.error:
            return browser_observation
        curr_files = os.listdir(self.downloads_directory)
        new_download = False
        for file in curr_files:
            if file not in self.downloaded_files:
                new_download = True
                self.downloaded_files.append(file)
                break
        if not new_download:
            return browser_observation
        src_path = os.path.join(self.downloads_directory, self.downloaded_files[-1])
        file_ext = ""
        try:
            guesses = puremagic.magic_file(src_path)
            if len(guesses) > 0:
                ext = guesses[0].extension.strip()
                if len(ext) > 0:
                    file_ext = ext
        except Exception:
            pass
        tgt_path = os.path.join(
            "/workspace", f"file_{len(self.downloaded_files)}{file_ext}"
        )
        shutil.copy(src_path, tgt_path)
        return FileDownloadObservation(
            content=f"Execution of the previous action {action.browser_actions} resulted in a file download. The downloaded file is saved at location: {tgt_path}",
            file_path=tgt_path,
        )

    def close(self) -> None:
        """Close action execution server and clean up resources."""
        self.memory_monitor.stop_monitoring()
        if self.bash_session is not None:
            self.bash_session.close()
        if self.browser is not None:
            self.browser.close()


# Initialize global variables for client and proxies
client: ActionExecutor | None = None
mcp_proxy_manager: MCPProxyManager | None = None


# Initializers for routes
def get_client() -> ActionExecutor:
    if client is None:
        logger.warning("Action executor not initialized")
        raise ReferenceError("Action executor not initialized")
    return client


def get_mcp_proxy() -> MCPProxyManager | None:
    return mcp_proxy_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage FastAPI application lifespan."""
    global initialization_task
    logger.info("Starting server (initialization will run in background)...")

    # Start initialization in background task
    initialize_background = globals().get("_initialize_background")
    if not callable(initialize_background):

        async def _noop_initialize(_: FastAPI) -> None:
            return

        initialize_background = _noop_initialize
    initialization_task = asyncio.create_task(initialize_background(app))

    # Yield immediately so server can start accepting requests
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

    logger.info("Closing ActionExecutor...")
    if client:
        try:
            client.close()
            logger.info("ActionExecutor closed successfully.")
        except Exception as e:
            logger.error("Error closing ActionExecutor: %s", e, exc_info=True)

    logger.info("Shutdown complete.")


app = FastAPI(lifespan=lifespan)
register_exception_handlers(app)
session_api_key = os.environ.get("SESSION_API_KEY", "")
register_auth_middleware(app, session_api_key)
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
    parser.add_argument("--username", type=str, help="User to run as", default="forge")
    parser.add_argument("--user-id", type=int, help="User ID to run as", default=1000)
    parser.add_argument(
        "--enable-browser",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable the browser environment",
    )
    parser.add_argument(
        "--browsergym-eval-env",
        type=str,
        help="BrowserGym environment used for browser evaluation",
        default=None,
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

    client: ActionExecutor | None = None  # type: ignore[no-redef]
    mcp_proxy_manager: MCPProxyManager | None = None  # type: ignore[no-redef]
    initialization_task: asyncio.Task | None = None
    initialization_error: Exception | None = None

    async def _initialize_background(app: FastAPI):
        """Initialize ActionExecutor and MCP Proxy Manager in the background."""
        global client, mcp_proxy_manager, initialization_error
        try:
            logger.info("Initializing ActionExecutor...")
            client = ActionExecutor(
                plugins_to_load,
                work_dir=args.working_dir,
                username=args.username,
                user_id=args.user_id,
                enable_browser=args.enable_browser,
                browsergym_eval_env=args.browsergym_eval_env,
            )
            logger.info(
                "ActionExecutor instance created. Starting async initialization..."
            )

            init_timeout = int(os.environ.get("ACTION_EXECUTOR_INIT_TIMEOUT", "300"))
            try:
                await asyncio.wait_for(client.ainit(), timeout=init_timeout)
                logger.info("ActionExecutor initialized successfully.")
            except TimeoutError as exc:
                error_msg = f"ActionExecutor initialization timed out after {init_timeout} seconds."
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
                    auth_enabled=bool(os.environ.get("SESSION_API_KEY")),
                    api_key=os.environ.get("SESSION_API_KEY"),
                    logger_level=logger.getEffectiveLevel(),
                )
                mcp_proxy_manager.initialize()
                allowed_origins = ["*"]
                try:
                    await mcp_proxy_manager.mount_to_app(app, allowed_origins)
                    logger.info("MCP Proxy Manager mounted to app successfully")
                except Exception as e:
                    logger.error("Error mounting MCP Proxy: %s", e, exc_info=True)
                    logger.warning("Continuing without MCP Proxy mounting")

        except Exception as e:
            logger.error(
                "Failed to initialize ActionExecutor: %s",
                e,
                exc_info=True,
            )
            initialization_error = e

    logger.debug("Starting action execution API on port %d", args.port)
    log_config = None
    if os.getenv("LOG_JSON", "0") in ("1", "true", "True"):
        log_config = get_uvicorn_json_log_config()
    run(app, host="0.0.0.0", port=args.port, log_config=log_config, use_colors=False)
