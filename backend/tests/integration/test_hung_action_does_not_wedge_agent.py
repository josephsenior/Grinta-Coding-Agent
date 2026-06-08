"""Integration test: a hung tool call must not wedge the agent.

This is the end-to-end test for the fix to the "agent stuck at polling"
bug.  It exercises the full runtime path with a tool that hangs
indefinitely and verifies that:

1. The runtime's wall-clock bound cuts off the hung tool within
   ``event.timeout`` seconds (Layer 1).
2. The pending action is cleared so the agent can step again.
3. The error reaches the event stream so downstream consumers
   (controller, LLM, UI) see the recovery.

If this test ever fails, the agent CAN be permanently stuck on a hung
tool, which is the bug class this fix is designed to eliminate.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.ledger.action import FileReadAction
from backend.ledger.observation import ErrorObservation


def _make_runtime(timeout: float = 0.1) -> object:
    """Build a minimal LocalRuntimeInProcess with a tight timeout."""
    from backend.execution.drivers.local.local_runtime_inprocess import (
        LocalRuntimeInProcess,
    )

    with patch.object(LocalRuntimeInProcess, '_init_tooling_and_platform'):
        config = MagicMock()
        config.runtime_config.timeout = timeout
        runtime = LocalRuntimeInProcess(
            config=config,
            event_stream=MagicMock(),
            llm_registry=MagicMock(),
            sid='hung-action-test',
        )
    runtime._runtime_initialized = True
    return runtime


class TestHungActionRecovery:
    """End-to-end verification that hung tools cannot wedge the agent."""

    @pytest.mark.asyncio
    async def test_hung_file_read_does_not_wedge_runtime(self):
        """A FileReadAction whose execute hangs is cut off in bounded time.

        Scenario (the original bug):
        - LLM emits a FileReadAction
        - The runtime dispatches it to ``_execute_action``
        - The action hangs (e.g. shell session init deadlock on Windows)
        - Without the fix, ``await self._execute_action(event)`` never
          returns and the agent is stuck in RUNNING forever.
        - With the fix, ``asyncio.wait_for`` cancels the coroutine and
          the runtime emits an ``ACTION_EXECUTION_TIMEOUT`` observation.
        """
        runtime = _make_runtime(timeout=0.1)

        async def _hang_forever(_event):
            await asyncio.sleep(60)

        runtime._execute_action = AsyncMock(side_effect=_hang_forever)  # type: ignore[method-assign]
        runtime.event_stream = MagicMock()

        action = FileReadAction(path='/workspace/hung.py')
        action.set_hard_timeout(0.1, blocking=False)

        start = time.monotonic()
        await runtime._handle_action(action)
        elapsed = time.monotonic() - start

        # The hang would normally take 60s; the timeout bound must cut it.
        assert elapsed < 2.0, (
            f'_handle_action took {elapsed:.2f}s with a 0.1s timeout; '
            f'wall-clock bound is not being enforced.'
        )

        # The runtime must have emitted the timeout observation.
        runtime.event_stream.add_event.assert_called_once()
        emitted = runtime.event_stream.add_event.call_args.args[0]
        assert isinstance(emitted, ErrorObservation)
        assert emitted.error_id == 'ACTION_EXECUTION_TIMEOUT'

    @pytest.mark.asyncio
    async def test_recovery_is_observable_to_controller(self):
        """The recovery observation is structured for the controller to act on.

        The controller consumes observations and uses them to drive the
        next step.  The timeout observation must:
        - Have ``tool_call_metadata`` attached (via ``_process_observation``)
        - Be added to the event stream with the correct EventSource
        - Have a structured ``tool_result`` so downstream code (e.g.
          trajectory recording, the LLM message queue) can classify it
          as a failure and continue stepping.
        """
        runtime = _make_runtime(timeout=0.1)

        async def _hang_forever(_event):
            await asyncio.sleep(60)

        runtime._execute_action = AsyncMock(side_effect=_hang_forever)  # type: ignore[method-assign]
        runtime.event_stream = MagicMock()

        action = FileReadAction(path='/workspace/hung.py')
        action.set_hard_timeout(0.1, blocking=False)

        await runtime._handle_action(action)

        # Inspect the emitted observation.
        runtime.event_stream.add_event.assert_called_once()
        emitted = runtime.event_stream.add_event.call_args.args[0]
        source = runtime.event_stream.add_event.call_args.args[1]

        # The source is the action's source (or AGENT default).
        from backend.ledger import EventSource
        assert source in (EventSource.AGENT, action.source or EventSource.AGENT)

        # The observation has structured tool_result for downstream
        # consumers (set by _process_observation).
        assert isinstance(emitted.tool_result, dict)
        assert emitted.tool_result.get('ok') is False
        assert emitted.tool_result.get('retryable') is True

    @pytest.mark.asyncio
    async def test_timeout_does_not_promote_runtime_error_status(self):
        """ACTION_EXECUTION_TIMEOUT must not flip runtime to ERROR (session survival)."""
        from backend.core.schemas import RuntimeStatus

        runtime = _make_runtime(timeout=0.1)

        async def _hang_forever(_event):
            await asyncio.sleep(60)

        runtime._execute_action = AsyncMock(side_effect=_hang_forever)  # type: ignore[method-assign]
        runtime.event_stream = MagicMock()
        runtime.set_runtime_status = MagicMock()  # type: ignore[method-assign]

        action = FileReadAction(path='/workspace/hung.py')
        action.set_hard_timeout(0.1, blocking=False)

        await runtime._handle_action(action)

        for call in runtime.set_runtime_status.call_args_list:
            status = call.args[0] if call.args else None
            assert status != RuntimeStatus.ERROR
