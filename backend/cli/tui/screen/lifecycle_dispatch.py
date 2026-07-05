"""TUI agent dispatch and completion polling (extracted from lifecycle)."""

from __future__ import annotations

import asyncio
import time as _time
from typing import Any

from backend.app.agent_control_loop import run_agent_until_done
from backend.cli.tui.constants import _tui_logger
from backend.core.constants import DEFAULT_TUI_DISPATCH_TIMEOUT_SECONDS
from backend.core.enums import AgentState, EventSource
from backend.core.logging.logger import app_logger as logger
from backend.ledger.action import MessageAction


class ScreenLifecycleDispatchMixin:
    async def _run_agent_loop(self) -> None:
        if self._controller is None:
            _tui_logger.debug('_run_agent_loop: no controller, aborting')
            return
        _tui_logger.debug('_run_agent_loop: ENTER')
        end_states = [
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.STOPPED,
        ]
        try:
            _tui_logger.debug('_run_agent_loop: calling run_agent_until_done')
            await run_agent_until_done(
                self._controller,
                self._runtime_stub,
                self._memory_stub,
                end_states,
            )
            _tui_logger.debug('_run_agent_loop: run_agent_until_done returned')
        except Exception as exc:
            _tui_logger.debug(f'_run_agent_loop: EXCEPTION {type(exc).__name__}: {exc}')
            logger.exception('Agent loop exited with error')
        _tui_logger.debug('_run_agent_loop: EXIT')

    async def _ensure_agent_task(self) -> None:
        if self._controller is None:
            _tui_logger.debug('_ensure_agent_task: no controller, returning')
            return

        state = self._controller.get_agent_state()
        _tui_logger.debug(f'_ensure_agent_task: current state={state}')
        logger.info('TUI _ensure_agent_task: current state=%s', state)
        if state in {
            AgentState.LOADING,
            AgentState.AWAITING_USER_INPUT,
            AgentState.FINISHED,
            AgentState.ERROR,
            AgentState.REJECTED,
            AgentState.STOPPED,
        }:
            _tui_logger.debug(f'_ensure_agent_task: transitioning {state} -> RUNNING')
            logger.info('TUI _ensure_agent_task: transitioning %s -> RUNNING', state)
            await self._controller.set_agent_state_to(AgentState.RUNNING)
        elif state == AgentState.RUNNING:
            _tui_logger.debug('_ensure_agent_task: already RUNNING')
            logger.info('TUI _ensure_agent_task: already RUNNING')

        state_after = self._controller.get_agent_state()
        _tui_logger.debug(f'_ensure_agent_task: state after transition={state_after}')
        logger.info('TUI _ensure_agent_task: state after transition=%s', state_after)

        if self._agent_task is None or self._agent_task.done():
            _tui_logger.debug('_ensure_agent_task: creating new agent task')
            logger.info('TUI _ensure_agent_task: creating new agent task')
            self._agent_task = asyncio.create_task(
                run_agent_until_done(
                    self._controller,
                    self._runtime_stub,
                    self._memory_stub,
                    [
                        AgentState.AWAITING_USER_INPUT,
                        AgentState.FINISHED,
                        AgentState.ERROR,
                        AgentState.STOPPED,
                    ],
                ),
                name='grinta-tui-agent',
            )

            def _on_agent_done(t: asyncio.Task[Any]) -> None:
                if t.cancelled():
                    _tui_logger.debug('_agent_task cancelled')
                    return
                exc = t.exception()
                if exc:
                    _tui_logger.debug(
                        f'_agent_task FAILED: {type(exc).__name__}: {exc}'
                    )
                    logger.exception('TUI _agent_task failed')
                else:
                    _tui_logger.debug('_agent_task completed OK')

            self._agent_task.add_done_callback(_on_agent_done)
        else:
            _tui_logger.debug(
                f'_ensure_agent_task: agent task already running task={self._agent_task}'
            )
            logger.info(
                'TUI _ensure_agent_task: agent task already running (task=%s)',
                self._agent_task,
            )

    async def _poll_wait(self):
        # Keep the poll loop lightweight; renderer drains are event-driven.
        # 250ms sleep balances responsiveness with reduced CPU wakeups (~4/sec).
        await asyncio.sleep(0.25)

    def _get_current_event_count(self) -> int:
        try:
            return self._event_stream.get_latest_event_id()
        except Exception:
            return 0

    def _update_progress_tracking(
        self,
        state,
        current_event_count: int,
        last_event_count: int,
        last_state,
        stale_poll_count: int,
        last_progress_at: float,
    ):
        progress_made = False
        if current_event_count != last_event_count:
            progress_made = True
            stale_poll_count = 0
            last_event_count = current_event_count
        else:
            stale_poll_count += 1

        if state != last_state:
            progress_made = True
            last_state = state

        if progress_made:
            last_progress_at = _time.monotonic()

        return last_event_count, last_state, stale_poll_count, last_progress_at

    def _maybe_log_stale_polls(self, stale_poll_count: int, state):
        STALE_POLL_THRESHOLD = 120
        if (
            stale_poll_count > 0
            and stale_poll_count % STALE_POLL_THRESHOLD == 0
            and state == AgentState.RUNNING
        ):
            _tui_logger.debug(
                '_dispatch_to_agent: %d consecutive polls with no new events '
                'in RUNNING state (LLM may be thinking silently; '
                'no-step-progress watchdog will recover true stalls)',
                stale_poll_count,
            )

    async def _check_stall_timeout(
        self,
        state,
        last_progress_at: float,
        started_at: float,
        loop_count: int,
    ):
        elapsed_since_progress = _time.monotonic() - last_progress_at
        if (
            DEFAULT_TUI_DISPATCH_TIMEOUT_SECONDS > 0
            and elapsed_since_progress > DEFAULT_TUI_DISPATCH_TIMEOUT_SECONDS
        ):
            total_elapsed = _time.monotonic() - started_at
            _tui_logger.error(
                '_dispatch_to_agent: TIMEOUT after %.0fs since last progress '
                '(%.0fs total, poll #%d, state=%s) — forcing ERROR to break stall',
                elapsed_since_progress,
                total_elapsed,
                loop_count,
                state,
            )
            logger.error(
                '[TUI] _dispatch_to_agent: STALL TIMEOUT after %.0fs since last progress '
                '(%.0fs total, poll #%d, state=%s). '
                'This usually indicates the _step_pending race condition. '
                'Forcing ERROR state.',
                elapsed_since_progress,
                total_elapsed,
                loop_count,
                state,
                extra={'msg_type': 'TUI_DISPATCH_STALL_TIMEOUT'},
            )
            try:
                await self._controller.set_agent_state_to(AgentState.ERROR)
            except Exception:
                pass
            return AgentState.ERROR, True
        return state, False

    def _maybe_log_periodic_status(self, loop_count: int, state):
        if loop_count == 1 or loop_count % 20 == 0:
            _tui_logger.debug(f'_dispatch_to_agent: poll #{loop_count}, state={state}')
            logger.info(
                '[TUI] _dispatch_to_agent: poll #%d, state=%s',
                loop_count,
                state,
            )

    def _check_completion(self, state, end_states: set[AgentState]) -> bool:
        if state in end_states:
            _tui_logger.debug(f'_dispatch_to_agent: reached end state {state}')
            logger.info('[TUI] _dispatch_to_agent: reached end state %s', state)
            return True
        if self._agent_task and self._agent_task.done():
            _tui_logger.debug(f'_dispatch_to_agent: agent task done, state={state}')
            logger.info('[TUI] _dispatch_to_agent: agent task done, state=%s', state)
            return True
        return False

    async def _poll_for_agent_completion(
        self,
        end_states: set[AgentState],
        started_at: float,
    ) -> AgentState:
        loop_count = 0
        last_progress_at = started_at
        last_event_count = 0
        last_state = None
        stale_poll_count = 0

        while True:
            try:
                await self._poll_wait()
                loop_count += 1
                state = self._controller.get_agent_state()
                current_event_count = self._get_current_event_count()

                last_event_count, last_state, stale_poll_count, last_progress_at = (
                    self._update_progress_tracking(
                        state,
                        current_event_count,
                        last_event_count,
                        last_state,
                        stale_poll_count,
                        last_progress_at,
                    )
                )

                self._maybe_log_stale_polls(stale_poll_count, state)

                state, timed_out = await self._check_stall_timeout(
                    state, last_progress_at, started_at, loop_count
                )
                if timed_out:
                    break

                self._maybe_log_periodic_status(loop_count, state)

                if self._check_completion(state, end_states):
                    break
            except Exception as exc:
                _tui_logger.debug(
                    f'_dispatch_to_agent: poll loop EXCEPTION {type(exc).__name__}: {exc}'
                )
                raise

        return state

    async def _dispatch_action_event(self, action: MessageAction | Any) -> None:
        _tui_logger.debug('_dispatch_action_event: ENTER')
        if self._controller is None or self._event_stream is None:
            _tui_logger.debug(
                '_dispatch_action_event: missing controller or event_stream, returning'
            )
            return

        await self._ensure_environment_ready()

        self._event_stream.add_event(action, EventSource.USER)
        _tui_logger.debug('_dispatch_action_event: event added')
        try:
            logger.info('[TUI] _dispatch_action_event: event added')
        except Exception as exc:
            _tui_logger.debug(
                f'_dispatch_action_event: logger.info FAILED: {type(exc).__name__}: {exc}'
            )
        try:
            await self._ensure_agent_task()
            _tui_logger.debug('_dispatch_action_event: _ensure_agent_task OK')
        except Exception as exc:
            _tui_logger.debug(
                f'_dispatch_action_event: _ensure_agent_task FAILED: {type(exc).__name__}: {exc}'
            )
            raise
        try:
            end_states = {
                AgentState.AWAITING_USER_INPUT,
                AgentState.FINISHED,
                AgentState.ERROR,
                AgentState.STOPPED,
                AgentState.AWAITING_USER_CONFIRMATION,
            }
            _tui_logger.debug('_dispatch_action_event: end_states created')
        except Exception as exc:
            _tui_logger.debug(
                f'_dispatch_action_event: end_states FAILED: {type(exc).__name__}: {exc}'
            )
            raise

        started_at = _time.monotonic()
        while True:
            state = await self._poll_for_agent_completion(end_states, started_at)
            if state == AgentState.AWAITING_USER_CONFIRMATION:
                await self._handle_confirmation_dialog()
                continue
            break

        _tui_logger.debug('_dispatch_action_event: poll loop exited')
        if self._renderer:
            await self._renderer.drain_events_async()

    async def _dispatch_to_agent(
        self, text: str, *, image_urls: list[str] | None = None
    ) -> None:
        _tui_logger.debug('_dispatch_to_agent: ENTER')
        action = MessageAction(
            content=text,
            image_urls=image_urls or None,
        )
        await self._dispatch_action_event(action)
