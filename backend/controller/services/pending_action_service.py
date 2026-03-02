"""Tracks pending actions, timeouts, and confirmation logging."""

from __future__ import annotations

import contextlib
import time
from typing import TYPE_CHECKING

from backend.events import EventSource
from backend.events.action import Action
from backend.events.observation import ErrorObservation

if TYPE_CHECKING:
    from backend.controller.services.controller_context import ControllerContext


class PendingActionService:
    """Maintains pending action state and emits timeout events."""

    def __init__(self, context: ControllerContext, timeout: float) -> None:
        self._context = context
        self._timeout = timeout
        self._pending: tuple[Action, float] | None = None

    def set(self, action: Action | None) -> None:
        controller = self._context.get_controller()
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

    def get(self) -> Action | None:
        if self._pending is None:
            return None

        controller = self._context.get_controller()
        action, timestamp = self._pending
        elapsed = time.time() - timestamp

        if elapsed > self._timeout:
            self._handle_timeout(controller, action, elapsed)
            self._pending = None
            return None

        if elapsed > 60.0 and int(elapsed) % 30 == 0:
            controller.log(
                "info",
                f"Pending action active for {elapsed:.1f}s: {type(action).__name__} "
                f"(id={getattr(action, 'id', 'unknown')})",
                extra={"msg_type": "PENDING_ACTION_TIMEOUT"},
            )
        return action

    def info(self) -> tuple[Action, float] | None:
        return self._pending

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
        cause_value: int | None = None
        if action_id != "unknown":
            with contextlib.suppress(TypeError, ValueError):
                cause_value = int(action_id)
        timeout_obs.cause = cause_value
        controller.event_stream.add_event(timeout_obs, EventSource.ENVIRONMENT)
