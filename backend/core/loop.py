"""Agent control loop helpers for running runtimes and handling status callbacks."""

import asyncio
from collections.abc import Callable

from backend.controller import AgentController
from backend.core.logger import FORGE_logger as logger
from backend.core.schemas import AgentState
from backend.memory.agent_memory import Memory
from backend.runtime.base import Runtime
from backend.core.enums import RuntimeStatus
from backend.utils.async_utils import run_or_schedule

# Backoff parameters for the polling loop
_INITIAL_POLL_INTERVAL = 0.1  # 100ms
_MAX_POLL_INTERVAL = 2.0  # 2s cap
_BACKOFF_FACTOR = 1.5
_MAX_CONSECUTIVE_ERRORS = 20  # Force ERROR state after this many step failures


def _handle_error_status(
    controller: AgentController, runtime_status: RuntimeStatus, msg: str
) -> None:
    """Handle error status in the status callback."""
    if controller:
        controller.state.set_last_error(msg, source="loop.status_callback")
        try:
            if runtime_status == RuntimeStatus.ERROR_MEMORY:
                setattr(
                    controller.state,
                    "_memory_error_boundary",
                    controller.state.iteration_flag.current_value,
                )
                logger.info(
                    "LOOP.status_callback: memory error boundary recorded at iteration %s",
                    controller.state.iteration_flag.current_value,
                )
        except Exception:
            logger.debug("Failed to record memory error boundary", exc_info=True)
        # Schedule safely across threads without requiring a running loop
        try:
            run_or_schedule(controller.set_agent_state_to(AgentState.ERROR))
        except Exception:
            logger.warning(
                "Failed to schedule ERROR state transition via run_or_schedule",
                exc_info=True,
            )
            try:
                from backend.utils.async_utils import create_tracked_task

                create_tracked_task(
                    controller.set_agent_state_to(AgentState.ERROR),
                    name="error-state-fallback",
                )
            except Exception:
                logger.error(
                    "All attempts to transition agent to ERROR state failed",
                    exc_info=True,
                )


def _create_status_callback(
    controller: AgentController,
) -> Callable[[str, RuntimeStatus, str], None]:
    """Create the status callback function."""

    def status_callback(msg_type: str, runtime_status: RuntimeStatus, msg: str) -> None:
        """Handle runtime status updates.

        Args:
            msg_type: Message type (error, info, etc.)
            runtime_status: Runtime status object
            msg: Status message

        """
        if msg_type == "error":
            logger.error(msg)
            _handle_error_status(controller, runtime_status, msg)
        else:
            logger.info(msg)

    return status_callback


def _validate_status_callbacks(runtime: Runtime, controller: AgentController) -> None:
    """Validate that status callbacks are not already set."""
    if getattr(runtime, "status_callback", None):
        logger.warning("Runtime status_callback already set; overriding in run loop")
    if getattr(controller, "status_callback", None):
        logger.warning("Controller status_callback already set; overriding in run loop")


def _set_status_callbacks(
    runtime: Runtime,
    controller: AgentController,
    memory: Memory,
    status_callback: Callable[[str, RuntimeStatus, str], None],
) -> None:
    """Set status callbacks on runtime, controller, and memory."""
    runtime.status_callback = status_callback
    controller.status_callback = status_callback
    memory.status_callback = status_callback


async def run_agent_until_done(
    controller: AgentController,
    runtime: Runtime,
    memory: Memory,
    end_states: list[AgentState],
) -> None:
    """run_agent_until_done takes a controller and a runtime, and will run.

    the agent until it reaches a terminal state.

    Note that runtime must be connected before being passed in here.
    """
    _validate_status_callbacks(runtime, controller)

    status_callback = _create_status_callback(controller)
    _set_status_callbacks(runtime, controller, memory, status_callback)

    # Kick the agent once to ensure progress starts even if no event arrives
    try:
        controller.step()
    except Exception:
        logger.warning("Initial controller.step() failed", exc_info=True)

    # Actively drive the loop with exponential backoff on consecutive errors
    poll_interval = _INITIAL_POLL_INTERVAL
    consecutive_errors = 0

    while controller.state.agent_state not in end_states:
        await asyncio.sleep(poll_interval)
        try:
            controller.step()
            # Reset backoff on successful step
            poll_interval = _INITIAL_POLL_INTERVAL
            consecutive_errors = 0
        except Exception:
            consecutive_errors += 1
            logger.warning(
                "controller.step() error (%d consecutive)",
                consecutive_errors,
                exc_info=True,
            )
            # Exponential backoff to avoid busy-loop on persistent errors
            poll_interval = min(poll_interval * _BACKOFF_FACTOR, _MAX_POLL_INTERVAL)
            if consecutive_errors >= _MAX_CONSECUTIVE_ERRORS:
                logger.error(
                    "Agent loop exceeded %d consecutive step errors; forcing ERROR state",
                    _MAX_CONSECUTIVE_ERRORS,
                )
                try:
                    await controller.set_agent_state_to(AgentState.ERROR)
                except Exception:
                    logger.error("Failed to force ERROR state", exc_info=True)
                break
