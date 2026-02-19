"""Runtime session orchestration for agents, including startup and lifecycle."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from backend.controller import AgentController
from backend.controller.agent_controller import ControllerConfig
from backend.controller.replay import ReplayManager
from backend.controller.state.state import State
from backend.core.config import AgentConfig, ForgeConfig, LLMConfig
from backend.core.errors import (
    RuntimeConnectError,
    SessionAlreadyActiveError,
    SessionStartupError,
)
from backend.core.logger import ForgeLoggerAdapter
from backend.core.schemas import AgentState
from backend.events.action import ChangeAgentStateAction, MessageAction
from backend.events.event import Event, EventSource
from backend.events.observation import ErrorObservation
from backend.core.provider_types import (
    CustomSecretsType,
    ProviderTokenType,
    CustomSecret,
)
from backend.mcp import add_mcp_tools_to_agent
from backend.memory.agent_memory import Memory
from backend.runtime import RuntimeAcquireResult, runtime_orchestrator
from backend.server.shared import get_event_service_adapter
from backend.server.types import LLMAuthenticationError
from backend.server.utils.error_formatter import format_error_for_user
from backend.storage.data_models.user_secrets import UserSecrets
from backend.utils.async_utils import EXECUTOR, call_sync_from_async
from backend.utils.shutdown_listener import should_continue

from .constants import (
    WAIT_TIME_BEFORE_CLOSE,
    WAIT_TIME_BEFORE_CLOSE_INTERVAL,
)

if TYPE_CHECKING:
    from logging import LoggerAdapter

    from backend.controller.agent import Agent
    from backend.events.stream import EventStream
    from backend.instruction.playbook import BasePlaybook
    from backend.llm.llm_registry import LLMRegistry
    from backend.runtime.base import Runtime
    from backend.server.services.conversation_stats import ConversationStats
    from backend.storage.data_models.settings import Settings
    from backend.storage.files import FileStore
else:
    # Runtime imports - these are only used at runtime, not for type checking
    EventStream = object  # type: ignore[assignment,misc]
    LLMRegistry = object  # type: ignore[assignment,misc]
    FileStore = object  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Typed startup lifecycle
# ---------------------------------------------------------------------------


class StartupPhase(str, Enum):
    """Named phases of ``AgentSession.start()``.

    Tracking the current phase gives callers (and logs) clear visibility
    into *where* a failure happened.
    """

    VALIDATE = "validate"
    AUTH = "auth"
    RUNTIME = "runtime"
    MEMORY = "memory"
    CONTROLLER = "controller"
    EXECUTION = "execution"
    PLUGIN = "plugin"
    DONE = "done"


@dataclass
class StartupContext:
    """Typed container replacing the old ad-hoc ``startup_state`` dict.

    Attributes are populated incrementally as each phase completes.
    """

    started_at: float = field(default_factory=time.time)
    phase: StartupPhase = StartupPhase.VALIDATE
    finished: bool = False
    runtime_connected: bool = False
    restored_state: bool = False
    error_msg: str | None = None
    error_exception: Exception | None = None
    error_context: dict[str, Any] | None = None

    @property
    def duration(self) -> float:
        return time.time() - self.started_at

    def fail(
        self,
        msg: str,
        exc: Exception | None = None,
        ctx: dict[str, Any] | None = None,
    ) -> None:
        self.error_msg = msg
        self.error_exception = exc
        if ctx:
            self.error_context = ctx


class AgentSession:
    """Represents a session with an Agent.

    Attributes:
        controller: The AgentController instance for controlling the agent.

    """

    sid: str
    user_id: str | None
    event_stream: EventStream
    llm_registry: LLMRegistry
    file_store: FileStore
    controller: AgentController | None = None
    runtime: Runtime | None = None
    memory: Memory | None = None
    _starting: bool = False
    _startup_failed: bool = False
    _started_at: float = 0
    _closed: bool = False
    loop: asyncio.AbstractEventLoop | None = None
    logger: LoggerAdapter

    def __init__(
        self,
        sid: str,
        file_store: FileStore,
        llm_registry: LLMRegistry,
        conversation_stats: ConversationStats,
        status_callback: Callable | None = None,
        user_id: str | None = None,
    ) -> None:
        """Initializes a new instance of the Session class.

        Parameters:
        - sid: The session ID
        - file_store: Instance of the FileStore
        """
        self.sid = sid
        adapter = get_event_service_adapter()
        session_info = adapter.start_session(
            session_id=sid,
            user_id=user_id,
            labels={"source": "agent_session"},
        )
        self.event_stream = adapter.get_event_stream(session_info["session_id"])
        self.file_store = file_store
        self._status_callback = status_callback
        self.user_id = user_id
        self.logger = ForgeLoggerAdapter(extra={"session_id": sid, "user_id": user_id})
        self.llm_registry = llm_registry
        self.conversation_stats = conversation_stats
        self._runtime_acquire_result: RuntimeAcquireResult | None = None
        self._repo_directory: str | None = None
        self._selected_repository: str | None = None
        self._selected_branch: str | None = None

    async def start(
        self,
        runtime_name: str,
        config: ForgeConfig,
        agent: Agent,
        max_iterations: int,
        vcs_provider_tokens: ProviderTokenType | None = None,
        custom_secrets: CustomSecretsType | None = None,
        max_budget_per_task: float | None = None,
        agent_to_llm_config: dict[str, LLMConfig] | None = None,
        agent_configs: dict[str, AgentConfig] | None = None,
        selected_repository: str | None = None,
        selected_branch: str | None = None,
        initial_message: MessageAction | None = None,
        conversation_instructions: str | None = None,
        replay_json: str | None = None,
        user_settings: Settings | None = None,
    ) -> None:
        """Starts the Agent session.

        Phases (tracked via :class:`StartupContext`):
          1. VALIDATE — guard against double-start / closed session
          2. AUTH     — validate API keys for all configured agents
          3. RUNTIME  — create and connect the runtime environment
          4. MEMORY   — set up memory, knowledge base, MCP tools
          5. CONTROLLER — create AgentController (or replay)
          6. EXECUTION — enqueue initial message / state change
          7. PLUGIN   — fire session_start plugin hook
          8. DONE
        """
        # Phase: VALIDATE
        if not self._validate_session_state():
            return

        ctx = self._initialize_session_startup()
        self._selected_repository = selected_repository
        self._selected_branch = selected_branch
        self.config = config

        try:
            # Phase: AUTH — validate API keys before starting anything slow
            ctx.phase = StartupPhase.AUTH
            await self._handle_auth_phase(agent_to_llm_config)

            # Phase: RUNTIME
            ctx.phase = StartupPhase.RUNTIME
            ctx.runtime_connected = await self._setup_runtime_and_providers(
                runtime_name,
                config,
                agent,
                vcs_provider_tokens,
                custom_secrets,
                selected_repository,
                selected_branch,
            )

            if not ctx.runtime_connected:
                msg = "Runtime failed to connect"
                self.logger.warning(
                    "Runtime failed to connect — skipping controller setup"
                )
                ctx.fail(msg)
                raise RuntimeConnectError(msg)

            # Phase: MEMORY
            ctx.phase = StartupPhase.MEMORY
            await self._setup_memory_and_mcp_tools(
                selected_repository,
                selected_branch,
                conversation_instructions,
                custom_secrets,
                config,
                agent,
                user_settings=user_settings,
            )

            # Phase: CONTROLLER
            ctx.phase = StartupPhase.CONTROLLER
            initial_message = await self._setup_controller_and_handle_replay(
                replay_json,
                initial_message,
                agent,
                config,
                max_iterations,
                max_budget_per_task,
                agent_to_llm_config,
                agent_configs,
            )

            # Phase: EXECUTION
            ctx.phase = StartupPhase.EXECUTION
            self.logger.info(
                "Starting agent execution; has_initial_message=%s",
                bool(initial_message),
                extra={"signal": "agent_start"},
            )
            self._start_agent_execution(initial_message)

            # Phase: PLUGIN
            ctx.phase = StartupPhase.PLUGIN
            await self._handle_plugin_phase()

            ctx.phase = StartupPhase.DONE
            ctx.finished = True

        except Exception as e:
            if ctx.error_msg is None:
                ctx.fail(str(e), e)
            if ctx.error_exception is None:
                ctx.error_exception = e
            # Preserve error context on the exception for upstream handlers
            if ctx.error_context and hasattr(e, "__dict__"):
                e.__dict__.update(ctx.error_context)
            raise
        finally:
            await self._finalize_session_startup(ctx)

    def _validate_session_state(self) -> bool:
        """Validate that the session can be started."""
        if self.controller or self.runtime:
            msg = "Session already started. You need to close this session and start a new one."
            raise SessionAlreadyActiveError(msg)
        if self._closed:
            self.logger.warning("Session closed before starting")
            return False
        return True

    def _validate_api_key_for_model(self, llm_config: LLMConfig) -> None:
        """Validate API key requirements for the given model.

        Args:
            llm_config: LLM configuration containing API key and model name

        Raises:
            LLMAuthenticationError: If API key validation fails

        """
        # Validate API key presence and non-emptiness
        if not llm_config.api_key or llm_config.api_key.get_secret_value().isspace():
            model_name = llm_config.model or "the selected model"
            # Extract provider name from model if possible
            if "/" in model_name:
                model_name.split("/")[0].title()
            elif (
                "claude" in model_name.lower()
                or "gpt" in model_name.lower()
                or "openai" in model_name.lower()
                or "gemini" in model_name.lower()
            ):
                pass

            raise LLMAuthenticationError(
                "Error authenticating with the LLM provider. Please check your API key"
            )

    async def _handle_auth_phase(
        self, agent_to_llm_config: dict[str, LLMConfig] | None
    ) -> None:
        """Handle the AUTH phase of session startup."""
        if not agent_to_llm_config:
            return

        for agent_name, llm_config in agent_to_llm_config.items():
            try:
                self._validate_api_key_for_model(llm_config)
            except LLMAuthenticationError:
                # Add context for logging/audit
                self.logger.error(
                    "Authentication failed for agent %s (model: %s)",
                    agent_name,
                    llm_config.model,
                )
                raise

    def _determine_provider_name(self, model_name: str) -> str:
        """Determine the provider name from a model string."""
        if "/" in model_name:
            return model_name.split("/")[0].title()
        model_lower = model_name.lower()
        if "claude" in model_lower:
            return "Anthropic (Claude)"
        if "gpt" in model_lower or "openai" in model_lower:
            return "OpenAI"
        if "gemini" in model_lower:
            return "Google (Gemini)"
        return "Unknown"

    async def _handle_plugin_phase(self) -> None:
        """Handle the PLUGIN phase of session startup."""
        try:
            from backend.core.plugin import get_plugin_registry

            await get_plugin_registry().dispatch_session_start(
                self.sid, {"user_id": self.user_id}
            )
        except Exception as plugin_err:
            self.logger.warning("Plugin session_start hook failed: %s", plugin_err)

    def _initialize_session_startup(self) -> StartupContext:
        """Initialize session startup state."""
        self._starting = True
        ctx = StartupContext()
        self._started_at = ctx.started_at
        return ctx

    async def _setup_runtime_and_providers(
        self,
        runtime_name,
        config,
        agent,
        vcs_provider_tokens,
        custom_secrets,
        selected_repository,
        selected_branch,
    ):
        """Setup runtime and provider handlers."""
        from backend.server.session.runtime_factory import create_runtime

        result = await create_runtime(
            runtime_name=runtime_name,
            config=config,
            agent=agent,
            sid=self.sid,
            user_id=self.user_id,
            event_stream=self.event_stream,
            llm_registry=self.llm_registry,
            status_callback=self._status_callback,
            session_logger=self.logger,
            vcs_provider_tokens=vcs_provider_tokens,
            custom_secrets=custom_secrets,
            selected_repository=selected_repository,
            selected_branch=selected_branch,
        )
        if result.success:
            self.runtime = result.runtime
            self._runtime_acquire_result = result.acquire_result
            self._repo_directory = result.repo_directory

        # Setup provider handlers
        await self._setup_provider_handlers(vcs_provider_tokens, custom_secrets)

        return result.success

    async def _setup_provider_handlers(
        self, vcs_provider_tokens, custom_secrets
    ) -> None:
        """Setup provider handlers for git and custom secrets."""
        if vcs_provider_tokens:
            from backend.server.provider_handler import ProviderHandler

            provider_handler = ProviderHandler(provider_tokens=vcs_provider_tokens)
            await provider_handler.set_event_stream_secrets(self.event_stream)  # type: ignore[arg-type]

        if custom_secrets:
            custom_secrets_handler = UserSecrets(custom_secrets=custom_secrets)
            custom_secrets_handler.set_event_stream_secrets(self.event_stream)  # type: ignore[arg-type]

    async def _setup_memory_and_mcp_tools(
        self,
        selected_repository,
        selected_branch,
        conversation_instructions,
        custom_secrets,
        config,
        agent,
        user_settings: Settings | None = None,
    ) -> None:
        """Setup memory and MCP tools."""
        # Create memory
        custom_secret_dict: dict[str, CustomSecret] = {}
        if custom_secrets:
            custom_secret_dict = dict(custom_secrets.items())
        custom_secrets_handler = UserSecrets(custom_secrets=custom_secret_dict)
        repo_directory = self._repo_directory
        if repo_directory is None and selected_repository:
            repo_directory = selected_repository.split("/")[-1]

        # Determine working directory for memory
        working_dir = "."
        if self.runtime:
            working_dir = str(self.runtime.workspace_root)

        self.memory = await self._create_memory(
            selected_repository=selected_repository,
            repo_directory=repo_directory,
            selected_branch=selected_branch,
            conversation_instructions=conversation_instructions,
            custom_secrets_descriptions=custom_secrets_handler.get_custom_secrets_descriptions(),
            working_dir=working_dir,
            user_id=self.user_id,
            user_settings=user_settings,
        )

        # Add MCP tools if enabled
        if self.runtime and agent.config.enable_mcp:
            await add_mcp_tools_to_agent(agent, self.runtime, self.memory)

    async def _setup_controller_and_handle_replay(
        self,
        replay_json,
        initial_message,
        agent,
        config,
        max_iterations,
        max_budget_per_task,
        agent_to_llm_config,
        agent_configs,
    ):
        """Setup controller and handle replay if specified."""
        if replay_json:
            initial_message = self._run_replay(
                initial_message,
                replay_json,
                agent,
                config,
                max_iterations,
                max_budget_per_task,
                agent_to_llm_config,
                agent_configs,
            )
        else:
            self.controller, _restored_state = self._create_controller(
                agent,
                config.security.confirmation_mode,
                max_iterations,
                max_budget_per_task=max_budget_per_task,
                agent_to_llm_config=agent_to_llm_config,
                agent_configs=agent_configs,
            )
        return initial_message

    def _start_agent_execution(self, initial_message) -> None:
        """Start agent execution with appropriate initial state."""
        if not self._closed:
            if initial_message:
                self.logger.info(
                    "Adding initial user message and switching agent state to RUNNING",
                    extra={"signal": "agent_start"},
                )
                self.event_stream.add_event(initial_message, EventSource.USER)  # type: ignore[attr-defined]
                self.logger.debug(
                    "Enqueuing ChangeAgentStateAction(RUNNING)",
                    extra={"signal": "agent_start"},
                )
                self.event_stream.add_event(  # type: ignore[attr-defined]
                    ChangeAgentStateAction(AgentState.RUNNING), EventSource.ENVIRONMENT
                )
            else:
                self.logger.info(
                    "No initial message; queueing ChangeAgentStateAction(AWAITING_USER_INPUT)",
                    extra={"signal": "agent_start"},
                )
                self.logger.debug(
                    "Enqueuing ChangeAgentStateAction(AWAITING_USER_INPUT)",
                    extra={"signal": "agent_start"},
                )
                self.event_stream.add_event(  # type: ignore[attr-defined]
                    ChangeAgentStateAction(AgentState.AWAITING_USER_INPUT),
                    EventSource.ENVIRONMENT,
                )

    async def _finalize_session_startup(self, ctx: StartupContext) -> None:
        """Finalize session startup and log results."""
        self._starting = False
        success = ctx.finished and ctx.runtime_connected
        self._startup_failed = not success

        log_metadata = {
            "signal": "agent_session_start",
            "success": success,
            "phase": ctx.phase.value,
            "duration": ctx.duration,
            "restored_state": ctx.restored_state,
        }

        if success:
            self.logger.info(
                f"Agent session start succeeded in {ctx.duration:.1f}s",
                extra=log_metadata,
            )
        else:
            self.logger.error(
                f"Agent session start failed in phase={ctx.phase.value} after {ctx.duration:.1f}s",
                extra=log_metadata,
            )
            await self._handle_startup_failure_observations(ctx)

    async def _handle_startup_failure_observations(self, ctx: StartupContext) -> None:
        """Handle error observations when session startup fails."""
        # Format error for user-friendly display
        error_content = self._format_startup_error(ctx)

        # Add error observation to the event stream so the UI can show it
        if self.event_stream:
            self.event_stream.add_event(
                ErrorObservation(content=error_content),
                EventSource.ENVIRONMENT,
            )
            from backend.events.observation import AgentStateChangedObservation

            user_message = ctx.error_msg or "Agent session failed to initialize"
            if ctx.error_exception:
                try:
                    formatted = format_error_for_user(
                        ctx.error_exception,
                        context={"session_id": self.sid},
                    )
                    user_message = formatted.get("message", user_message)
                except Exception:
                    pass

            self.event_stream.add_event(
                AgentStateChangedObservation(
                    content=user_message,
                    agent_state=AgentState.ERROR,
                    reason=user_message,
                ),
                EventSource.ENVIRONMENT,
            )

    def _format_startup_error(self, ctx: StartupContext) -> str:
        """Format the startup error for user display."""
        if not ctx.error_exception:
            return ctx.error_msg or "Agent session failed to initialize"

        try:
            context: dict[str, Any] = {"session_id": self.sid}
            if ctx.error_context:
                context.update(ctx.error_context)
            if hasattr(ctx.error_exception, "__dict__"):
                for key in ["model", "provider", "agent"]:
                    if key in ctx.error_exception.__dict__:
                        context[key] = ctx.error_exception.__dict__[key]

            formatted_error = format_error_for_user(
                ctx.error_exception,
                context=context,
            )
            return json.dumps(formatted_error)
        except Exception as format_err:
            self.logger.warning("Failed to format error: %s", format_err)
            return ctx.error_msg or "Agent session failed to initialize"

    async def close(self) -> None:
        """Closes the Agent session, releasing all resources via try/finally."""
        if self._closed:
            return
        self._closed = True

        # Plugin hook: session_end
        await self._handle_session_end_plugins()

        # Wait for startup to complete or timeout
        await self._wait_for_startup_completion()

        # Best-effort: terminate any subprocesses/servers started by this runtime.
        self._hard_kill_runtime()

        # Close the controller *before* the event stream
        await self._close_controller()

        # Now it's safe to close the event stream — no more writers.
        self._close_event_stream()

        # Always release runtime — even if controller/event-stream close threw.
        self._release_runtime()

    async def _handle_session_end_plugins(self) -> None:
        """Fire the session_end plugin hook."""
        try:
            from backend.core.plugin import get_plugin_registry

            await get_plugin_registry().dispatch_session_end(
                self.sid, {"user_id": self.user_id}
            )
        except Exception as plugin_err:
            self.logger.warning("Plugin session_end hook failed: %s", plugin_err)

    async def _wait_for_startup_completion(self) -> None:
        """Wait for initialization to finish or timeout before closing."""
        while self._starting and should_continue():
            self.logger.debug(
                "Waiting for initialization to finish before closing session %s",
                self.sid,
            )
            await asyncio.sleep(WAIT_TIME_BEFORE_CLOSE_INTERVAL)
            if time.time() >= self._started_at + WAIT_TIME_BEFORE_CLOSE:
                self.logger.error(
                    "Waited too long for initialization to finish before closing session %s",
                    self.sid,
                )
                break

    def _hard_kill_runtime(self) -> None:
        """Best-effort: hard-kill runtime processes."""
        try:
            runtime = self.runtime
            if runtime is not None and hasattr(runtime, "hard_kill"):
                runtime.hard_kill()  # type: ignore[call-arg]
        except Exception as e:
            self.logger.warning("Error hard-killing runtime processes: %s", e)

    async def _close_controller(self) -> None:
        """Close the agent controller."""
        try:
            if self.controller is not None:
                self.controller.save_state()
                await self.controller.close()
        except Exception as e:
            self.logger.warning("Error closing controller: %s", e)

    def _close_event_stream(self) -> None:
        """Close the event stream."""
        try:
            if self.event_stream is not None:
                self.event_stream.close()  # type: ignore[attr-defined]
        except Exception as e:
            self.logger.warning("Error closing event stream: %s", e)

    def _release_runtime(self) -> None:
        """Release the runtime resources."""
        try:
            if self._runtime_acquire_result is not None:
                runtime_orchestrator.release(self._runtime_acquire_result)
                self._runtime_acquire_result = None
                self.runtime = None
            elif self.runtime is not None:
                EXECUTOR.submit(self.runtime.close)
                self.runtime = None
        except Exception as e:
            self.logger.warning("Error releasing runtime: %s", e)

    def _run_replay(
        self,
        initial_message: MessageAction | None,
        replay_json: str,
        agent: Agent,
        config: ForgeConfig,
        max_iterations: int,
        max_budget_per_task: float | None,
        agent_to_llm_config: dict[str, LLMConfig] | None,
        agent_configs: dict[str, AgentConfig] | None,
    ) -> MessageAction:
        """Replays a trajectory from a JSON file.

        Note that once the replay session finishes, the controller will continue to run with
        further user instructions, so we still need to pass llm configs, budget, etc., even
        though the replay itself does not call LLM or cost money.
        """
        assert initial_message is None
        replay_events = ReplayManager.get_replay_events(json.loads(replay_json))
        self.controller, _ = self._create_controller(
            agent,
            config.security.confirmation_mode,
            max_iterations,
            max_budget_per_task=max_budget_per_task,
            agent_to_llm_config=agent_to_llm_config,
            agent_configs=agent_configs,
            replay_events=replay_events[1:],
        )
        assert isinstance(replay_events[0], MessageAction)
        return replay_events[0]

    def override_provider_tokens_with_custom_secret(
        self,
        vcs_provider_tokens: ProviderTokenType | None,
        custom_secrets: CustomSecretsType | None,
    ):
        """Filter out provider tokens that have been overridden by custom secrets.

        Args:
            vcs_provider_tokens: Provider tokens from configuration
            custom_secrets: Custom secrets that may override provider tokens

        Returns:
            Filtered provider tokens (immutable)

        """
        if vcs_provider_tokens and custom_secrets:
            from backend.server.provider_handler import ProviderHandler

            tokens = {
                provider: token
                for provider, token in vcs_provider_tokens.items()
                if not (
                    ProviderHandler.get_provider_env_key(provider) in custom_secrets
                    or ProviderHandler.get_provider_env_key(provider).upper()
                    in custom_secrets
                )
            }
            return MappingProxyType(tokens)
        return vcs_provider_tokens

    def _create_controller(
        self,
        agent: Agent,
        confirmation_mode: bool,
        max_iterations: int,
        max_budget_per_task: float | None = None,
        agent_to_llm_config: dict[str, LLMConfig] | None = None,
        agent_configs: dict[str, AgentConfig] | None = None,
        replay_events: list[Event] | None = None,
    ) -> tuple[AgentController, bool]:
        """Creates an AgentController instance.

        Parameters:
        - agent:
        - confirmation_mode: Whether to use confirmation mode
        - max_iterations:
        - max_budget_per_task:
        - agent_to_llm_config:
        - agent_configs:

        Returns:
            Agent Controller and a bool indicating if state was restored from a previous conversation

        """
        if self.controller is not None:
            msg = "Controller already created"
            raise RuntimeError(msg)
        if self.runtime is None:
            msg = "Runtime must be initialized before the agent controller"
            raise SessionStartupError(msg)
        msg = f"\n--------------------------------- Forge Configuration ---------------------------------\nLLM: {
            agent.llm.config.model
        }\nBase URL: {agent.llm.config.base_url}\nAgent: {agent.name}\nRuntime: {
            self.runtime.__class__.__name__
        }\nPlugins: {
            (
                [p.name for p in agent.runtime_plugins]
                if agent.runtime_plugins
                else 'None'
            )
        }\n-------------------------------------------------------------------------------------------"
        self.logger.debug(msg)
        initial_state = self._maybe_restore_state()
        controller = AgentController(
            ControllerConfig(
                sid=self.sid,
                user_id=self.user_id,
                file_store=self.file_store,
                event_stream=self.event_stream,
                conversation_stats=self.conversation_stats,
                agent=agent,
                iteration_delta=max_iterations,
                budget_per_task_delta=max_budget_per_task,
                agent_to_llm_config=agent_to_llm_config,
                agent_configs=agent_configs,
                confirmation_mode=confirmation_mode,
                headless_mode=False,
                status_callback=self._status_callback,
                initial_state=initial_state,
                replay_events=replay_events,
                security_analyzer=self.runtime.security_analyzer
                if self.runtime
                else None,
            )
        )
        return (controller, initial_state is not None)

    async def _create_memory(
        self,
        selected_repository: str | None,
        repo_directory: str | None,
        selected_branch: str | None,
        conversation_instructions: str | None,
        custom_secrets_descriptions: dict[str, str],
        working_dir: str,
        user_id: str | None = None,
        user_settings: Settings | None = None,
    ) -> Memory:
        memory = Memory(
            event_stream=self.event_stream,
            sid=self.sid,
            status_callback=self._status_callback,
            user_id=user_id,
        )
        # Apply Knowledge Base settings if available
        if user_settings and user_settings.knowledge_base:
            kb_settings = user_settings.knowledge_base
            # If we need to pass more settings to Memory, we can do it here
            # For now, KnowledgeBaseManager in Memory uses default settings
            # or we can add a method to Memory to update KB settings
            if hasattr(memory, "set_knowledge_base_settings"):
                memory.set_knowledge_base_settings(kb_settings)

        if self.runtime:
            memory.set_runtime_info(
                self.runtime, custom_secrets_descriptions, working_dir
            )
            memory.set_conversation_instructions(conversation_instructions)
            playbooks: list[BasePlaybook] = await call_sync_from_async(
                self.runtime.get_playbooks_from_selected_repo,
                selected_repository or None,
            )
            memory.load_user_workspace_playbooks(playbooks)
            if selected_repository and repo_directory:
                memory.set_repository_info(
                    selected_repository, repo_directory, selected_branch
                )
        return memory

    def get_state(self) -> AgentState | None:
        """Get current agent state.

        Returns:
            Current agent state, ERROR if timed out, None if still initializing

        """
        if controller := self.controller:
            return controller.state.agent_state
        if time.time() > self._started_at + WAIT_TIME_BEFORE_CLOSE:
            return AgentState.ERROR
        return None

    def _maybe_restore_state(self) -> State | None:
        """Helper method to handle state restore logic."""
        restored_state = None
        try:
            restored_state = State.restore_from_session(
                self.sid, self.file_store, self.user_id
            )
            self.logger.debug("Restored state from session, sid: %s", self.sid)
        except Exception as e:
            if self.event_stream.get_latest_event_id() > 0:  # type: ignore[attr-defined]
                self.logger.warning("State could not be restored: %s", e)
            else:
                self.logger.debug("No events found, no state to restore")
        return restored_state

    def is_closed(self) -> bool:
        """Check if session has been closed.

        Returns:
            True if session is closed

        """
        return self._closed
