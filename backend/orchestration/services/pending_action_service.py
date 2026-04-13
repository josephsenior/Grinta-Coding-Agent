"""Tracks pending actions, timeouts, and confirmation logging."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from typing import TYPE_CHECKING, Any, cast

from backend.core.constants import (
    CMD_PENDING_ACTION_TIMEOUT_FLOOR,
    MCP_PENDING_ACTION_TIMEOUT_FLOOR,
)
from backend.core.logger import app_logger as logger
from backend.ledger import EventSource
from backend.ledger.action import Action
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation_cause import attach_observation_cause

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )


class PendingActionService:
    """Maintains pending action state and emits timeout events.

    Multiple runnable actions may be in flight (e.g. overlapping async delivery,
    or a revived parallel batch).  We track **every** outstanding action by stream
    id so an observation with ``cause=<id>`` resolves the correct row without
    colliding when a newer action overwrote the single-slot ``_pending`` model.
    """

    def __init__(self, context: OrchestrationContext, timeout: float) -> None:
        self._context = context
        self._timeout = timeout
        self._outstanding: dict[int, tuple[Action, float]] = {}
        self._legacy_pending: tuple[Action, float] | None = None
        self._watchdog_handle: asyncio.TimerHandle | threading.Timer | None = None
        self._watchdog_delay_s: float = timeout + 2

    @staticmethod
    def _effective_timeout_seconds(base: float, action: Action) -> float:
        """MCP tool calls often need longer than the default (cold npx, network).

        Delegated tasks run sub-agents that may take many minutes; use infinite timeout.
        """
        if base <= 0:
            return math.inf
        if type(action).__name__ == 'DelegateTaskAction':
            return math.inf
        if type(action).__name__ == 'CmdRunAction':
            # Shell commands have their own runtime timeout model; keep the
            # pending watchdog from clearing active installs/builds too early.
            action_timeout = getattr(action, 'timeout', None)
            try:
                parsed_action_timeout = (
                    float(action_timeout) if action_timeout is not None else None
                )
            except (TypeError, ValueError):
                parsed_action_timeout = None

            candidates = [float(base), CMD_PENDING_ACTION_TIMEOUT_FLOOR]
            if parsed_action_timeout is not None and parsed_action_timeout > 0:
                candidates.append(parsed_action_timeout)
            return max(candidates)
        if type(action).__name__ == 'MCPAction':
            return max(float(base), MCP_PENDING_ACTION_TIMEOUT_FLOOR)
        return float(base)

    @staticmethod
    def _int_action_id(action: Action) -> int | None:
        raw = getattr(action, 'id', None)
        try:
            return int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    def set(self, action: Action | None) -> None:
        controller = self._context.get_controller()
        self._cancel_watchdog()
        if action is None:
            for act, ts in list(self._outstanding.values()):
                self._log_clear(controller, act, ts)
            self._outstanding.clear()
            if self._legacy_pending is not None:
                act, ts = self._legacy_pending
                self._log_clear(controller, act, ts)
                self._legacy_pending = None
            return

        action_id = getattr(action, 'id', 'unknown')
        action_type = type(action).__name__
        controller.log(
            'debug',
            f'Set pending action: {action_type} (id={action_id})',
            extra={'msg_type': 'PENDING_ACTION_SET'},
        )
        now = time.time()
        aid = self._int_action_id(action)
        if aid is not None:
            self._outstanding[aid] = (action, now)
        else:
            self._legacy_pending = (action, now)

        self._schedule_watchdog_if_needed()

    def peek_for_cause(self, cause: object | None) -> Action | None:
        """Return the pending action for *cause* without removing it (for observation routing)."""
        if cause is None:
            return None
        try:
            cid = int(cast(Any, cause))
        except (TypeError, ValueError):
            return None
        self._purge_timeouts()
        entry = self._outstanding.get(cid)
        return entry[0] if entry else None

    def has_outstanding_for_cause(self, cause: object | None) -> bool:
        """True if *cause* maps to a stream id currently present in ``_outstanding``."""
        if cause is None:
            return False
        try:
            cid = int(cast(Any, cause))
        except (TypeError, ValueError):
            return False
        self._purge_timeouts()
        return cid in self._outstanding

    def pop_for_cause(self, cause: object | None) -> Action | None:
        """Remove and return the pending action whose stream id equals *cause*."""
        if cause is None:
            return None
        try:
            cid = int(cast(Any, cause))
        except (TypeError, ValueError):
            return None
        self._purge_timeouts()
        entry = self._outstanding.pop(cid, None)
        if entry is None:
            return None
        action, ts = entry
        self._log_clear(self._context.get_controller(), action, ts)
        self._schedule_watchdog_if_needed()
        return action

    def _primary_entry(self) -> tuple[Action, float] | None:
        """Latest / highest-id outstanding row (for step guards and logging)."""
        if not self._outstanding:
            return self._legacy_pending
        best_id = max(self._outstanding.keys())
        return self._outstanding[best_id]

    def _purge_timeouts(self) -> None:
        controller = self._context.get_controller()
        now = time.time()
        dead: list[int] = []
        for aid, (action, ts) in list(self._outstanding.items()):
            elapsed = now - ts
            limit = self._effective_timeout_seconds(self._timeout, action)
            if math.isfinite(limit) and elapsed > limit:
                self._handle_timeout(controller, action, elapsed)
                dead.append(aid)
        for aid in dead:
            self._outstanding.pop(aid, None)

        if self._legacy_pending is not None:
            action, ts = self._legacy_pending
            elapsed = now - ts
            limit = self._effective_timeout_seconds(self._timeout, action)
            if math.isfinite(limit) and elapsed > limit:
                self._handle_timeout(controller, action, elapsed)
                self._legacy_pending = None

    def get(self) -> Action | None:
        self._purge_timeouts()
        primary = self._primary_entry()
        if primary is None:
            return None
        action, timestamp = primary
        controller = self._context.get_controller()
        elapsed = time.time() - timestamp
        limit = self._effective_timeout_seconds(self._timeout, action)

        if math.isfinite(limit) and elapsed > 60.0 and int(elapsed) % 30 == 0:
            controller.log(
                'info',
                f'Pending action active for {elapsed:.1f}s: {type(action).__name__} '
                f'(id={getattr(action, "id", "unknown")})',
                extra={'msg_type': 'PENDING_ACTION_TIMEOUT'},
            )
        return action

    def info(self) -> tuple[Action, float] | None:
        self._purge_timeouts()
        return self._primary_entry()

    def shutdown(self) -> None:
        """Cancel watchdog and clear pending state during controller shutdown."""
        self._cancel_watchdog()
        self._outstanding.clear()
        self._legacy_pending = None

    def _log_clear(self, controller, prev_action: Action, timestamp: float) -> None:
        action_id = getattr(prev_action, 'id', 'unknown')
        action_type = type(prev_action).__name__
        elapsed = time.time() - timestamp
        controller.log(
            'debug',
            f'Cleared pending action after {elapsed:.2f}s: {action_type} (id={action_id})',
            extra={'msg_type': 'PENDING_ACTION_CLEARED'},
        )

    def _handle_timeout(self, controller, action: Action, elapsed: float) -> None:
        self._cancel_watchdog()
        action_id = getattr(action, 'id', 'unknown')
        action_type = type(action).__name__
        controller.log(
            'warning',
            f'Pending action timed out after {elapsed:.1f}s, auto-clearing: {action_type} (id={action_id})',
            extra={'msg_type': 'PENDING_ACTION_TIMEOUT_CLEARED'},
        )
        timeout_obs = ErrorObservation(
            content=(
                f'Pending action timed out after {elapsed:.1f}s: {action_type}. '
                f'WARNING: The operation may still complete in the background. '
                f'Before proceeding, verify the current state of any files or '
                f'resources this action was modifying to avoid working with '
                f'stale assumptions.'
            ),
            error_id='PENDING_ACTION_TIMEOUT',
        )
        attach_observation_cause(
            timeout_obs, action, context='pending_action_service.timeout'
        )
        controller.event_stream.add_event(timeout_obs, EventSource.ENVIRONMENT)

    def _schedule_watchdog_if_needed(self) -> None:
        """Schedule the next watchdog using the soonest finite timeout among rows."""
        self._cancel_watchdog()
        delays: list[float] = []
        for action, _ts in self._outstanding.values():
            eff = self._effective_timeout_seconds(self._timeout, action)
            if math.isfinite(eff):
                delays.append(eff + 2.0)
        if self._legacy_pending is not None:
            eff = self._effective_timeout_seconds(self._timeout, self._legacy_pending[0])
            if math.isfinite(eff):
                delays.append(eff + 2.0)
        if not delays:
            return
        self._watchdog_delay_s = min(delays)
        self._schedule_watchdog()

    def _schedule_watchdog(self) -> None:
        """Schedule a delayed trigger_step after the timeout period."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            from backend.utils.async_utils import get_main_event_loop

            main_loop = get_main_event_loop()
            if main_loop is None or not main_loop.is_running():
                logger.debug(
                    'Skipping pending action watchdog scheduling because no active event loop is available'
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

    def _watchdog_fire(self) -> None:
        """Trigger a step if any pending action is still active."""
        self._watchdog_handle = None
        if not self._outstanding and self._legacy_pending is None:
            return
        logger.warning(
            'Pending action watchdog fired; triggering step (outstanding ids=%s)',
            list(self._outstanding.keys()),
        )
        self._context.trigger_step()

    def _cancel_watchdog(self) -> None:
        if self._watchdog_handle is not None:
            self._watchdog_handle.cancel()
            self._watchdog_handle = None


__all__ = ['PendingActionService']
