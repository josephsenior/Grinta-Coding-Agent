"""Core functionality for the Forge agent framework.

Classes:
    FakeUserResponseFunc

Functions:
    auto_continue_response
    load_replay_log
    on_event
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from backend.utils.async_utils import run_or_schedule

if TYPE_CHECKING:
    from backend.controller.agent import Agent
    from backend.controller.state.state import State
    from backend.events.action.action import Action
    from backend.events.event import Event
    from backend.events.stream import EventStream
    from backend.core.provider_types import PROVIDER_TOKEN_TYPE
    from backend.memory.agent_memory import Memory
    from backend.llm.llm_registry import LLMRegistry
    from backend.runtime.base import Runtime
    from backend.server.services.conversation_stats import ConversationStats


from backend.adapters import read_input, read_task
from backend.controller.replay import ReplayManager
from backend.core.config import (
    ForgeConfig,
    parse_arguments,
    setup_config_from_args,
)
from backend.core.config.mcp_config import ForgeMCPConfigImpl
from backend.core.logger import FORGE_logger as logger
from backend.core.loop import run_agent_until_done
from backend.core.schemas import AgentState
from backend.core.setup import (
    create_agent,
    create_controller,
    create_memory,
    generate_sid,
    get_provider_tokens,
    initialize_repository_for_runtime,
)
from backend.events import EventSource, EventStreamSubscriber
from backend.events.action import MessageAction, NullAction
from backend.events.observation import AgentStateChangedObservation
from backend.mcp import add_mcp_tools_to_agent
from backend.runtime import (
    RuntimeAcquireResult,
    RuntimeOrchestrator,
    runtime_orchestrator,
)
from backend.core.enums import RuntimeStatus
from backend.utils.async_utils import call_async_from_sync
from backend.utils.utils import create_registry_and_conversation_stats

_RUNTIME_ORCHESTRATOR: RuntimeOrchestrator = runtime_orchestrator


class FakeUserResponseFunc(Protocol):
    """Protocol for fake user response functions in testing/evaluation.

    Defines the interface for functions that simulate user responses
    during automated agent evaluation.
    """

    def __call__(
        self,
        state: State,
        encapsulate_solution: bool = False,
        try_parse: Callable[[Action | None], str] | None = None,
    ) -> str:
        """Simulate a user reply given the current state and parsing helpers."""


def _setup_runtime_and_repo(
    config_: ForgeConfig,
    session_id: str,
    llm_registry,
    agent,
    headless_mode: bool,
    *,
    vcs_provider_tokens: PROVIDER_TOKEN_TYPE | None = None,
    repo_initializer: Callable[[Runtime], str | None] | None = None,
    event_stream: EventStream | None = None,
    env_vars: dict[str, str] | None = None,
    user_id: str | None = None,
) -> RuntimeAcquireResult:
    """Setup runtime and repository directory."""
    repo_tokens = (
        vcs_provider_tokens
        if vcs_provider_tokens is not None
        else get_provider_tokens()
    )

    def _default_repo_initializer(runtime: Runtime) -> str | None:
        return initialize_repository_for_runtime(
            runtime,
            immutable_provider_tokens=repo_tokens,
            selected_repository=config_.runtime_config.selected_repo,
        )

    repo_cb = repo_initializer
    if repo_cb is None and config_.runtime_config.selected_repo:
        repo_cb = _default_repo_initializer

    acquire_result = _RUNTIME_ORCHESTRATOR.acquire(
        config_,
        llm_registry,
        session_id=session_id,
        agent=agent,
        headless_mode=headless_mode,
        vcs_provider_tokens=repo_tokens,
        repo_initializer=repo_cb,
        event_stream=event_stream,
        env_vars=env_vars,
        user_id=user_id,
    )
    runtime = acquire_result.runtime
    call_async_from_sync(runtime.connect)

    return acquire_result


async def _setup_memory_and_mcp(
    config_: ForgeConfig,
    runtime: Runtime,
    session_id: str,
    repo_directory: str | None,
    memory: Memory | None,
    conversation_instructions: str | None,
    agent,
) -> Memory:
    """Setup memory and MCP tools."""
    event_stream = runtime.event_stream
    if event_stream is None:
        raise RuntimeError("Runtime does not have an event stream")

    if memory is None:
        memory = create_memory(
            runtime=runtime,
            event_stream=event_stream,
            sid=session_id,
            selected_repository=config_.runtime_config.selected_repo,
            repo_directory=repo_directory,
            conversation_instructions=conversation_instructions,
            working_dir=config_.workspace_mount_path_in_runtime,
        )

    if agent.config.enable_mcp:
        _, FORGE_mcp_stdio_servers = (
            ForgeMCPConfigImpl.create_default_mcp_server_config(
                config_.mcp_host,
                config_,
                None,
            )
        )
        runtime.config.mcp.stdio_servers.extend(FORGE_mcp_stdio_servers)
        await add_mcp_tools_to_agent(agent, runtime, memory)

    return memory


def _setup_replay_events(
    config_: ForgeConfig, initial_action: Action
) -> tuple[list[Event] | None, Action]:
    """Setup replay events if trajectory replay is enabled."""
    if config_.replay_trajectory_path:
        logger.info("Trajectory replay is enabled")
        assert isinstance(initial_action, NullAction)
        return load_replay_log(config_.replay_trajectory_path)
    return None, initial_action


def _create_early_status_callback(
    controller,
) -> Callable[[str, RuntimeStatus, str], None]:
    """Create the early status callback function."""

    def _early_status_callback(
        msg_type: str, runtime_status: RuntimeStatus, msg: str
    ) -> None:
        if msg_type == "error":
            logger.error(msg)
            logger.info(
                'MAIN._early_status_callback ENTER (runtime_status=%s, msg="%s")',
                runtime_status,
                msg,
            )
            try:
                controller.state.set_last_error(
                    msg, source="main._early_status_callback"
                )
                if runtime_status == RuntimeStatus.ERROR_MEMORY:
                    logger.info(
                        "MAIN._early_status_callback: recording memory error boundary at iteration %s",
                        controller.state.iteration_flag.current_value,
                    )
                    setattr(
                        controller.state,
                        "_memory_error_boundary",
                        controller.state.iteration_flag.current_value,
                    )
            except Exception:
                logger.warning(
                    "Failed to record error state on controller", exc_info=True
                )
            # Schedule safely across threads without requiring a running loop
            try:
                run_or_schedule(controller.set_agent_state_to(AgentState.ERROR))
            except Exception:
                try:
                    from backend.utils.async_utils import create_tracked_task

                    create_tracked_task(
                        controller.set_agent_state_to(AgentState.ERROR),
                        name="error-state-last-resort",
                    )
                except Exception:
                    logger.error(
                        "CRITICAL: Failed to transition agent to ERROR state — "
                        "agent may be stuck in an inconsistent state",
                        exc_info=True,
                    )
        else:
            logger.info(msg)

    return _early_status_callback


def _validate_initial_action(initial_action: Action) -> None:
    """Validate that the initial action is properly formatted."""
    if not hasattr(initial_action, "message") and (
        not hasattr(initial_action, "content")
    ):
        msg = f"initial user actions must be an Action-like object, got {type(initial_action)}"
        raise AssertionError(msg)


def _setup_initial_events(
    event_stream, initial_action: Action, initial_state: State | None
) -> None:
    """Setup initial events based on state and action."""
    loop = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if initial_state is not None and initial_state.last_error:
        error_message = MessageAction(
            content=(
                "Let's get back on track. If you experienced errors before, "
                "do NOT resume your task. Ask me about it."
            ),
        )
        if loop is not None:
            loop.call_soon(event_stream.add_event, error_message, EventSource.USER)
        else:
            event_stream.add_event(error_message, EventSource.USER)
    elif loop is not None:
        loop.call_soon(event_stream.add_event, initial_action, EventSource.USER)
    else:
        event_stream.add_event(initial_action, EventSource.USER)


def _create_event_handler(
    config_: ForgeConfig,
    exit_on_message: bool,
    fake_user_response_fn: FakeUserResponseFunc | None,
    controller,
    event_stream,
) -> Callable[[Event], None]:
    """Create the event handler for user input."""

    def on_event(event: Event) -> None:
        """Handle events and trigger completion on user input or agent finish.

        Args:
            event: Event to process

        """
        if (
            isinstance(event, AgentStateChangedObservation)
            and event.agent_state == AgentState.AWAITING_USER_INPUT
        ):
            if exit_on_message:
                message = "/exit"
            elif fake_user_response_fn is None:
                message = read_input(config_.cli_multiline_input)
            else:
                message = fake_user_response_fn(controller.get_state())
            action = MessageAction(content=message)
            event_stream.add_event(action, EventSource.USER)

    return on_event


def _save_trajectory(config_: ForgeConfig, session_id: str, controller) -> None:
    """Save trajectory to file if configured."""
    if config_.save_trajectory_path is not None:
        if os.path.isdir(config_.save_trajectory_path):
            file_path = os.path.join(config_.save_trajectory_path, f"{session_id}.json")
        else:
            file_path = config_.save_trajectory_path
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        histories = controller.get_trajectory(config_.save_screenshots_in_trajectory)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(histories, f, indent=4)


def _initialize_session_components(
    config_: ForgeConfig,
    session_id: str | None,
) -> tuple[str, LLMRegistry, ConversationStats, ForgeConfig, Agent]:
    """Initialize session and components."""
    session_id = session_id or generate_sid(config_)
    llm_registry, conversation_stats, config_ = create_registry_and_conversation_stats(
        config_, session_id, None
    )
    agent = create_agent(config_, llm_registry)
    return session_id, llm_registry, conversation_stats, config_, agent


def _setup_runtime_for_controller(
    config_: ForgeConfig,
    llm_registry: LLMRegistry,
    session_id: str,
    headless_mode: bool,
    agent: Agent,
    runtime: Runtime | None,
) -> tuple[Runtime, str | None, RuntimeAcquireResult | None]:
    """Setup runtime for controller."""
    if runtime is not None:
        return runtime, None, None
    acquire_result = _setup_runtime_and_repo(
        config_,
        session_id,
        llm_registry,
        agent,
        headless_mode,
    )
    return acquire_result.runtime, acquire_result.repo_directory, acquire_result


async def run_controller(
    config_: ForgeConfig | None = None,
    initial_action: Action | None = None,
    *,
    session_id: str | None = None,
    runtime: Runtime | None = None,
    exit_on_message: bool = False,
    fake_user_response_fn: FakeUserResponseFunc | None = None,
    headless_mode: bool = True,
    memory: Memory | None = None,
    conversation_instructions: str | None = None,
) -> State | None:
    """Main coroutine to run the agent controller with task input flexibility."""
    config_, initial_action = _validate_run_controller_inputs(config_, initial_action)

    session_id, llm_registry, conversation_stats, config_, agent = (
        _initialize_session_components(config_, session_id)
    )
    runtime, repo_directory, acquire_result = _setup_runtime_for_controller(
        config_,
        llm_registry,
        session_id,
        headless_mode,
        agent,
        runtime,
    )

    try:
        state = await _execute_controller_lifecycle(
            config_=config_,
            runtime=runtime,
            session_id=session_id,
            repo_directory=repo_directory,
            agent=agent,
            conversation_stats=conversation_stats,
            initial_action=initial_action,
            exit_on_message=exit_on_message,
            fake_user_response_fn=fake_user_response_fn,
            memory=memory,
            conversation_instructions=conversation_instructions,
        )
        saved_controller = getattr(runtime, "controller", None)
        if saved_controller is not None:
            _save_trajectory(config_, session_id, saved_controller)
        return state
    finally:
        if acquire_result is not None:
            _RUNTIME_ORCHESTRATOR.release(acquire_result)


def _validate_run_controller_inputs(
    config_: ForgeConfig | None, initial_action: Action | None
) -> tuple[ForgeConfig, Action]:
    if config_ is None:
        raise TypeError("run_controller() missing required argument 'config_'")
    if initial_action is None:
        raise TypeError("run_controller() missing required argument 'initial_action'")
    return config_, initial_action


async def _execute_controller_lifecycle(
    *,
    config_: ForgeConfig,
    runtime: Runtime,
    session_id: str,
    repo_directory: str | None,
    agent: Agent,
    conversation_stats: ConversationStats,
    initial_action: Action,
    exit_on_message: bool,
    fake_user_response_fn: FakeUserResponseFunc | None,
    memory: Memory | None,
    conversation_instructions: str | None,
) -> State:
    event_stream = runtime.event_stream
    if event_stream is None:
        raise RuntimeError("Runtime does not have an event stream")
    resolved_memory = await _setup_memory_and_mcp(
        config_,
        runtime,
        session_id,
        repo_directory,
        memory,
        conversation_instructions,
        agent,
    )
    replay_events, initial_action = _setup_replay_events(config_, initial_action)
    controller, initial_state = create_controller(
        agent,
        runtime,
        config_,
        conversation_stats,
        replay_events=replay_events,
    )
    setattr(runtime, "controller", controller)  # retain for trajectory saving
    _attach_status_callback(resolved_memory, controller)
    _validate_initial_action(initial_action)
    logger.debug(
        "Agent Controller Initialized: Running agent %s, model %s, with actions: %s",
        agent.name,
        agent.llm.config.model,
        initial_action,
    )
    _setup_initial_events(event_stream, initial_action, initial_state)
    _subscribe_controller_events(
        config_,
        event_stream,
        exit_on_message,
        fake_user_response_fn,
        controller,
    )
    await _run_agent_loop(controller, runtime, resolved_memory)
    await _persist_controller_state(config_, controller, event_stream)
    return _prepare_final_state(controller)


def _attach_status_callback(memory: Memory, controller) -> None:
    _early_status_callback = _create_early_status_callback(controller)
    try:
        memory.status_callback = _early_status_callback
    except Exception:
        logger.warning("Failed to attach status callback to memory", exc_info=True)


def _subscribe_controller_events(
    config_: ForgeConfig,
    event_stream: EventStream,
    exit_on_message: bool,
    fake_user_response_fn: FakeUserResponseFunc | None,
    controller,
) -> None:
    on_event = _create_event_handler(
        config_, exit_on_message, fake_user_response_fn, controller, event_stream
    )
    event_stream.subscribe(EventStreamSubscriber.MAIN, on_event, event_stream.sid)


async def _run_agent_loop(controller, runtime: Runtime, memory: Memory) -> None:
    end_states = [
        AgentState.FINISHED,
        AgentState.REJECTED,
        AgentState.ERROR,
        AgentState.PAUSED,
        AgentState.STOPPED,
    ]
    try:
        await run_agent_until_done(controller, runtime, memory, end_states)
    except Exception as exc:
        logger.error("Exception in main loop: %s", exc)


async def _persist_controller_state(
    config_: ForgeConfig, controller, event_stream: EventStream
) -> None:
    if config_.file_store is None or config_.file_store == "memory":
        return
    end_state = controller.get_state()
    end_state.save_to_session(
        event_stream.sid,
        event_stream.file_store,
        event_stream.user_id,
    )
    await controller.close(set_stop_state=False)


def _prepare_final_state(controller) -> State:
    state = controller.get_state()
    force_iteration_reset = getattr(
        controller, "_force_iteration_reset", False
    ) or getattr(
        state,
        "_force_iteration_reset",
        False,
    )
    if force_iteration_reset:
        logger.debug(
            "run_controller: honoring forced iteration reset (current=%s)",
            state.iteration_flag.current_value,
        )
        state.iteration_flag.current_value = 0
    return state


def auto_continue_response(
    state: State,
    encapsulate_solution: bool = False,
    try_parse: Callable[[Action | None], str] | None = None,
) -> str:
    """Default function to generate user responses.

    Tell the agent to proceed without asking for more input, or finish the interaction.
    """
    return (
        "Please continue on whatever approach you think is suitable.\n"
        "If you think you have solved the task, please finish the interaction.\n"
        "IMPORTANT: YOU SHOULD NEVER ASK FOR HUMAN RESPONSE.\n"
    )


def load_replay_log(trajectory_path: str) -> tuple[list[Event] | None, Action]:
    """Load trajectory from given path, serialize it to a list of events, and return.

    two things:
    1) A list of events except the first action
    2) First action (user message, a.k.a. initial task).
    """
    try:
        path = Path(trajectory_path).resolve()
        if not path.exists():
            msg = f"Trajectory file not found: {path}"
            raise ValueError(msg)
        if not path.is_file():
            msg = f"Trajectory path is a directory, not a file: {path}"
            raise ValueError(msg)
        with open(path, encoding="utf-8") as file:
            events = ReplayManager.get_replay_events(json.load(file))
            assert isinstance(events[0], MessageAction)
            return (events[1:], events[0])
    except json.JSONDecodeError as e:
        msg = f"Invalid JSON format in {trajectory_path}: {e}"
        raise ValueError(msg) from e


if __name__ == "__main__":
    args = parse_arguments()
    config_main: ForgeConfig = setup_config_from_args(args)
    task_str = read_task(args, config_main.cli_multiline_input)
    initial_action_main: Action = NullAction()
    if config_main.replay_trajectory_path:
        if task_str:
            error_msg = (
                "User-specified task is not supported under trajectory replay mode"
            )
            raise ValueError(error_msg)
    elif task_str:
        initial_action_main = MessageAction(content=task_str)
    else:
        error_msg = "No task provided. Please specify a task through -t, -f."
        raise ValueError(error_msg)
    session_name = args.name
    sid_main = generate_sid(config_main, session_name)
    asyncio.run(
        run_controller(
            config_=config_main,
            initial_action=initial_action_main,
            session_id=sid_main,
            fake_user_response_fn=None
            if args.no_auto_continue
            else auto_continue_response,
        ),
    )
