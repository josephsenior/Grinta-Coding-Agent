"""Tracks pending actions, timeouts, and confirmation logging."""

from __future__ import annotations

import asyncio
import math
import threading
import time
from typing import TYPE_CHECKING, Any, cast

from backend.core.constants import (
    BROWSER_TOOL_SYNC_TIMEOUT_SECONDS,
    DEBUGGER_PENDING_ACTION_TIMEOUT_FLOOR,
    MCP_PENDING_ACTION_TIMEOUT_FLOOR,
    TERMINAL_IO_PENDING_ACTION_TIMEOUT_FLOOR,
    TERMINAL_RUN_PENDING_ACTION_TIMEOUT_FLOOR,
)
from backend.core.logger import app_logger as logger
from backend.core.timeout_policy import effective_cmd_run_pending_timeout_seconds
from backend.ledger import EventSource
from backend.ledger.action import Action, ActionConfirmationStatus
from backend.ledger.observation import ErrorObservation
from backend.ledger.observation_cause import attach_observation_cause

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import (
        OrchestrationContext,
    )


def _cmd_run_pending_timeout(base: float, action: Action) -> float:
    return effective_cmd_run_pending_timeout_seconds(base, action)


def _terminal_run_pending_timeout(base: float, _action: Action) -> float:
    return max(float(base), float(TERMINAL_RUN_PENDING_ACTION_TIMEOUT_FLOOR))


def _terminal_io_pending_timeout(base: float, _action: Action) -> float:
    return max(float(base), float(TERMINAL_IO_PENDING_ACTION_TIMEOUT_FLOOR))


def _debugger_pending_timeout(base: float, action: Action) -> float:
    """Honour an explicit action ``timeout`` and apply the debugger floor.

    DAP step / continue / breakpoint waits routinely exceed 60 s when the
    debuggee is doing slow native work, blocking I/O, or deep recursion. The
    previous 60 s clamp produced false-positive timeouts on legitimate slow
    steps. We now use ``DEBUGGER_PENDING_ACTION_TIMEOUT_FLOOR`` (matches the
    terminal/cmd floor) and let the action's own ``timeout`` extend it
    further when the agent set one explicitly.
    """
    action_timeout = getattr(action, 'timeout', None)
    try:
        parsed_timeout = float(action_timeout) if action_timeout is not None else None
    except (TypeError, ValueError):
        parsed_timeout = None

    candidates = [float(base), float(DEBUGGER_PENDING_ACTION_TIMEOUT_FLOOR)]
    if parsed_timeout is not None and parsed_timeout > 0:
        candidates.append(parsed_timeout + 5.0)
    return max(candidates)


def _identity_pending_timeout(base: float, _action: Action) -> float:
    return float(base)


def _infinite_pending_timeout(_base: float, _action: Action) -> float:
    return math.inf


def _is_awaiting_confirmation(action: Action) -> bool:
    state = getattr(action, 'confirmation_state', None)
    state = getattr(state, 'value', state)
    return (
        str(state or '').strip().lower()
        == ActionConfirmationStatus.AWAITING_CONFIRMATION.value
    )


def _delegate_task_pending_timeout(base: float, action: Action) -> float:
    """DelegateTaskAction timeout: use worker timeout from constants.

    Workers have a configurable timeout (default 5 minutes) to prevent
    infinite hangs. This is much better than the previous infinite timeout.
    """
    from backend.core.constants import DELEGATE_WORKER_TIMEOUT_SECONDS

    # Use the worker timeout, but ensure it's at least the base timeout
    return max(float(base), DELEGATE_WORKER_TIMEOUT_SECONDS)


_TIMEOUT_POLICY_BY_ACTION_NAME = {
    'DelegateTaskAction': _delegate_task_pending_timeout,
    'CmdRunAction': _cmd_run_pending_timeout,
    'MCPAction': lambda base, _action: max(
        float(base), MCP_PENDING_ACTION_TIMEOUT_FLOOR
    ),
    'BrowserToolAction': lambda base, _action: max(
        float(base), float(BROWSER_TOOL_SYNC_TIMEOUT_SECONDS)
    ),
    'TerminalRunAction': _terminal_run_pending_timeout,
    'TerminalInputAction': _terminal_io_pending_timeout,
    'TerminalReadAction': _terminal_io_pending_timeout,
    'DebuggerAction': _debugger_pending_timeout,
}


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
        self._progress_log_buckets: dict[int | str, int] = {}
        self._timing_out_ids: set[int] = set()
        self._watchdog_handle: asyncio.TimerHandle | threading.Timer | None = None
        self._watchdog_delay_s: float = timeout + 2
        self._lock = threading.Lock()

    @staticmethod
    def _effective_timeout_seconds(base: float, action: Action) -> float:
        """MCP tool calls often need longer than the default (cold npx, network).

        Delegated tasks run sub-agents with a configurable timeout (default 5 minutes).
        Terminal* actions (terminal_manager) use a high floor like CmdRunAction.
        """
        if _is_awaiting_confirmation(action):
            return math.inf
        if base <= 0:
            return math.inf

        action_name = type(action).__name__
        policy = _TIMEOUT_POLICY_BY_ACTION_NAME.get(
            action_name, _identity_pending_timeout
        )
        return policy(base, action)

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
                self._log_clear(controller, act, ts, clear_reason='clear_all')
            self._outstanding.clear()
            if self._legacy_pending is not None:
                act, ts = self._legacy_pending
                self._log_clear(controller, act, ts, clear_reason='clear_all')
                self._legacy_pending = None
            self._progress_log_buckets.clear()
            self._timing_out_ids.clear()
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
            self._progress_log_buckets.pop(aid, None)
        else:
            self._legacy_pending = (action, now)
            self._progress_log_buckets.pop('legacy', None)

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
        self._progress_log_buckets.pop(cid, None)
        self._log_clear(
            self._context.get_controller(), action, ts, clear_reason='pop_for_cause'
        )
        self._schedule_watchdog_if_needed()
        return action

    def clear_for_action(self, action: Action) -> None:
        """Remove only the outstanding row for *action* (parallel-safe clear)."""
        controller = self._context.get_controller()
        aid = self._int_action_id(action)
        if aid is not None and aid in self._outstanding:
            act, ts = self._outstanding.pop(aid)
            self._progress_log_buckets.pop(aid, None)
            self._timing_out_ids.discard(aid)
            self._log_clear(controller, act, ts, clear_reason='clear_for_action')
            self._schedule_watchdog_if_needed()
            return
        if self._legacy_pending is not None:
            legacy_action, ts = self._legacy_pending
            if legacy_action is action:
                self._legacy_pending = None
                self._progress_log_buckets.pop('legacy', None)
                self._log_clear(
                    controller, legacy_action, ts, clear_reason='clear_for_action'
                )
                self._schedule_watchdog_if_needed()

    def get_primary(self) -> Action | None:
        """Return the latest outstanding action without progress side effects."""
        self._purge_timeouts()
        primary = self._primary_entry()
        return primary[0] if primary else None

    def clear_all(self) -> None:
        """Clear every outstanding pending row (shutdown / hard reset)."""
        self.set(None)

    def clear_primary(self) -> None:
        """Clear only the latest outstanding row (step-liveness / single-action recovery)."""
        controller = self._context.get_controller()
        with self._lock:
            if self._outstanding:
                try:
                    best_id = max(self._outstanding.keys())
                except ValueError:
                    best_id = None
                if best_id is not None:
                    act, ts = self._outstanding.pop(best_id)
                    self._progress_log_buckets.pop(best_id, None)
                    self._timing_out_ids.discard(best_id)
                    self._log_clear(controller, act, ts, clear_reason='clear_primary')
                    self._schedule_watchdog_if_needed()
                    return
            if self._legacy_pending is not None:
                act, ts = self._legacy_pending
                self._legacy_pending = None
                self._progress_log_buckets.pop('legacy', None)
                self._log_clear(controller, act, ts, clear_reason='clear_primary')
                self._schedule_watchdog_if_needed()

    def has_outstanding(self) -> bool:
        """Return True when any action is still awaiting its observation."""
        self._purge_timeouts()
        with self._lock:
            return bool(self._outstanding) or self._legacy_pending is not None

    def _primary_entry(self) -> tuple[Action, float] | None:
        """Latest / highest-id outstanding row (for step guards and logging)."""
        with self._lock:
            if not self._outstanding:
                return self._legacy_pending
            try:
                active_ids = [
                    aid for aid in self._outstanding if aid not in self._timing_out_ids
                ]
                if not active_ids:
                    return self._legacy_pending
                best_id = max(active_ids)
                return self._outstanding[best_id]
            except (ValueError, KeyError):
                return self._legacy_pending

    def _purge_timeouts(self) -> None:
        """Remove timed-out actions; defer observation emission to async path."""
        now = time.time()
        dead: list[tuple[Action, float]] = []
        with self._lock:
            for aid, (action, ts) in list(self._outstanding.items()):
                elapsed = now - ts
                limit = self._effective_timeout_seconds(self._timeout, action)
                if math.isfinite(limit) and elapsed > limit:
                    if aid in self._timing_out_ids:
                        continue
                    self._timing_out_ids.add(aid)
                    dead.append((action, elapsed))

            if self._legacy_pending is not None:
                action, ts = self._legacy_pending
                elapsed = now - ts
                limit = self._effective_timeout_seconds(self._timeout, action)
                if math.isfinite(limit) and elapsed > limit:
                    legacy_id = self._int_action_id(action)
                    if legacy_id is None or legacy_id not in self._timing_out_ids:
                        if legacy_id is not None:
                            self._timing_out_ids.add(legacy_id)
                        dead.append((action, elapsed))

        # Defer observation emission to async path to avoid recursive
        # event delivery when called from the sync step loop.
        if dead:
            self._defer_timeout_observations(dead)

    def _defer_timeout_observations(
        self, timed_out: list[tuple[Action, float]]
    ) -> None:
        """Emit timeout observations synchronously to avoid test isolation issues.

        The original design used run_or_schedule to defer emission to the async
        context, but this causes test failures where the task doesn't complete
        before the test's event loop closes. Running synchronously ensures
        observations are emitted before get() returns.
        """
        controller = self._context.get_controller()
        for action, elapsed in timed_out:
            self._emit_timeout_observation(controller, action, elapsed)

    def _emit_timeout_observation(
        self, controller, action: Action, elapsed: float
    ) -> None:
        """Actually emit the timeout ErrorObservation (async context)."""
        action_id = getattr(action, 'id', 'unknown')
        action_type = type(action).__name__

        _SUBPROCESS_ACTION_TYPES = frozenset({
            'CmdRunAction',
            'TerminalRunAction',
            'TerminalInputAction',
            'DebuggerAction',
        })
        if action_type in _SUBPROCESS_ACTION_TYPES:
            try:
                self._context.kill_running_command()
            except Exception:
                pass
        if action_type in {
            'TerminalRunAction',
            'TerminalInputAction',
            'TerminalReadAction',
        }:
            try:
                self._context.close_hung_terminal_sessions()
            except Exception:
                pass

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
            timeout_kind='pending_action',
        )
        attach_observation_cause(
            timeout_obs, action, context='pending_action_service.timeout'
        )
        try:
            from backend.orchestration.file_edit_transaction import (
                get_file_edit_transaction_coordinator,
            )

            timeout_obs = get_file_edit_transaction_coordinator(
                controller
            ).after_observation(action, timeout_obs)
        except Exception:
            controller.log(
                'warning',
                'File edit transaction timeout handling failed; continuing.',
                extra={'msg_type': 'FILE_EDIT_TRANSACTION_TIMEOUT_FAILED'},
            )
        try:
            self.clear_for_action(action)
            controller.event_stream.add_event(timeout_obs, EventSource.ENVIRONMENT)
        finally:
            aid = self._int_action_id(action)
            if aid is not None:
                self._timing_out_ids.discard(aid)

    def get(self) -> Action | None:
        self._purge_timeouts()
        primary = self._primary_entry()
        if primary is None:
            return None
        action, timestamp = primary
        controller = self._context.get_controller()
        elapsed = time.time() - timestamp
        limit = self._effective_timeout_seconds(self._timeout, action)

        self._log_progress_update(controller, action, elapsed, limit)
        return action

    def info(self) -> tuple[Action, float] | None:
        self._purge_timeouts()
        return self._primary_entry()

    def shutdown(self) -> None:
        """Cancel watchdog and clear pending state during controller shutdown."""
        self._cancel_watchdog()
        self._outstanding.clear()
        self._legacy_pending = None
        self._progress_log_buckets.clear()

    def _log_progress_update(
        self, controller, action: Action, elapsed: float, limit: float
    ) -> None:
        """Emit at most one progress log per 30s bucket for long-running actions."""
        if not math.isfinite(limit) or elapsed < 60.0:
            return

        bucket = int(elapsed // 30)
        if bucket < 2:
            return

        action_id = self._int_action_id(action)
        progress_key: int | str = action_id if action_id is not None else 'legacy'
        if self._progress_log_buckets.get(progress_key) == bucket:
            return

        self._progress_log_buckets[progress_key] = bucket
        controller.log(
            'info',
            f'Pending action still running for {elapsed:.1f}s '
            f'(timeout {limit:.1f}s): {type(action).__name__} '
            f'(id={getattr(action, "id", "unknown")})',
            extra={'msg_type': 'PENDING_ACTION_STILL_RUNNING'},
        )

    def _outstanding_count(self) -> int:
        count = len(self._outstanding)
        if self._legacy_pending is not None:
            count += 1
        return count

    def _log_clear(
        self,
        controller,
        prev_action: Action,
        timestamp: float,
        *,
        clear_reason: str = 'unknown',
    ) -> None:
        action_id = getattr(prev_action, 'id', 'unknown')
        action_type = type(prev_action).__name__
        elapsed = time.time() - timestamp
        controller.log(
            'debug',
            f'Cleared pending action after {elapsed:.2f}s: {action_type} (id={action_id})',
            extra={
                'msg_type': 'PENDING_ACTION_CLEARED',
                'pending_action_id': action_id,
                'clear_reason': clear_reason,
                'outstanding_count': self._outstanding_count(),
            },
        )

    def _handle_timeout(self, controller, action: Action, elapsed: float) -> None:
        """Called by watchdog timer — defer observation to async path."""
        self._cancel_watchdog()
        self._defer_timeout_observations([(action, elapsed)])

    def _schedule_watchdog_if_needed(self) -> None:
        """Schedule the next watchdog using the soonest finite timeout among rows."""
        self._cancel_watchdog()
        delays: list[float] = []
        for action, _ts in self._outstanding.values():
            eff = self._effective_timeout_seconds(self._timeout, action)
            if math.isfinite(eff):
                delays.append(eff + 2.0)
        if self._legacy_pending is not None:
            eff = self._effective_timeout_seconds(
                self._timeout, self._legacy_pending[0]
            )
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
        """Trigger a step if any pending action is still active.

        First purges timed-out actions (emits ErrorObservation and clears
        internal state) so the agent is no longer blocked on a stuck pending
        action. Only triggers a step if anything is still pending after the
        purge — otherwise the purge itself is the recovery and a step is
        unnecessary.
        """
        self._watchdog_handle = None
        if not self._outstanding and self._legacy_pending is None:
            return
        self._purge_timeouts()
        if not self._outstanding and self._legacy_pending is None:
            logger.warning(
                'Pending action watchdog fired; purged timed-out actions. '
                'No further step trigger needed.'
            )
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
