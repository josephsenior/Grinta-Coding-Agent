"""_SessionOrchestratorWatchdogMixin mixin for SessionOrchestrator.

Provides the independent watchdog timer for stall detection.
"""

from __future__ import annotations

import asyncio
import logging
import time

from backend.core.schemas import AgentState
from backend.utils.async_utils import (
    create_tracked_task,
    get_main_event_loop,
)

logger = logging.getLogger(__name__)


class _SessionOrchestratorWatchdogMixin:
    """Mixin for SessionOrchestrator watchdog functionality."""

    _watchdog_task: asyncio.Task[None] | None = None
    _watchdog_last_step_ts: float = 0.0
    _watchdog_auto_recover_ts: float = 0.0
    _watchdog_timeout: float | None = None

    def _start_watchdog(self) -> None:
        """Start the independent watchdog background task.

        The watchdog runs on the main event loop and periodically checks
        whether ``step()`` has been called recently.  If the agent is in
        RUNNING state but no step has occurred within the configured timeout,
        the watchdog issues ``schedule_step_soon()`` to recover.

        This is a safety net for the case where the step loop stops running
        entirely (e.g. due to an unhandled exception in ``_on_event``).
        The existing watchdog inside ``_step_inner`` cannot detect this case
        because it only runs when ``_step_inner`` runs.
        """
        if self._watchdog_task is not None and not self._watchdog_task.done():
            return

        self._watchdog_last_step_ts = time.monotonic()
        loop: asyncio.AbstractEventLoop | None
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = get_main_event_loop()
        if loop is None or not loop.is_running():
            return

        self._watchdog_task = create_tracked_task(
            self._watchdog_loop(),
            name='agent-watchdog',
        )

    def _stop_watchdog(self) -> None:
        """Cancel the watchdog background task."""
        task = getattr(self, '_watchdog_task', None)
        if task is not None and not task.done():
            task.cancel()
        self._watchdog_task = None

    def _is_llm_stream_active(self) -> bool:
        """Return True while the active executor is consuming an LLM stream."""
        executor = getattr(getattr(self, 'agent', None), 'executor', None)
        if executor is None:
            return False

        stream_task = getattr(executor, '_active_stream_task', None)
        if stream_task is not None:
            done = getattr(stream_task, 'done', None)
            if not callable(done):
                return True
            try:
                if not done():
                    return True
            except Exception:
                return True

        return getattr(executor, '_active_stream_iter', None) is not None

    async def _watchdog_loop(self) -> None:
        """Background loop that checks for step() progress at regular intervals."""
        from backend.core.constants import (
            DEFAULT_NO_STEP_PROGRESS_TIMEOUT_SECONDS,
            DEFAULT_STUCK_AUTO_RECOVER_COOLDOWN_SECONDS,
        )

        check_interval = 10.0
        cb_config = getattr(
            getattr(self.services.circuit_breaker, 'circuit_breaker', None),
            'config',
            None,
        )
        watchdog_timeout = getattr(self, '_watchdog_timeout', None)
        if isinstance(watchdog_timeout, (int, float)):
            timeout = float(watchdog_timeout)
        else:
            timeout = float(
                getattr(
                    cb_config,
                    'no_step_progress_timeout_seconds',
                    DEFAULT_NO_STEP_PROGRESS_TIMEOUT_SECONDS,
                )
            )
        if timeout <= 0:
            return
        cooldown = float(
            getattr(
                cb_config,
                'auto_recover_cooldown_seconds',
                DEFAULT_STUCK_AUTO_RECOVER_COOLDOWN_SECONDS,
            )
        )
        auto_recover_attempted = False
        auto_recover_ts = 0.0

        try:
            while not self._closed:
                await asyncio.sleep(check_interval)
                state = self.get_agent_state()
                if state != AgentState.RUNNING:
                    self._watchdog_last_step_ts = time.monotonic()
                    auto_recover_attempted = False
                    continue

                if self._is_llm_stream_active():
                    self._watchdog_last_step_ts = time.monotonic()
                    auto_recover_attempted = False
                    logger.debug(
                        'INDEPENDENT WATCHDOG: suppressed no-step recovery; '
                        'LLM stream is active'
                    )
                    continue

                elapsed = time.monotonic() - self._watchdog_last_step_ts
                if elapsed < timeout:
                    continue

                now = time.monotonic()
                if not auto_recover_attempted or (now - auto_recover_ts) > cooldown:
                    logger.warning(
                        'INDEPENDENT WATCHDOG: no step() call for %.1fs in RUNNING; '
                        'issuing schedule_step_soon() to recover',
                        elapsed,
                    )
                    self._watchdog_last_step_ts = now
                    auto_recover_attempted = True
                    auto_recover_ts = now
                    try:
                        self.schedule_step_soon()
                    except Exception:
                        pass
                else:
                    logger.error(
                        'INDEPENDENT WATCHDOG: auto-recover did not help after %.1fs; '
                        'forcing ERROR state to break the stall',
                        elapsed,
                    )
                    try:
                        await self.set_agent_state_to(AgentState.ERROR)
                    except Exception:
                        pass
                    return
        except asyncio.CancelledError:
            return
        except Exception as exc:
            logger.debug('Watchdog loop exited: %s', exc)

    def _record_watchdog_step(self) -> None:
        """Record that step() was called, resetting the watchdog timer."""
        self._watchdog_last_step_ts = time.monotonic()
