"""Runtime environment and execution infrastructure.

Classes:
    Runtime

Functions:
    runtime_initialized
    setup_initial_env
    close
    log
    set_runtime_status
"""

from __future__ import annotations

import asyncio
import atexit
import copy
import os
from abc import abstractmethod
from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Self, cast

import httpx

from backend.core.exceptions import AgentRuntimeDisconnectedError
from backend.core.logger import forge_logger as logger
from backend.events import EventSource, EventStream, EventStreamSubscriber
from backend.events.action import (
    Action,
    AgentThinkAction,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
    TaskTrackingAction,
)
from backend.events.action.mcp import MCPAction
from backend.events.observation import (
    AgentThinkObservation,
    CmdOutputObservation,
    ErrorObservation,
    FileWriteObservation,
    NullObservation,
    Observation,
)
from backend.events.serialization.action import ACTION_TYPE_TO_CLASS
from backend.api.provider_handler import ProviderHandler
from backend.runtime.capabilities import RuntimeCapabilities
from backend.runtime.command_timeout import CommandTimeoutMixin
from backend.runtime.env_manager import EnvManagerMixin
from backend.runtime.git_setup import GitSetupMixin
from backend.runtime.playbook_loader import PlaybookLoaderMixin
from backend.runtime.plugins import PluginRequirement
from backend.core.enums import RuntimeStatus
from backend.runtime.security_enforcement import SecurityEnforcementMixin
from backend.runtime.task_tracking import TaskTrackingMixin
from backend.runtime.utils.edit import FileEditRuntimeMixin
from backend.runtime.utils.git_handler import CommandResult, GitHandler
from backend.security import SecurityAnalyzer, options
from backend.utils.async_utils import (
    GENERAL_TIMEOUT,
    call_async_from_sync,
    call_sync_from_async,
    run_or_schedule,
)

if TYPE_CHECKING:
    from pydantic import SecretStr
    from backend.core.config import ForgeConfig, RuntimeConfig
    from backend.core.config.mcp_config import MCPConfig, MCPStdioServerConfig
    from backend.events.event import Event
    from backend.playbook_engine import BasePlaybook
    from backend.core.provider_types import (
        ProviderTokenType,
        ProviderToken,
        ProviderType,
    )
    from backend.llm.llm_registry import LLMRegistry
else:
    BasePlaybook = Any


# Action types handled by the agent system, NOT the runtime.
# Defined once here to avoid duplication across run_action/validate_action.
AGENT_LEVEL_ACTIONS: frozenset[str] = frozenset(
    {
        "change_agent_state",
        "message",
        "recall",
        "think",
        "finish",
        "reject",
        "delegate",
        "condensation",
        "condensation_request",
        "task_tracking",
        "system",
    }
)


def _default_env_vars(runtime_config: RuntimeConfig) -> dict[str, str]:
    """Build default environment variables for runtime from host environment.

    Copies environment variables prefixed with RUNTIME_ENV_ into the runtime,
    removing the prefix. Also sets auto-lint flag if enabled.

    Args:
        runtime_config: Runtime configuration settings

    Returns:
        Dictionary of environment variables for the runtime

    """
    ret = {}
    for key in os.environ:
        if key.startswith("RUNTIME_ENV_"):
            runtime_key = key.removeprefix("RUNTIME_ENV_")
            ret[runtime_key] = os.environ[key]
    if runtime_config.enable_auto_lint:
        ret["ENABLE_AUTO_LINT"] = "true"
    return ret


def _normalize_provider_tokens(
    tokens: ProviderTokenType | None,
) -> MappingProxyType[ProviderType, ProviderToken]:
    """Ensure provider tokens are stored as an immutable mapping."""
    if isinstance(tokens, MappingProxyType):
        return tokens
    if tokens is None:
        return MappingProxyType({})
    return MappingProxyType(dict(tokens))


class Runtime(
    EnvManagerMixin,
    GitSetupMixin,
    PlaybookLoaderMixin,
    TaskTrackingMixin,
    FileEditRuntimeMixin,
    CommandTimeoutMixin,
    SecurityEnforcementMixin,
):
    """Abstract base class for agent runtime environments.

    This is an extension point in Forge that allows applications to customize how
    agents interact with the external environment. The runtime provides an environment with:
    - Bash shell access
    - Browser interaction
    - Filesystem operations
    - Git operations
    - Environment variable management

    Applications can substitute their own implementation by:
    1. Creating a class that inherits from Runtime
    2. Implementing all required methods
    3. Setting the runtime name in configuration or using get_runtime_cls()

    The class is instantiated via get_impl() in get_runtime_cls().

    Built-in implementations include:
    - LocalRuntime: Local execution on the host machine (default)

    Args:
        sid: Session ID that uniquely identifies the current user session

    """

    sid: str
    config: ForgeConfig
    initial_env_vars: dict[str, str]
    attach_to_existing: bool
    status_callback: Callable[[str, RuntimeStatus, str], None] | None
    runtime_status: RuntimeStatus | None
    _runtime_initialized: bool = False
    security_analyzer: SecurityAnalyzer | None = None
    workspace_base: str | None = None
    capabilities: RuntimeCapabilities | None = None
    """Frozen capability snapshot, populated during ``connect()``."""

    def __init__(
        self,
        config: ForgeConfig,
        event_stream: EventStream | None,
        llm_registry: LLMRegistry,
        sid: str = "default",
        plugins: list[PluginRequirement] | None = None,
        env_vars: dict[str, str] | None = None,
        status_callback: Callable[[str, RuntimeStatus, str], None] | None = None,
        attach_to_existing: bool = False,
        headless_mode: bool = False,
        user_id: str | None = None,
        vcs_provider_tokens: ProviderTokenType | None = None,
        workspace_base: str | None = None,
    ) -> None:
        """Initialize runtime state, subscriptions, plugins, and provider credentials."""
        self.git_handler = GitHandler(
            execute_shell_fn=self._execute_shell_fn_git_handler,
            create_file_fn=self._create_file_fn_git_handler,
        )
        self.sid = sid
        self.event_stream = event_stream
        self.workspace_base = workspace_base
        if event_stream:
            # Unsubscribe first if already exists (handles reconnection cases)
            try:
                event_stream.unsubscribe(EventStreamSubscriber.RUNTIME, self.sid)
            except Exception:
                pass  # Ignore if not subscribed
            event_stream.subscribe(
                EventStreamSubscriber.RUNTIME, self.on_event, self.sid
            )
        self.plugins = (
            copy.deepcopy(plugins) if plugins is not None and plugins else []
        )
        self.status_callback = status_callback
        self.attach_to_existing = attach_to_existing
        self.config = copy.deepcopy(config)
        atexit.register(self.close)
        self.initial_env_vars = _default_env_vars(config.runtime_config)
        if env_vars is not None:
            self.initial_env_vars.update(env_vars)
        provider_tokens = _normalize_provider_tokens(vcs_provider_tokens)
        self.provider_handler = ProviderHandler(
            provider_tokens=provider_tokens,
        )
        raw_env_vars = cast(
            dict[str, str],
            call_async_from_sync(
                self.provider_handler.get_env_vars,
                GENERAL_TIMEOUT,
                True,
            ),
        )
        self.initial_env_vars.update(raw_env_vars)
        FileEditRuntimeMixin.__init__(
            self,
            enable_llm_editor=getattr(
                config.get_agent_config(), "enable_llm_editor", False
            ),
            llm_registry=llm_registry,
        )
        self.user_id = user_id
        self.vcs_provider_tokens = provider_tokens

        # 🧹 CRITICAL FIX: Process manager for tracking and cleaning up long-running processes
        from backend.runtime.utils.process_manager import ProcessManager

        self.process_manager = ProcessManager()
        self.runtime_status = None
        self.security_analyzer = None
        if self.config.security.security_analyzer:
            # SecurityAnalyzers is a dict-like object in options module
            analyzer_cls = getattr(options, "SecurityAnalyzers", {}).get(  # type: ignore[attr-defined]
                self.config.security.security_analyzer, SecurityAnalyzer
            )
            self.security_analyzer = analyzer_cls()
            logger.debug(
                "Security analyzer %s initialized for runtime %s",
                analyzer_cls.__name__,
                self.sid,
            )

    @property
    def runtime_initialized(self) -> bool:
        """Check if runtime has completed initialization.

        Returns:
            True if runtime is initialized and ready

        """
        return self._runtime_initialized

    def setup_initial_env(self) -> None:
        """Set up initial environment variables and git configuration.

        Skipped if attaching to existing runtime. Adds initial env vars,
        runtime startup vars, and configures git user settings.
        """
        if self.attach_to_existing:
            return
        logger.debug("Adding env vars: %s", self.initial_env_vars.keys())
        self.add_env_vars(self.initial_env_vars)
        if self.config.runtime_config.runtime_startup_env_vars:
            self.add_env_vars(self.config.runtime_config.runtime_startup_env_vars)
        self._setup_git_config()

    def close(self) -> None:
        """This should only be called by conversation manager or closing the session.

        If called for instance by error handling, it could prevent recovery.
        """
        if not self._should_cleanup_processes():
            return
        try:
            logger.info(
                "🧹 Cleaning up %s long-running processes",
                self.process_manager.count(),
            )
            self._cleanup_processes()
        except Exception as e:
            logger.error("Failed to cleanup processes: %s", e)

    def _should_cleanup_processes(self) -> bool:
        return hasattr(self, "process_manager") and self.process_manager.count() > 0

    def _cleanup_processes(self) -> None:
        loop, created = self._resolve_event_loop()
        if loop and loop.is_running():
            from backend.utils.async_utils import create_tracked_task

            create_tracked_task(
                self.process_manager.cleanup_all(runtime=self),
                name="process-cleanup",
            )
            return
        self._run_cleanup_synchronously(loop, created)

    def _resolve_event_loop(self) -> tuple[asyncio.AbstractEventLoop | None, bool]:
        import asyncio

        try:
            loop = asyncio.get_running_loop()
            return loop, False
        except RuntimeError:
            pass
        try:
            loop = asyncio.get_event_loop()
            return loop, False
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return loop, True

    def _run_cleanup_synchronously(
        self, loop: asyncio.AbstractEventLoop | None, created: bool
    ) -> None:
        import asyncio

        if loop is None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            created = True
        try:
            loop.run_until_complete(self.process_manager.cleanup_all(runtime=self))
        finally:
            self._close_loop_if_needed(loop, created)

    def _close_loop_if_needed(
        self, loop: asyncio.AbstractEventLoop, created: bool
    ) -> None:
        import asyncio

        if not created:
            return
        try:
            if loop and not loop.is_closed() and loop is not asyncio.get_running_loop():
                loop.close()
        except RuntimeError:
            pass

    @classmethod
    async def delete(cls, conversation_id: str) -> None:
        """Delete runtime resources associated with a conversation.

        Args:
            conversation_id: ID of conversation to clean up

        """

    def log(self, level: str, message: str) -> None:
        """Log message with runtime context.

        Args:
            level: Log level ('debug', 'info', 'warning', 'error')
            message: Message to log

        """
        message = f"[runtime {self.sid}] {message}"
        getattr(logger, level)(message, stacklevel=2)

    def set_runtime_status(
        self, runtime_status: RuntimeStatus, msg: str = "", level: str = "info"
    ) -> None:
        """Sends a status message if the callback function was provided."""
        self.runtime_status = runtime_status
        if self.status_callback:
            self.status_callback(level, runtime_status, msg)

    def on_event(self, event: Event) -> None:
        """Handle incoming events (primarily actions from agent).

        Args:
            event: Event to process

        """
        if isinstance(event, Action):
            run_or_schedule(self._handle_action(event))

    async def _export_latest_git_provider_tokens(self, event: Action) -> None:
        """Refresh runtime provider tokens when agent attemps to run action with provider token."""
        providers_called = ProviderHandler.check_cmd_action_for_provider_token_ref(
            event
        )
        if not providers_called:
            return
        provider_handler = ProviderHandler(
            provider_tokens=self.vcs_provider_tokens,
        )
        logger.info("Fetching latest provider tokens for runtime")
        env_vars = cast(
            "dict[ProviderType, SecretStr]",
            await provider_handler.get_env_vars(
                expose_secrets=False,
            ),
        )
        if not env_vars:
            return
        try:
            if self.event_stream:
                await provider_handler.set_event_stream_secrets(
                    self.event_stream, env_vars=env_vars
                )
            self.add_env_vars(provider_handler.expose_env_vars(env_vars))
        except Exception:
            logger.warning("Failed to export latest provider tokens to runtime")

    async def _execute_action(self, event: Action) -> Observation:
        """Execute action and return observation.

        Args:
            event: Action to execute

        Returns:
            Observation from action execution

        """
        await self._export_latest_git_provider_tokens(event)

        if isinstance(event, MCPAction):
            # Centralised MCP guard: if capabilities have been probed and
            # MCP is unsupported, short-circuit with a clear error rather
            # than letting driver-specific code fail in unpredictable ways.
            if self.capabilities is not None and not self.capabilities.can_mcp:
                return ErrorObservation(
                    content=(
                        "MCP tools are not available in this environment "
                        f"(platform={self.capabilities.platform}).  "
                        "Set FORGE_ENABLE_WINDOWS_MCP=1 to override on Windows."
                    )
                )
            return await self.call_tool_mcp(event)
        return await call_sync_from_async(self.run_action, event)

    def _handle_runtime_error(
        self, event: Action, error: Exception, is_network_error: bool = False
    ) -> None:
        """Handle runtime error during action execution.

        Args:
            event: Action that caused error
            error: Exception raised
            is_network_error: Whether this is a network/disconnection error

        """
        runtime_status = (
            RuntimeStatus.ERROR_RUNTIME_DISCONNECTED
            if is_network_error
            else RuntimeStatus.ERROR
        )
        error_message = f"{type(error).__name__}: {error!s}"
        self.log("error", f"Unexpected error while running action: {error_message}")
        self.log("error", f"Problematic action: {event!s}")
        self.set_runtime_status(runtime_status, error_message, level="error")

    def _process_observation(self, observation: Observation, event: Action) -> bool:
        """Process observation result and add to event stream.

        Args:
            observation: Observation to process
            event: Source action

        Returns:
            True if observation should be added to stream, False otherwise

        """
        observation.cause = event.id
        observation.tool_call_metadata = event.tool_call_metadata

        # Attach a structured result payload for downstream consumers.
        # This avoids fragile parsing of free-form observation content.
        try:
            exit_code: int | None = getattr(observation, "exit_code", None)
        except Exception:
            exit_code = None

        observation.tool_result = {
            "ok": not isinstance(observation, ErrorObservation),
            "retryable": isinstance(observation, ErrorObservation),
            "exit_code": exit_code,
            "action": getattr(event, "action", None),
            "observation": getattr(observation, "observation", None),
        }

        if isinstance(observation, NullObservation):
            return False

        return True

    async def _handle_action(self, event: Action) -> None:
        """Handle action execution with timeout, error handling, and observation processing."""
        self._set_action_timeout(event)

        assert event.timeout is not None or (
            isinstance(event, CmdRunAction)
            and self._is_long_running_command(event.command)
        )

        try:
            observation = await self._execute_action(event)
        except PermissionError as e:
            observation = ErrorObservation(content=str(e))
        except (httpx.NetworkError, AgentRuntimeDisconnectedError) as e:
            self._handle_runtime_error(event, e, is_network_error=True)
            return
        except Exception as e:
            self._handle_runtime_error(event, e, is_network_error=False)
            return

        if not self._process_observation(observation, event):
            return

        source = event.source or EventSource.AGENT
        if self.event_stream:
            self.event_stream.add_event(observation, source)

    def run_action(self, action: Action) -> Observation:
        """Run an action and return the resulting observation.

        If the action is not runnable in any runtime, a NullObservation is returned.
        If the action is not supported by the current runtime, an ErrorObservation is returned.
        """
        # Handle special action types
        if isinstance(action, AgentThinkAction):
            return AgentThinkObservation("Your thought has been logged.")

        if isinstance(action, TaskTrackingAction):
            return self._handle_task_tracking_action(action)

        # Check confirmation state
        confirmation_result = self._check_action_confirmation(action)
        if confirmation_result is not None:
            return confirmation_result

        # Security enforcement — classify risk and gate dangerous actions
        enforcement_result = self._enforce_security(action)
        if enforcement_result is not None:
            return enforcement_result

        # Validate action type and runtime support
        validation_result = self._validate_action(action)
        if validation_result is not None:
            return validation_result

        # Check if this is an agent-level action that should not be executed by runtime
        action_type = action.action

        if action_type in AGENT_LEVEL_ACTIONS:
            # These actions are handled by the agent system, not the runtime
            return NullObservation(content="")

        # Execute the action (synchronous path)
        observation = self._execute_action_sync(action)

        # Verify critical actions (Layer 3: Post-Action Verification)
        verification_obs = self._verify_action_if_needed(action, observation)
        if verification_obs:
            # Return combined observation with verification result
            return verification_obs

        return observation

    def _verify_action_if_needed(
        self, action: Action, observation: Observation
    ) -> Observation | None:
        """Verify critical actions to prevent hallucinations (Layer 3).

        Args:
            action: The action that was executed
            observation: The observation returned from execution

        Returns:
            Enhanced observation with verification, or None if no verification needed

        """
        # Only verify file operations
        if not isinstance(action, (FileEditAction, FileWriteAction)):
            return None

        # Skip verification if action already failed
        if isinstance(observation, ErrorObservation):
            return None

        try:
            file_path = action.path
            file_on_disk = Path(file_path)

            if not file_on_disk.is_file():
                logger.error(
                    "VERIFICATION FAILURE: File %s missing after file operation",
                    file_path,
                )
                error_msg = (
                    "❌ CRITICAL VERIFICATION FAILURE:\n"
                    f"File {file_path} does NOT exist after file operation execution.\n"
                    "This indicates an execution failure or stale workspace base.\n\n"
                    f"Original observation: {observation.content[:200]}\n\n"
                    "Please retry the file creation."
                )
                return ErrorObservation(content=error_msg)

            # File exists - count lines (best-effort; don't fail if unreadable)
            try:
                with file_on_disk.open("r", encoding="utf-8", errors="replace") as f:
                    line_count = sum(1 for _ in f)
            except Exception:
                line_count = None

            if line_count is not None:
                enhanced_content = (
                    f"{observation.content}\n\n"
                    f"✅ VERIFICATION: File {file_path} confirmed to exist ({line_count} lines)"
                )
                return FileWriteObservation(content=enhanced_content, path=file_path)

            return None

        except Exception as e:
            logger.warning("Verification error for %s: %s", action.path, e)
            # Don't fail the action due to verification errors
            return None

    def _validate_action(self, action: Action) -> Observation | None:
        """Validate action type and runtime support."""
        action_type = action.action

        if action_type not in ACTION_TYPE_TO_CLASS:
            return ErrorObservation(f"Action {action_type} does not exist.")

        # Agent-level actions that should not be executed by runtime
        if action_type in AGENT_LEVEL_ACTIONS:
            # These actions are handled by the agent system, not the runtime
            return None

        if not hasattr(self, action_type):
            return ErrorObservation(
                f"Action {action_type} is not supported in the current runtime."
            )

        return None

    def _execute_action_sync(self, action: Action) -> Observation:
        """Execute the validated action (synchronous internal path)."""
        action_type = action.action
        return getattr(self, action_type)(action)

    def __enter__(self) -> Self:
        """Enter runtime context manager.

        Returns:
            Self for context manager protocol

        """
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """Exit runtime context manager, ensuring cleanup.

        Args:
            exc_type: Exception type if an error occurred
            exc_value: Exception value if an error occurred
            traceback: Traceback if an error occurred

        """
        self.close()

    @abstractmethod
    async def connect(self) -> None:
        """Connect to the runtime environment.

        Must be implemented by subclasses to establish connection to
        the execution environment (local process, subprocess, etc.).
        """

    @abstractmethod
    def get_mcp_config(
        self, extra_servers: list[Any] | None = None
    ) -> MCPConfig:
        """Get MCP configuration for this runtime."""

    @abstractmethod
    def run(self, action: CmdRunAction) -> Observation:
        """Execute a bash/shell command in the runtime environment."""

    @abstractmethod
    def read(self, action: FileReadAction) -> Observation:
        """Read file contents from the runtime filesystem."""

    @abstractmethod
    def write(self, action: FileWriteAction) -> Observation:
        """Write content to a file in the runtime filesystem."""

    @abstractmethod
    def edit(self, action: FileEditAction) -> Observation:
        """Edit file using search/replace or other edit operations."""

    @abstractmethod
    def copy_to(
        self, host_src: str, runtime_dest: str, recursive: bool = False
    ) -> None:
        """Copy files from host into the runtime environment."""
        raise NotImplementedError

    @abstractmethod
    def copy_from(self, path: str) -> Path:
        """Copy files from the runtime environment to the host."""
        raise NotImplementedError

    @abstractmethod
    def list_files(self, path: str, recursive: bool = False) -> list[str]:
        """List files within the runtime environment."""
        raise NotImplementedError

    @abstractmethod
    async def call_tool_mcp(self, action: MCPAction) -> Observation:
        """Call an MCP (Model Context Protocol) tool.

        Args:
            action: MCP action with tool name and arguments

        Returns:
            Observation with tool execution results

        """

    def get_git_diff(self, file_path: str, cwd: str) -> dict[str, str]:
        """Get git diff for a specific file.

        Args:
            file_path: Path to file to diff
            cwd: Working directory for git command

        Returns:
            Dictionary with diff information

        """
        self.git_handler.set_cwd(cwd)
        return self.git_handler.get_git_diff(file_path)

    def get_workspace_branch(self, primary_repo_path: str | None = None) -> str | None:
        """Get the current branch of the workspace.

        Args:
            primary_repo_path: Path to the primary repository within the workspace.
                              If None, uses the workspace root.

        Returns:
            str | None: The current branch name, or None if not a git repository or error occurs.

        """
        if primary_repo_path:
            git_cwd = str(self.workspace_root / primary_repo_path)
        else:
            git_cwd = str(self.workspace_root)
        self.git_handler.set_cwd(git_cwd)
        return self.git_handler.get_current_branch()

    @property
    def session_api_key(self) -> str | None:
        """Return a session API key if configured for the runtime (default: None)."""
        return None

    def _execute_shell_fn_git_handler(
        self, command: str, cwd: str | None
    ) -> CommandResult:
        """This function is used by the GitHandler to execute shell commands."""
        obs = self.run(
            CmdRunAction(command=command, is_static=True, hidden=True, cwd=cwd)
        )
        exit_code = 0
        if isinstance(obs, ErrorObservation):
            exit_code = -1
        else:
            exit_attr = getattr(obs, "exit_code", None)
            if isinstance(exit_attr, int):
                exit_code = exit_attr
        content = getattr(obs, "content", "")
        return CommandResult(content=content, exit_code=exit_code)

    def _create_file_fn_git_handler(self, path: str, content: str) -> int:
        """This function is used by the GitHandler to create files in the runtime."""
        obs = self.write(FileWriteAction(path=path, content=content))
        return -1 if isinstance(obs, ErrorObservation) else 0

    def additional_agent_instructions(self) -> str:
        """Provide runtime-specific instructions appended to agent prompts."""
        return ""

    def subscribe_to_shell_stream(
        self, callback: Callable[[str], None] | None = None
    ) -> bool:
        """Subscribe to shell command output stream.

        This method is meant to be overridden by runtime implementations
        that want to stream shell command output to external consumers.

        Args:
            callback: A function that will be called with each line of output from shell commands.
                     If None, any existing subscription will be removed.

        Returns False by default.

        """
        return False

    @classmethod
    def setup(cls, config: ForgeConfig, headless_mode: bool = False) -> None:
        """Set up the environment for runtimes to be created."""

    @classmethod
    def teardown(cls, config: ForgeConfig) -> None:
        """Tear down the environment in which runtimes are created."""
