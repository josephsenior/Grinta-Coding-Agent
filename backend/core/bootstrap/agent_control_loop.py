"""Agent control loop helpers for running runtimes and handling status callbacks."""

import asyncio
from collections.abc import Callable

from backend.context.agent_memory import Memory
from backend.core.enums import RuntimeStatus
from backend.core.logger import app_logger as logger
from backend.core.schemas import AgentState
from backend.core.suspend_aware_deadline import SuspendAwareDeadline
from backend.execution.base import Runtime
from backend.orchestration import SessionOrchestrator
from backend.utils.async_utils import run_or_schedule


def _handle_error_status(
    controller: SessionOrchestrator, runtime_status: RuntimeStatus, msg: str
) -> None:
    """Handle error status in the status callback."""
    if controller:
        controller.state.set_last_error(msg, source='loop.status_callback')
        try:
            if runtime_status == RuntimeStatus.ERROR_MEMORY:
                setattr(
                    controller.state,
                    '_memory_error_boundary',
                    controller.state.iteration_flag.current_value,
                )
                logger.info(
                    'LOOP.status_callback: memory error boundary recorded at iteration %s',
                    controller.state.iteration_flag.current_value,
                )
        except Exception:
            logger.debug('Failed to record memory error boundary', exc_info=True)
        # Late runtime callbacks may fire after the user stopped/finished the
        # agent; do not promote those diagnostics to ERROR.  The agent's
        # state stays STOPPED/FINISHED — a transition to ERROR would raise
        # InvalidStateTransitionError and blur the WAL semantics.
        if controller.get_agent_state() in (
            AgentState.STOPPED,
            AgentState.FINISHED,
        ):
            logger.info(
                'Runtime error callback: skipping agent ERROR transition while state is %s',
                controller.get_agent_state().value,
            )
        else:
            try:
                run_or_schedule(controller.set_agent_state_to(AgentState.ERROR))
            except Exception:
                logger.warning(
                    'Failed to schedule ERROR state transition via run_or_schedule',
                    exc_info=True,
                )
                try:
                    from backend.utils.async_utils import create_tracked_task

                    create_tracked_task(
                        controller.set_agent_state_to(AgentState.ERROR),
                        name='error-state-fallback',
                    )
                except Exception:
                    logger.error(
                        'All attempts to transition agent to ERROR state failed',
                        exc_info=True,
                    )


def _create_status_callback(
    controller: SessionOrchestrator,
) -> Callable[[str, RuntimeStatus, str], None]:
    """Create the status callback function."""

    def status_callback(msg_type: str, runtime_status: RuntimeStatus, msg: str) -> None:
        """Handle runtime status updates.

        Args:
            msg_type: Message type (error, info, etc.)
            runtime_status: Runtime status object
            msg: Status message

        """
        if msg_type == 'error':
            logger.error(msg)
            _handle_error_status(controller, runtime_status, msg)
        else:
            logger.info(msg)

    return status_callback


def _validate_status_callbacks(
    runtime: Runtime, controller: SessionOrchestrator
) -> None:
    """Validate that status callbacks are not already set."""
    if getattr(runtime, 'status_callback', None):
        logger.debug('Runtime status_callback already set; overriding in run loop')
    if getattr(controller, 'status_callback', None):
        logger.debug('Controller status_callback already set; overriding in run loop')


def _set_status_callbacks(
    runtime: Runtime,
    controller: SessionOrchestrator,
    memory: Memory,
    status_callback: Callable[[str, RuntimeStatus, str], None],
) -> None:
    """Set status callbacks on runtime, controller, and memory."""
    runtime.status_callback = status_callback
    controller.status_callback = status_callback
    memory.status_callback = status_callback


def _apply_freeze_credit(
    started: float, slept: float, poll_interval: float, grace: float
) -> tuple[float, float]:
    """Credit a detected freeze back to the run deadline (test/helper shim)."""
    overrun = slept - poll_interval
    if overrun > grace:
        return started + overrun, overrun
    return started, 0.0


async def run_agent_until_done(
    controller: SessionOrchestrator,
    runtime: Runtime,
    memory: Memory,
    end_states: list[AgentState],
) -> None:
    """run_agent_until_done takes a controller and a runtime, and will run.

    the agent until it reaches a terminal state.

    Note that runtime must be connected before being passed in here.
    """
    _validate_status_callbacks(runtime, controller)

    # Set session ID for working memory scoping — isolates working memory
    # across concurrent/sequential sessions on the same workspace.
    try:
        from backend.engine.tools.working_memory import set_current_session_id

        session_id = getattr(controller, 'id', None)
        set_current_session_id(session_id)
    except Exception:
        logger.debug('Failed to set working memory session ID', exc_info=True)

    # Auto-sync scratchpad to working_memory at session start
    try:
        from backend.engine.tools.note import _load_notes
        from backend.engine.tools.working_memory import (
            sync_scratchpad_to_working_memory,
        )

        notes = _load_notes()
        if notes:
            sync_scratchpad_to_working_memory(notes)
    except Exception:
        pass

    status_callback = _create_status_callback(controller)
    _set_status_callbacks(runtime, controller, memory, status_callback)

    # Skip the initial step if the controller is already in an end state or not
    # in a stepping-compatible state (e.g. restored from a crashed session).
    if controller.state.agent_state not in end_states:
        try:
            controller.step()
        except Exception:
            logger.warning('Initial controller.step() failed', exc_info=True)

    # Wait for the agent to reach an end state.  Steps are driven by the
    # event-driven mechanism (observation_service.trigger_step, _on_event ->
    # should_step, etc.) rather than by polling.  The initial step() above kicks
    # things off; all subsequent steps are triggered by events.
    #
    # A timeout guard prevents orphaned polling when the event-driven state
    # machine stalls (e.g. due to a provider outage or infinite loop).
    import time as _time

    from backend.core.constants import (
        DEFAULT_AGENT_RUN_FREEZE_GRACE_SECONDS,
        DEFAULT_AGENT_RUN_HARD_TIMEOUT_SECONDS,
    )

    _POLL_INTERVAL = 0.5
    _max_poll_seconds = DEFAULT_AGENT_RUN_HARD_TIMEOUT_SECONDS
    _freeze_grace = DEFAULT_AGENT_RUN_FREEZE_GRACE_SECONDS
    deadline = SuspendAwareDeadline(
        _max_poll_seconds,
        poll_interval=_POLL_INTERVAL,
        freeze_grace_seconds=_freeze_grace,
    )
    _ran_loop = False
    try:
        while controller.state.agent_state not in end_states:  # noqa: ASYNC110
            _ran_loop = True
            _before_sleep = _time.monotonic()
            await asyncio.sleep(_POLL_INTERVAL)
            _slept = _time.monotonic() - _before_sleep
            _credited = deadline.credit_poll_sleep(_slept)
            if _credited > 0:
                logger.warning(
                    'run_agent_until_done: detected ~%.0fs freeze (poll sleep '
                    'overran by %.0fs) — likely OS suspend or a blocked loop. '
                    'Frozen time credited back to the run budget; not counted '
                    'as an agent hang.',
                    _slept,
                    _credited,
                    extra={
                        'msg_type': 'AGENT_RUN_FREEZE_CREDIT',
                        'frozen_seconds': round(_credited, 1),
                    },
                )
            if deadline.expired():
                logger.error(
                    'run_agent_until_done: HARD TIMEOUT after %.0fs in state=%s',
                    _max_poll_seconds,
                    controller.state.agent_state,
                    extra={'msg_type': 'AGENT_HARD_TIMEOUT'},
                )
                try:
                    await controller.set_agent_state_to(AgentState.ERROR)
                except Exception:
                    pass
                break
    finally:
        deadline.close()
        if _ran_loop:
            # Drain is intentionally omitted here — the TUI gates new messages on
            # _agent_task.done(), and this cleanup delays completion. Background
            # tasks are independently scheduled and don't need this coroutine to
            # wait for them.  The TUI's run_tui finally block handles final drain.
            pass
