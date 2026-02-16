"""In-process LocalRuntime - runs ActionExecutor directly without subprocess/HTTP.

This is a simplified version that eliminates the complexity of subprocess management
and HTTP communication for desktop applications that only need local runtime.
"""

from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from backend.core.config.security_config import SecurityConfig
from backend.core.exceptions import AgentRuntimeDisconnectedError
from backend.core.logger import FORGE_logger as logger
from backend.events.action import (
    ActionSecurityRisk,
    BrowseInteractiveAction,
    BrowseURLAction,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
    MCPAction,
)
from backend.events.observation import Observation
from backend.runtime.action_execution_server import ActionExecutor
from backend.runtime.capabilities import detect_capabilities
from backend.runtime.drivers.action_execution.action_execution_client import (
    ActionExecutionClient,
)
from backend.runtime.executor_protocol import ActionExecutorProtocol
from backend.runtime.plugins import ALL_PLUGINS, Plugin
from backend.core.enums import RuntimeStatus
from backend.security.analyzer import SecurityAnalyzer
from backend.utils.async_utils import call_async_from_sync

if TYPE_CHECKING:
    from backend.core.config import ForgeConfig
    from backend.events import EventStream
    from backend.core.provider_types import PROVIDER_TOKEN_TYPE
    from backend.llm.llm_registry import LLMRegistry
    from backend.runtime.plugins import PluginRequirement


def get_user_info() -> tuple[int, str | None]:
    """Get user ID and username in a cross-platform way."""
    username = os.getenv("USER") or os.getenv("USERNAME")
    uid_getter = getattr(os, "getuid", None)
    if uid_getter and callable(uid_getter):
        return (uid_getter(), username)  # pylint: disable=not-callable
    return (0, username)


class LocalRuntimeInProcess(ActionExecutionClient):
    """In-process local runtime that runs ActionExecutor directly.

    This eliminates subprocess and HTTP overhead by running ActionExecutor
    directly in the same process. Ideal for desktop applications.
    """

    def __init__(
        self,
        config: ForgeConfig,
        event_stream: EventStream,
        llm_registry: LLMRegistry,
        sid: str = "default",
        plugins: list[PluginRequirement] | None = None,
        env_vars: dict[str, str] | None = None,
        status_callback: Callable[[str, RuntimeStatus, str], None] | None = None,
        attach_to_existing: bool = False,
        headless_mode: bool = True,
        user_id: str | None = None,
        vcs_provider_tokens: PROVIDER_TOKEN_TYPE | None = None,
        workspace_base: str | None = None,
    ) -> None:
        """Initialize in-process local runtime."""
        # Initialize parent
        safe_event_stream = event_stream if hasattr(event_stream, "subscribe") else None
        self.is_windows = sys.platform == "win32"

        # Initialize tooling and security
        self._init_tooling_and_platform()

        self.config = config
        self._original_config = config

        # Ensure config compatibility and user info
        self._sanitize_config()
        self._user_id, self._username = get_user_info()

        logger.info(
            "Initializing In-Process LocalRuntime. User ID: %s. Username: %s.",
            self._user_id,
            self._username,
        )

        # Setup workspace
        self._temp_workspace: str | None = workspace_base
        self.status_callback = status_callback

        # ActionExecutor instance (created in connect()).  Typed against the
        # protocol so this driver does not depend on the concrete class at
        # runtime — any executor satisfying the protocol works.
        self._executor: ActionExecutorProtocol | None = None

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
            workspace_base=workspace_base,
        )

    async def connect(self) -> None:
        """Initialize ActionExecutor in-process."""
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
                logger.warning("Plugin %s not found, skipping", plugin_req.name)

        # Create ActionExecutor directly (no subprocess!)
        logger.info("Creating ActionExecutor in-process...")
        if self._temp_workspace is None:
            self._setup_workspace_directory()
        work_dir = self._temp_workspace
        # Ensure workspace directory exists
        if work_dir is None:
            raise ValueError("Workspace directory must be set")
        os.makedirs(work_dir, exist_ok=True)

        self._executor = ActionExecutor(
            plugins_to_load=plugins_to_load,
            work_dir=work_dir,
            username=self._username or "forge",
            user_id=self._user_id,
            enable_browser=self.config.enable_browser,
            browsergym_eval_env=self.config.runtime_config.browsergym_eval_env,
            tool_registry=self._tool_registry,  # Pass ToolRegistry for cross-platform support
        )

        # Initialize ActionExecutor (this sets up bash, plugins, etc.)
        logger.info("Initializing ActionExecutor...")
        await self._executor.ainit()

        self.set_runtime_status(RuntimeStatus.READY)
        self._runtime_initialized = True

        # Populate the capability matrix once at startup
        self.capabilities = detect_capabilities(
            enable_browser=self.config.enable_browser,
        )
        if self.capabilities.missing_tools:
            logger.warning(
                "Missing expected tools: %s",
                ", ".join(self.capabilities.missing_tools),
            )

        elapsed = time.time() - start_time
        logger.info("🚀 In-process runtime ready in %.2fs", elapsed)

    def _setup_workspace_directory(self) -> None:
        """Create temporary workspace directory."""
        if self._temp_workspace is None:
            # If workspace_base is provided in init, use it; otherwise create temp
            base = getattr(self, "workspace_base", None)
            if base:
                self._temp_workspace = base
                os.makedirs(base, exist_ok=True)
            else:
                self._temp_workspace = tempfile.mkdtemp(
                    prefix=f"FORGE_workspace_{self.sid}_"
                )
            self.config.workspace_mount_path_in_runtime = self._temp_workspace
            # NOTE: We intentionally do NOT call os.chdir() here.
            # Mutating the process-global cwd is unsafe when multiple
            # sessions or concurrent operations share the same process.
            # Instead, the workspace path is passed to ActionExecutor's
            # work_dir parameter and each command runs in that directory.
            logger.info("Using workspace: %s", self._temp_workspace)
            return

        self.config.workspace_mount_path_in_runtime = self._temp_workspace

    async def execute_action(self, action: Any) -> Observation:
        """Execute action directly via ActionExecutor."""
        if not self._runtime_initialized or self._executor is None:
            raise AgentRuntimeDisconnectedError("Runtime not initialized")

        # Security Check
        try:
            risk = await self._security_analyzer.security_risk(action)
            if risk == ActionSecurityRisk.HIGH:
                from backend.events.observation import ErrorObservation

                return ErrorObservation(
                    content="Security Violation: Action blocked by security analyzer (High Risk)"
                )
        except Exception as e:
            logger.warning("Security analysis failed: %s", e)

        return await self._executor.run_action(action)

    def hard_kill(self) -> None:
        """Best-effort immediate termination of processes started by this runtime."""
        if self._executor is None:
            return
        try:
            call_async_from_sync(self._executor.hard_kill, 5.0)
        except Exception:
            logger.debug("LocalRuntimeInProcess hard_kill failed", exc_info=True)

    def run(self, action: CmdRunAction) -> Observation:
        """Execute command via ActionExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError("Runtime not initialized")
        return call_async_from_sync(self._executor.run, 15.0, action)

    def read(self, action: FileReadAction) -> Observation:
        """Read file via ActionExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError("Runtime not initialized")
        return call_async_from_sync(self._executor.read, 15.0, action)

    def write(self, action: FileWriteAction) -> Observation:
        """Write file via ActionExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError("Runtime not initialized")
        return call_async_from_sync(self._executor.write, 15.0, action)

    def edit(self, action: FileEditAction) -> Observation:
        """Edit file via ActionExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError("Runtime not initialized")
        return call_async_from_sync(self._executor.edit, 15.0, action)

    def browse(self, action: BrowseURLAction) -> Observation:
        """Browse URL via ActionExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError("Runtime not initialized")
        return call_async_from_sync(self._executor.browse, 15.0, action)

    def browse_interactive(self, action: BrowseInteractiveAction) -> Observation:
        """Browse interactively via ActionExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError("Runtime not initialized")
        return call_async_from_sync(self._executor.browse_interactive, 15.0, action)

    def list_files(self, path: str | None = None, recursive: bool = False) -> list[str]:
        """List files in the specified path."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError("Runtime not initialized")

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
            logger.warning("Invalid path for list_files: %s - %s", full_path, e)
            return []

        # Get sorted directory entries
        try:
            entries = os.listdir(full_path)
        except (OSError, NotADirectoryError) as e:
            # Path is not a directory or cannot be listed
            logger.warning("Cannot list directory %s: %s", full_path, e)
            return []

        directories, files = self._process_directory_entries(
            full_path, entries, path or "", recursive
        )

        directories.sort(key=lambda s: s.lower())
        files.sort(key=lambda s: s.lower())

        return directories + files

    def _resolve_list_files_path(self, path: str | None) -> str:
        """Resolve the path for file listing."""
        assert self._executor is not None, "Runtime not initialized"
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
            entry_relative = entry.lstrip("/").split("/")[-1]
            full_entry_path = os.path.join(full_path, entry_relative)

            try:
                if os.path.exists(full_entry_path):
                    if os.path.isdir(full_entry_path):
                        directories.append(entry.rstrip("/") + "/")
                        if recursive:
                            sub_path = os.path.join(path, entry) if path else entry
                            sub_files = self.list_files(sub_path, recursive=True)
                            files.extend([f"{entry}/{f}" for f in sub_files])
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
            raise AgentRuntimeDisconnectedError("Runtime not initialized")
        # For in-process, just use shutil
        import shutil

        if os.path.isdir(host_src):
            if recursive:
                shutil.copytree(host_src, runtime_dest, dirs_exist_ok=True)
            else:
                raise ValueError("Cannot copy directory without recursive=True")
        else:
            os.makedirs(os.path.dirname(runtime_dest), exist_ok=True)
            shutil.copy2(host_src, runtime_dest)

    def copy_from(self, path: str) -> Any:
        """Copy file from runtime to host."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError("Runtime not initialized")
        # For in-process, file is already accessible
        return Path(path)  # pylint: disable=redefined-outer-name,reimported

    def get_mcp_config(self, extra_stdio_servers: list[Any] | None = None) -> Any:
        """Get MCP configuration."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError("Runtime not initialized")
        # MCP is handled by ActionExecutor if available
        return self.config.mcp if hasattr(self.config, "mcp") else None

    async def call_tool_mcp(self, action: MCPAction) -> Observation:
        """Call MCP tool via ActionExecutor."""
        if self._executor is None:
            raise AgentRuntimeDisconnectedError("Runtime not initialized")
        # ActionExecutor handles MCP through run_action
        return await self._executor.run_action(action)

    def close(self) -> None:
        """Clean up runtime resources."""
        if self._executor:
            # ActionExecutor cleanup (this is synchronous)
            if hasattr(self._executor, "close"):
                self._executor.close()
            self._executor = None

        # Wait a bit for processes to release file handles before removing workspace
        import time

        time.sleep(0.5)  # Brief wait for Windows file handle release

        # Clean up workspace with retry logic
        if self._temp_workspace and os.path.exists(self._temp_workspace):
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
                            "Failed to remove workspace %s after %s attempts: %s",
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
        return Path(self._temp_workspace) if self._temp_workspace else Path(".")  # pylint: disable=redefined-outer-name,reimported

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
        from backend.runtime.utils.tool_registry import ToolRegistry

        logger.info("Initializing ToolRegistry for cross-platform support...")
        self._tool_registry = ToolRegistry()

        # Initialize Security Analyzer for default safety
        self._security_analyzer = SecurityAnalyzer()

        # Check for required tools
        if not self._tool_registry.has_git:
            logger.error(
                "Git is required but not found. Please install Git from: https://git-scm.com/downloads"
            )

        # Log platform-specific warnings
        if self.is_windows:
            logger.info(
                "Running on Windows with %s shell",
                self._tool_registry.shell_type,
            )
        else:
            if not self._tool_registry.has_tmux:
                logger.warning(
                    "tmux not found. Using simple subprocess-based Bash session. "
                    "Install tmux for better command management: sudo apt install tmux"
                )

    def _sanitize_config(self) -> None:
        """Sanitize configuration and ensure compatibility."""
        security_cfg = getattr(self.config, "security", None)
        if not isinstance(security_cfg, SecurityConfig):
            self.config.security = SecurityConfig()
