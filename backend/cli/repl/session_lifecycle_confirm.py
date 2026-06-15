"""Interrupt and confirmation handlers for :class:`SessionLifecycleMixin`.

Owns:
- ``_cancel_agent`` — interrupt a running agent task: cancel the task,
  hard-kill shells, stop the controller cleanly, and stop the reasoning
  stream.
- ``_handle_confirmation`` — render the Y/N confirmation prompt and feed
  the user's decision back to the controller via
  ``controller.apply_user_decision()``, with a guard against infinite
  confirmation loops and a per-session "remember always allow"
  affordance.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, Any, cast

from backend.cli.settings.confirmation import (
    render_confirmation,
)

if TYPE_CHECKING:
    from backend.cli._typing import SessionLifecycleHost

logger = logging.getLogger(__name__)


async def _cancel_agent(
    host: 'SessionLifecycleHost',
    agent_task: asyncio.Task[Any] | None,
) -> None:
    """Cancel a running agent task and return to the prompt."""
    if agent_task and not agent_task.done():
        agent_task.cancel()
        try:
            await asyncio.wait_for(agent_task, timeout=5.0)
        except (asyncio.CancelledError, asyncio.TimeoutError, Exception):
            pass

    # Clear stale _next_action to prevent swallowing user messages after interrupt
    host._next_action = None

    # Hard kill underlying shells/processes
    with contextlib.suppress(Exception):
        from backend.execution.action_execution_server import (
            client as runtime_client,
        )

        if runtime_client is not None:
            await runtime_client.hard_kill()

    # Stop orchestrator cleanly (no ErrorObservation for interrupted tools)
    if host._controller is not None:
        mark = getattr(host._controller, 'mark_user_interrupt_stop', None)
        if callable(mark):
            mark()
        with contextlib.suppress(Exception):
            await host._controller.stop()

    host._reasoning.stop()
    if host._renderer is not None:
        host._renderer.add_system_message(
            'Interrupted. Ready for input.', title='grinta'
        )


async def _apply_decision(controller: Any, approved: bool) -> None:
    apply = getattr(controller, 'apply_user_decision', None)
    if callable(apply):
        await apply(approved=approved)


def _get_pending_action(controller: Any) -> Any:
    try:
        return controller.get_pending_action()
    except Exception:
        logger.debug('get_pending_action() failed, trying fallback', exc_info=True)
        return getattr(controller, '_pending_action', None)


async def _check_confirmation_loop(
    host: 'SessionLifecycleHost', controller: Any
) -> bool:
    """Returns True if loop detected and handled (caller should return)."""
    if not hasattr(host, '_confirmation_prompt_count'):
        host._confirmation_prompt_count = 0
    host._confirmation_prompt_count += 1
    if host._confirmation_prompt_count > 5:
        logger.warning(
            'Confirmation loop detected (%d prompts), auto-rejecting',
            host._confirmation_prompt_count,
        )
        if host._renderer is not None:
            host._renderer.add_system_message(
                'Confirmation loop detected \u2014 auto-rejecting to prevent hang.',
                title='warning',
            )
        await _apply_decision(controller, approved=False)
        host._confirmation_prompt_count = 0
        return True
    return False


async def _try_auto_approve_low_risk(
    host: 'SessionLifecycleHost', controller: Any, pending: Any
) -> bool:
    """Returns True if auto-approved (caller should return)."""
    if pending is None or not host._suppress_low_risk_confirmations:
        return False
    from backend.core.enums import ActionSecurityRisk

    risk = getattr(pending, 'security_risk', ActionSecurityRisk.UNKNOWN)
    if risk == ActionSecurityRisk.LOW:
        await _apply_decision(controller, approved=True)
        return True
    return False


def _render_decision(
    host: 'SessionLifecycleHost', pending: Any
) -> tuple[bool, bool, bool]:
    """Returns (approved, remember_always, suppress_low_risk)."""
    if pending is not None:
        if host._renderer is not None:
            with host._renderer.suspend_live():
                decision = render_confirmation(host._console, pending)
        else:
            decision = render_confirmation(host._console, pending)
        return decision.approved, decision.remember, decision.suppress_low_risk

    from rich.prompt import Confirm

    prompt = '[bold yellow]The agent wants to execute an action. Approve?[/bold yellow]'
    if host._renderer is not None:
        with host._renderer.suspend_live():
            approved = Confirm.ask(prompt, console=cast(Any, host._console))
    else:
        approved = Confirm.ask(prompt, console=cast(Any, host._console))
    return approved, False, False


async def _apply_autonomy_decisions(
    host: 'SessionLifecycleHost',
    controller: Any,
    pending: Any,
    approved: bool,
    remember_always: bool,
    suppress_low_risk: bool,
) -> None:
    if remember_always and approved and pending is not None:
        ac = getattr(controller, 'autonomy_controller', None)
        if ac is not None and hasattr(ac, 'remember_always_allow'):
            try:
                ac.remember_always_allow(pending)
                if host._renderer is not None:
                    host._renderer.add_system_message(
                        'Remembered for this session \u2014 will not ask again for this exact action.',
                        title='autonomy',
                    )
            except Exception:
                logger.debug('remember_always_allow failed', exc_info=True)

    if suppress_low_risk and approved:
        host._suppress_low_risk_confirmations = True
        if host._renderer is not None:
            host._renderer.add_system_message(
                'LOW-risk actions will be auto-approved for the rest of this session.',
                title='autonomy',
            )


async def _handle_confirmation(
    host: 'SessionLifecycleHost',
    controller: Any,
) -> None:
    """Prompt user for Y/N on a pending action, then resume the engine."""
    if await _check_confirmation_loop(host, controller):
        return

    pending = _get_pending_action(controller)

    if await _try_auto_approve_low_risk(host, controller, pending):
        return

    approved, remember_always, suppress_low_risk = _render_decision(host, pending)

    await _apply_autonomy_decisions(
        host, controller, pending, approved, remember_always, suppress_low_risk
    )

    await _apply_decision(controller, approved=approved)
