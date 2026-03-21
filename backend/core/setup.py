"""Core functionality for the Forge agent framework.

Functions:
    create_runtime
    get_provider_tokens
    initialize_repository_for_runtime
    create_memory
    create_agent
"""

from __future__ import annotations

import hashlib
import importlib
import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from backend.controller import AgentController
from backend.controller.agent import Agent
from backend.controller.state.state import State
from backend.core.constants import GENERAL_TIMEOUT
from backend.core.errors import AgentNotRegisteredError
from backend.core.logger import forge_logger as logger
from backend.events import EventStream
from backend.memory.agent_memory import Memory
from backend.llm.llm_registry import LLMRegistry
from backend.runtime.plugins import PluginRequirement
from backend.storage import get_file_store
from backend.storage.data_models.user_secrets import UserSecrets
from backend.utils.async_utils import call_async_from_sync

if TYPE_CHECKING:
    from backend.core.config import AgentConfig, ForgeConfig
    from backend.events.event import Event
    from backend.playbook_engine.playbook import BasePlaybook
    from backend.core.provider_types import (
        ProviderTokenType,
        ProviderToken,
        ProviderType,
    )
    from backend.runtime.base import Runtime
    from backend.api.services.conversation_stats import ConversationStats


def _instantiate_runtime(runtime_cls: type[object], **kwargs: Any) -> Runtime:
    """Instantiate a runtime class and return it as Runtime protocol type."""
    return cast("Runtime", runtime_cls(**kwargs))


def _resolve_agent_config(
    agent: Agent | None,
    config: ForgeConfig | None,
    agent_cls_name: str | None,
) -> AgentConfig | None:
    """Resolve AgentConfig from agent or config + agent_cls_name."""
    if agent is not None:
        return getattr(agent, "config", None)
    if config is not None and agent_cls_name:
        try:
            return config.get_agent_config(agent_cls_name)
        except Exception:
            pass
    return None


def _apply_agent_disabled_plugins(
    filtered: list[PluginRequirement], agent_config: AgentConfig | None
) -> list[PluginRequirement]:
    """Apply agent config disabled_plugins denylist."""
    if agent_config is None:
        return filtered
    disabled = set(getattr(agent_config, "disabled_plugins", None) or [])
    if not disabled:
        return filtered
    result = [p for p in filtered if p.name not in disabled]
    if len(result) < len(filtered):
        logger.info(
            "Plugins disabled by agent config: %s",
            ", ".join(sorted(disabled)),
        )
    return result


def filter_plugins_by_config(
    plugins: list[PluginRequirement],
    agent: Agent | None = None,
    config: ForgeConfig | None = None,
    agent_cls_name: str | None = None,
) -> list[PluginRequirement]:
    """Filter plugins through two layers:

    1. **Environment allowlist** — delegates to
       ``backend.runtime.plugins.filter_plugins_by_config`` which honours the
       ``FORGE_PLUGINS`` env-var (comma-separated allowlist).  When the var is
       unset every plugin passes through.
    2. **Agent-config denylist** — if an ``AgentConfig`` is reachable (via
       *agent* or *config* + *agent_cls_name*), its ``disabled_plugins``
       attribute (if present) is respected.

    Args:
        plugins: List of plugin requirements to filter.
        agent: Optional agent instance to derive config from.
        config: Optional ForgeConfig to look up per-agent config.
        agent_cls_name: Agent class name used to resolve config.

    Returns:
        Filtered list of plugin requirements.
    """
    from backend.runtime.plugins import (
        filter_plugins_by_config as _env_filter,
    )

    filtered = _env_filter(plugins)
    agent_config = _resolve_agent_config(agent, config, agent_cls_name)
    return _apply_agent_disabled_plugins(filtered, agent_config)


def create_runtime(
    config: ForgeConfig,
    llm_registry: LLMRegistry | None = None,
    sid: str | None = None,
    headless_mode: bool = True,
    agent: Agent | None = None,
    vcs_provider_tokens: ProviderTokenType | None = None,
    *,
    event_stream: EventStream | None = None,
    env_vars: dict[str, str] | None = None,
    user_id: str | None = None,
    workspace_base: str | None = None,
) -> Runtime:
    """Create a runtime for the agent to run on.

    Args:
        config: The app config.
        llm_registry: Optional LLM registry to use.
        sid: (optional) The session id. IMPORTANT: please don't set this unless you know what you're doing.
        headless_mode: Whether the agent is run in headless mode.
            `create_runtime` is typically called within evaluation scripts, so it defaults to True.
        agent: (optional) The agent instance to use for configuring the runtime.
        vcs_provider_tokens: Optional git provider tokens for authentication.
        event_stream: Optional event stream for real-time monitoring.
        env_vars: Optional environment variables for the runtime.
        user_id: Optional user ID for ownership and quotas.
        workspace_base: Optional workspace base directory.

    Returns:
        The created Runtime instance (not yet connected or initialized).

    """
    if event_stream is None:
        session_id = sid or generate_sid(config)
        file_store = get_file_store(config.file_store, config.file_store_path)
        event_stream = EventStream(session_id, file_store)
    else:
        session_id = sid or event_stream.sid
    agent_cls = type(agent) if agent else Agent.get_cls(config.default_agent)

    # Filter plugins based on config
    plugins = filter_plugins_by_config(
        plugins=list(agent_cls.runtime_plugins),
        agent=agent,
        config=config,
        agent_cls_name=agent_cls.__name__,
    )

    from backend.runtime.factory import get_runtime_cls

    runtime_cls = get_runtime_cls(config.runtime)
    logger.debug("Initializing runtime: %s", runtime_cls.__name__)
    runtime = _instantiate_runtime(
        runtime_cls,
        config=config,
        event_stream=event_stream,
        sid=session_id,
        plugins=plugins,
        headless_mode=headless_mode,
        llm_registry=llm_registry or LLMRegistry(config),
        vcs_provider_tokens=vcs_provider_tokens,
        env_vars=env_vars,
        user_id=user_id,
        workspace_base=workspace_base,
    )
    logger.debug(
        "Runtime created with plugins: %s", [plugin.name for plugin in runtime.plugins]
    )
    return runtime


def _create_secret_store(provider_tokens: dict) -> UserSecrets | None:
    """Create UserSecrets instance if tokens are available."""
    return UserSecrets(provider_tokens=provider_tokens) if provider_tokens else None


def get_provider_tokens() -> ProviderTokenType | None:
    """Retrieve provider tokens from environment variables and return them as a dictionary.

    Returns:
        A dictionary mapping ProviderType to ProviderToken if tokens are found, otherwise None.

    """
    provider_tokens: dict[ProviderType, ProviderToken] = {}

    secret_store = _create_secret_store(provider_tokens)
    return secret_store.provider_tokens if secret_store else None


def initialize_repository_for_runtime(
    runtime: Runtime,
    immutable_provider_tokens: ProviderTokenType | None = None,
    selected_repository: str | None = None,
    selected_branch: str | None = None,
) -> str | None:
    """Initialize the repository for the runtime by cloning or initializing it,
    running setup scripts, and setting up git hooks if present.

    Args:
        runtime: The runtime to initialize the repository for.
        immutable_provider_tokens: (optional) Provider tokens to use for authentication.
        selected_repository: (optional) The repository to use.
        selected_branch: (optional) Branch ref to checkout.

    Returns:
        The repository directory path if a repository was cloned, None otherwise.

    """
    if not immutable_provider_tokens:
        immutable_provider_tokens = get_provider_tokens()
    logger.debug("Selected repository %s.", selected_repository)
    repo_directory = call_async_from_sync(
        runtime.clone_or_init_repo,
        GENERAL_TIMEOUT,
        immutable_provider_tokens,
        selected_repository,
        selected_branch,
    )
    runtime.maybe_run_setup_script()
    runtime.maybe_setup_git_hooks()
    return repo_directory


def create_memory(
    runtime: Runtime,
    event_stream: EventStream,
    sid: str,
    selected_repository: str | None = None,
    repo_directory: str | None = None,
    status_callback: Callable | None = None,
    conversation_instructions: str | None = None,
    working_dir: str | None = None,
) -> Memory:
    """Create a memory for the agent to use.

    Args:
        runtime: The runtime to use.
        event_stream: The event stream it will subscribe to.
        sid: The session id.
        selected_repository: The repository to clone and start with, if any.
        repo_directory: The repository directory, if any.
        status_callback: Optional callback function to handle status updates.
        conversation_instructions: Optional instructions that are passed to the agent
        working_dir: The working directory for the memory. If not provided, uses runtime.workspace_root.

    """
    memory = Memory(event_stream=event_stream, sid=sid, status_callback=status_callback)
    memory.set_conversation_instructions(conversation_instructions)
    if runtime:
        if working_dir is None:
            working_dir = str(runtime.workspace_root)
        memory.set_runtime_info(runtime, {}, working_dir)
        playbooks: list[BasePlaybook] = runtime.get_playbooks_from_selected_repo(
            selected_repository
        )
        memory.load_user_workspace_playbooks(playbooks)
        if selected_repository and repo_directory:
            memory.set_repository_info(selected_repository, repo_directory)
    return memory


def _ensure_agent_class_available(agent_name: str) -> None:
    """Ensure the requested agent class has been registered.

    Attempts to import `forge.engines` (and its submodules) lazily so that the
    built-in agents are registered even when the CLI is exercised in isolation,
    such as during unit tests.
    """
    try:
        Agent.get_cls(agent_name)
        return
    except AgentNotRegisteredError:
        pass
    try:
        importlib.import_module("forge.engines")
    except Exception as exc:  # pragma: no cover - defensive logging
        logger.debug("Failed to auto-import backend.engines: %s", exc)
    try:
        Agent.get_cls(agent_name)
    except AgentNotRegisteredError as exc:
        raise AgentNotRegisteredError(agent_name) from exc


def create_agent(config: ForgeConfig, llm_registry: LLMRegistry) -> Agent:
    """Create agent instance from configuration.

    Args:
        config: Configuration for composite score weights
        llm_registry: LLM registry for model access

    Returns:
        Initialized agent instance

    """
    try:
        agent_cls: type[Agent] = Agent.get_cls(config.default_agent)
    except AgentNotRegisteredError:
        _ensure_agent_class_available(config.default_agent)
        agent_cls = Agent.get_cls(config.default_agent)
    agent_config = config.get_agent_config(config.default_agent)
    config.get_llm_config_from_agent(config.default_agent)
    return agent_cls(config=agent_config, llm_registry=llm_registry)


def create_controller(
    agent: Agent,
    runtime: Runtime,
    config: ForgeConfig,
    conversation_stats: ConversationStats,
    headless_mode: bool = True,
    replay_events: list[Event] | None = None,
) -> tuple[AgentController, State | None]:
    """Create agent controller with optional state restoration.

    Attempts to restore previous agent state from session if available.

    Args:
        agent: Agent instance
        runtime: Runtime environment
        config: Forge configuration
        conversation_stats: Conversation statistics tracker
        headless_mode: Whether running in headless mode
        replay_events: Optional events to replay

    Returns:
        Tuple of (controller, initial_state)

    """
    event_stream = runtime.event_stream
    if event_stream is None:
        raise RuntimeError("Runtime does not have an initialized event stream")
    initial_state = None
    try:
        logger.debug(
            "Trying to restore agent state from session %s if available",
            event_stream.sid,
        )
        initial_state = State.restore_from_session(
            event_stream.sid, event_stream.file_store
        )
    except Exception as e:
        logger.debug("Cannot restore agent state: %s", e)
    from backend.controller.agent_controller import ControllerConfig

    controller = AgentController(
        config=ControllerConfig(
            agent=agent,
            conversation_stats=conversation_stats,
            iteration_delta=config.max_iterations,
            budget_per_task_delta=config.max_budget_per_task,
            agent_to_llm_config=config.get_agent_to_llm_config_map(),
            event_stream=event_stream,
            initial_state=initial_state,
            headless_mode=headless_mode,
            confirmation_mode=config.security.confirmation_mode,
            replay_events=replay_events,
            security_analyzer=runtime.security_analyzer,
            pending_action_timeout=config.pending_action_timeout,
        )
    )
    return (controller, initial_state)


def generate_sid(config: ForgeConfig, session_name: str | None = None) -> str:
    """Generate a unique session id.

    The session ID is kept short to ensure it's easy to manage.
    """
    session_name = session_name or str(uuid.uuid4())
    # Use a simple hash of the session name
    hash_str = hashlib.sha256(session_name.encode()).hexdigest()
    if len(session_name) > 16:
        session_id = f"{session_name[:16]}-{hash_str[:15]}"
    else:
        remaining_chars = 32 - len(session_name) - 1
        session_id = f"{session_name}-{hash_str[:remaining_chars]}"
    return session_id[:32]
