"""Tracks pending actions, timeouts, and confirmation logging."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from typing import TYPE_CHECKING

from backend.core.constants import MCP_PENDING_ACTION_TIMEOUT_FLOOR
from backend.core.logger import app_logger as logger
from backend.ledger import EventSource
from backend.ledger.action import Action
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation_cause import attach_observation_cause

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import OrchestrationContext


class PendingActionService:
    """Maintains pending action state and emits timeout events."""

    def __init__(self, context: OrchestrationContext, timeout: float) -> None:
        self._context = context
        self._timeout = timeout
        self._pending: tuple[Action, float] | None = None
        self._watchdog_handle: asyncio.TimerHandle | threading.Timer | None = None
        self._watchdog_delay_s: float = timeout + 2

    @staticmethod
    def _effective_timeout_seconds(base: float, action: Action) -> float:
        """MCP tool calls often need longer than the default (cold npx, network)."""
        if base <= 0:
            return math.inf
        if type(action).__name__ == "MCPAction":
            return max(float(base), MCP_PENDING_ACTION_TIMEOUT_FLOOR)
        return float(base)

    def set(self, action: Action | None) -> None:
        controller = self._context.get_controller()
        # Cancel any existing watchdog before changing state
        self._cancel_watchdog()
        if action is None:
            if self._pending is not None:
                prev_action, timestamp = self._pending
                self._log_clear(controller, prev_action, timestamp)
            self._pending = None
            return

        action_id = getattr(action, "id", "unknown")
        action_type = type(action).__name__
        controller.log(
            "debug",
            f"Set pending action: {action_type} (id={action_id})",
            extra={"msg_type": "PENDING_ACTION_SET"},
        )
        self._pending = (action, time.time())
        effective = self._effective_timeout_seconds(self._timeout, action)
        self._watchdog_delay_s = effective + 2 if math.isfinite(effective) else 0.0
        # Schedule a watchdog that triggers step() after the timeout, ensuring
        # the timeout check in get() is actually reached even if no other event
        # drives the agent loop forward. Skipped when timeout is disabled (<=0).
        if math.isfinite(effective):
            self._schedule_watchdog()

    def get(self) -> Action | None:
        if self._pending is None:
            return None

        controller = self._context.get_controller()
        action, timestamp = self._pending
        elapsed = time.time() - timestamp
        limit = self._effective_timeout_seconds(self._timeout, action)

        if math.isfinite(limit) and elapsed > limit:
            self._cancel_watchdog()
            self._handle_timeout(controller, action, elapsed)
            self._pending = None
            return None

        if math.isfinite(limit) and elapsed > 60.0 and int(elapsed) % 30 == 0:
            controller.log(
                "info",
                f"Pending action active for {elapsed:.1f}s: {type(action).__name__} "
                f"(id={getattr(action, 'id', 'unknown')})",
                extra={"msg_type": "PENDING_ACTION_TIMEOUT"},
            )
        return action

    def info(self) -> tuple[Action, float] | None:
        if self.get() is None:
            return None
        return self._pending

    def shutdown(self) -> None:
        """Cancel watchdog and clear pending state during controller shutdown."""
        self._cancel_watchdog()
        self._pending = None

    def _log_clear(self, controller, prev_action: Action, timestamp: float) -> None:
        action_id = getattr(prev_action, "id", "unknown")
        action_type = type(prev_action).__name__
        elapsed = time.time() - timestamp
        controller.log(
            "debug",
            f"Cleared pending action after {elapsed:.2f}s: {action_type} (id={action_id})",
            extra={"msg_type": "PENDING_ACTION_CLEARED"},
        )

    def _handle_timeout(self, controller, action: Action, elapsed: float) -> None:
        action_id = getattr(action, "id", "unknown")
        action_type = type(action).__name__
        controller.log(
            "warning",
            f"Pending action timed out after {elapsed:.1f}s, auto-clearing: {action_type} (id={action_id})",
            extra={"msg_type": "PENDING_ACTION_TIMEOUT_CLEARED"},
        )
        timeout_obs = ErrorObservation(
            content=(
                f"Pending action timed out after {elapsed:.1f}s: {action_type}. "
                f"WARNING: The operation may still complete in the background. "
                f"Before proceeding, verify the current state of any files or "
                f"resources this action was modifying to avoid working with "
                f"stale assumptions."
            ),
            error_id="PENDING_ACTION_TIMEOUT",
        )
        attach_observation_cause(
            timeout_obs, action, context="pending_action_service.timeout"
        )
        controller.event_stream.add_event(timeout_obs, EventSource.ENVIRONMENT)

    def _schedule_watchdog(self) -> None:
        """Schedule a delayed trigger_step after the timeout period.

        This ensures the timeout path in get() is reached even when no external
        event drives the agent loop forward (e.g. Memory silently drops the
        RecallAction or the EventStream delivery thread crashes).
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running event loop in this thread. If the process has a
            # registered main loop, bounce back onto it later without blocking
            # the caller. If no loop is available at all, skip watchdog
            # scheduling; timeout enforcement still happens on the next get().
            from backend.utils.async_utils import get_main_event_loop

            main_loop = get_main_event_loop()
            if main_loop is None or not main_loop.is_running():
                logger.debug(
                    "Skipping pending action watchdog scheduling because no active event loop is available"
                )
                return

            timer = threading.Timer(
                self._watchdog_delay_s,
                main_loop.call_soon_threadsafe,
                args=(self._watchdog_fire,),
            )
            timer.daemon = True
            timer.start()
            self._watchdog_handle = timer
            return
        self._watchdog_handle = loop.call_later(
            self._watchdog_delay_s,
            self._watchdog_fire,
        )

    async def _watchdog_async(self) -> None:
        """Async fallback watchdog when no running loop is available at schedule time."""
        await asyncio.sleep(self._watchdog_delay_s)
        self._watchdog_fire()

    def _watchdog_fire(self) -> None:
        """Trigger a step if the pending action is still active (presumably timed out)."""
        self._watchdog_handle = None
        if self._pending is None:
            return
        action, timestamp = self._pending
        elapsed = time.time() - timestamp
        limit = self._effective_timeout_seconds(self._timeout, action)
        if math.isfinite(limit) and elapsed >= limit:
            logger.warning(
                "Pending action watchdog fired after %.1fs for %s (id=%s); triggering step",
                elapsed,
                type(action).__name__,
                getattr(action, "id", "unknown"),
            )
            self._context.trigger_step()

    def _cancel_watchdog(self) -> None:
        """Cancel any scheduled watchdog callback."""
        if self._watchdog_handle is not None:
            self._watchdog_handle.cancel()
            self._watchdog_handle = None


__all__ = ["PendingActionService"]
