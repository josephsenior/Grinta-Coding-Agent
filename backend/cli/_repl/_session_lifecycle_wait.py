"""Agent-wait state machine and timeout helpers for :class:`SessionLifecycleMixin`.

Owns:
- the ``_IDLE_AGENT_STATES`` constant and timeout env-var helpers
  (``_coerce_env_int``, ``_resolve_hard_timeouts``, ``_active_timeout``);
- ``_fire_idle_notification`` — desktop notification when the agent reaches
  an idle state;
- ``_wait_for_agent_idle`` — the main async loop that drains the renderer,
  handles confirmation prompts inline, and watches the hard-timeout
  budget;
- ``_handle_idle_or_confirmation`` / ``_handle_agent_hard_timeout`` /
  ``_drain_renderer_until_settled`` — the per-iteration helpers.

``time.monotonic`` is read here because the test suite patches
``backend.cli._repl.session_lifecycle_mixin.time.monotonic`` — since
``time`` is a module object shared across all importers, any caller
of ``time.monotonic`` sees the patched value.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from typing import TYPE_CHECKING, Any, cast

from backend.core.enums import AgentState

if TYPE_CHECKING:
    from backend.cli._typing import SessionLifecycleHost

logger = logging.getLogger(__name__)


_IDLE_AGENT_STATES: frozenset[AgentState] = frozenset(
    {
        AgentState.AWAITING_USER_INPUT,
        AgentState.FINISHED,
        AgentState.ERROR,
        AgentState.STOPPED,
        AgentState.REJECTED,
    }
)


def _coerce_env_int(name: str, default: int = 0, *, floor: int = 0) -> int:
    raw = os.getenv(name, str(default))
    try:
        return max(floor, int(raw))
    except (ValueError, TypeError):
        return default


def _resolve_hard_timeouts() -> tuple[int, int]:
    hard = _coerce_env_int('APP_AGENT_HARD_TIMEOUT_SECONDS')
    cmd = _coerce_env_int('APP_AGENT_HARD_TIMEOUT_CMD_SECONDS')
    if hard > 0 and cmd > 0:
        cmd = max(hard, cmd)
    return hard, cmd


def _active_timeout(controller: Any, hard_timeout: int, cmd_timeout: int) -> int:
    active = hard_timeout
    pending_action = getattr(controller, '_pending_action', None)
    if pending_action is None or cmd_timeout <= 0:
        return active
    with contextlib.suppress(Exception):
        from backend.ledger.action import CmdRunAction

        if isinstance(pending_action, CmdRunAction):
            active = cmd_timeout
    return active


def _fire_idle_notification(state: AgentState) -> None:
    """Fire a desktop notification when the agent reaches an idle state."""
    from backend.cli.notifications import notify_agent_error, notify_agent_idle

    if state == AgentState.ERROR:
        notify_agent_error()
    elif state == AgentState.AWAITING_USER_INPUT:
        notify_agent_idle(needs_input=True)
    elif state in (AgentState.FINISHED, AgentState.STOPPED):
        notify_agent_idle(needs_input=False)


async def _wait_for_agent_idle(
    host: 'SessionLifecycleHost',
    controller: Any,
    agent_task: asyncio.Task[Any] | None,
) -> None:
    """Wait until agent is idle, handling confirmation prompts inline.

    Events are now processed directly in the EventStream delivery thread
    (no 3rd hop to the main loop), so the renderer state stays nearly in
    sync with the agent.  A brief yield after task completion is enough to
    let any in-flight deliveries finish.
    """
    # Disabled by default to avoid aborting long-running sessions.
    # Set APP_AGENT_HARD_TIMEOUT_SECONDS / APP_AGENT_HARD_TIMEOUT_CMD_SECONDS
    # to a positive value to re-enable limits.
    hard_timeout, cmd_timeout = _resolve_hard_timeouts()
    start = time.monotonic()
    last_periodic_drain = start
    self_obj = cast(Any, host)

    while True:
        renderer = host._renderer

        # Drain queued events and render — this is the ONLY place
        # where Live.update() happens during agent execution.
        if renderer is not None:
            renderer.drain_events()
        state = controller.get_agent_state()

        if await host._handle_idle_or_confirmation(
            controller,
            renderer,
            state,
        ):
            break

        # Agent task finished — drain any remaining events, then break.
        if agent_task and agent_task.done():
            if renderer is not None:
                # Final settle after task completion to catch late events.
                await self_obj._drain_renderer_until_settled(
                    renderer, settle_delay=0.05
                )
            break

        # Yield to the event loop.  wait_for_state_change will return
        # early when the delivery thread sets _state_event.
        if renderer is None:
            await asyncio.sleep(0.1)
        else:
            await renderer.wait_for_state_change(wait_timeout_sec=0.1)
            # Keep transcript rendering moving even if no explicit state
            # transition arrives (e.g. long-running tool with queued output).
            renderer.drain_events()
            now = time.monotonic()
            if now - last_periodic_drain >= 0.5:
                renderer.refresh(force=True)
                last_periodic_drain = now

        # Hard timeout — surface error and return to prompt instead of
        # hanging forever (e.g. LLM API unresponsive). Allow a longer
        # budget while a foreground command action is still pending.
        active_timeout = _active_timeout(
            controller,
            hard_timeout,
            cmd_timeout,
        )
        if active_timeout > 0 and time.monotonic() - start > active_timeout:
            await self_obj._handle_agent_hard_timeout(
                renderer,
                agent_task,
                active_timeout,
            )
            break


async def _handle_idle_or_confirmation(
    host: 'SessionLifecycleHost',
    controller: Any,
    renderer: Any,
    state: AgentState,
) -> bool:
    """Return True when the wait loop should break out (agent is idle)."""
    self_obj = cast(Any, host)
    if state in _IDLE_AGENT_STATES:
        # Reset confirmation counter when agent leaves confirmation state.
        if hasattr(self_obj, '_confirmation_prompt_count'):
            self_obj._confirmation_prompt_count = 0
        if renderer is not None:
            await self_obj._drain_renderer_until_settled(renderer)
            state = controller.get_agent_state()
        if state == AgentState.AWAITING_USER_CONFIRMATION:
            await self_obj._handle_confirmation(controller)
            return False
        if state in _IDLE_AGENT_STATES:
            _fire_idle_notification(state)
            return True
        return False
    if state == AgentState.AWAITING_USER_CONFIRMATION:
        await self_obj._handle_confirmation(controller)
    return False


async def _handle_agent_hard_timeout(
    host: 'SessionLifecycleHost',
    renderer: Any,
    agent_task: asyncio.Task[Any] | None,
    active_timeout: int,
) -> None:
    logger.warning('Agent wait exceeded %ds hard timeout', active_timeout)
    from backend.cli.notifications import notify
    from backend.core.enums import AgentState

    notify(
        'Grinta — Timeout',
        f'Agent timed out after {active_timeout} seconds.',
        urgency='critical',
    )
    if renderer is not None:
        renderer.add_system_message(
            f'Agent timed out after {active_timeout} seconds. Returning to prompt.',
            title='⏱ Timeout',
        )
        renderer.drain_events()
    # Cancel the stale task so it does not linger into the next turn.
    if agent_task and not agent_task.done():
        agent_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await agent_task
    # Transition controller out of RUNNING so the next user message
    # starts from a clean, valid state machine position.
    controller = getattr(host, '_controller', None)
    if controller is not None:
        with contextlib.suppress(Exception):
            await controller.set_agent_state_to(AgentState.ERROR)


async def _drain_renderer_until_settled(
    renderer: Any,
    *,
    settle_delay: float = 0.05,
    max_passes: int = 4,
) -> None:
    """Drain queued CLI events until the delivery queue stays quiet briefly."""
    for _ in range(max_passes):
        renderer.drain_events()
        if getattr(renderer, 'pending_event_count', 0) == 0:
            await asyncio.sleep(settle_delay)
            renderer.drain_events()
            if getattr(renderer, 'pending_event_count', 0) == 0:
                return
        else:
            await asyncio.sleep(settle_delay)
