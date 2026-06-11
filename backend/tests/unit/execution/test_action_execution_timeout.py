"""Tests for runtime action execution wall-clock timeout (Layer 1).

These tests verify the runtime enforces a hard wall-clock bound on action
execution via ``asyncio.wait_for`` and emits an ``ACTION_EXECUTION_TIMEOUT``
``ErrorObservation`` when the bound is exceeded.  This is the primary fix
that prevents the agent from getting permanently stuck on a hung tool.

The bug class being eliminated: a single hung tool call (e.g. shell
session creation deadlock) could leave the runtime's ``_execute_action``
await pending forever, with no ``FileReadObservation`` ever produced.
The pending action would never be cleared and the agent would appear
stuck in RUNNING state indefinitely.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest

from backend.ledger.action import FileReadAction
from backend.ledger.observation import ErrorObservation


def _make_runtime_with_mocked_execute() -> object:
    """Construct a minimal LocalRuntimeInProcess with ``_execute_action`` patched.

    Returns a runtime instance with a config that yields a 0.1s runtime
    timeout so tests run quickly.  The ``_execute_action`` method is
    replaced with an ``AsyncMock`` that the test sets up to either hang
    or return a real observation.
    """
    from backend.execution.drivers.local.local_runtime_inprocess import (
        LocalRuntimeInProcess,
    )

    with patch.object(LocalRuntimeInProcess, '_init_tooling_and_platform'):
        config = MagicMock()
        config.runtime_config.timeout = 0.1
        runtime = LocalRuntimeInProcess(
            config=config,
            event_stream=MagicMock(),
            llm_registry=MagicMock(),
            sid='test-sid-timeout',
        )
    runtime._runtime_initialized = True
    return runtime


class TestActionExecutionTimeout:
    """Layer 1: ``_handle_action`` must enforce a wall-clock bound."""

    @pytest.mark.asyncio
    async def test_hung_action_emits_action_execution_timeout(self):
        """Hung ``_execute_action`` is cut off and emits timeout observation."""
        from unittest.mock import AsyncMock

        runtime = _make_runtime_with_mocked_execute()

        async def _hang_forever(_event):
            await asyncio.sleep(60)

        runtime._execute_action = AsyncMock(side_effect=_hang_forever)  # type: ignore[method-assign]

        event_stream = MagicMock()
        runtime.event_stream = event_stream

        action = FileReadAction(path='/tmp/example.py')
        start = time.monotonic()
        await runtime._handle_action(action)
        elapsed = time.monotonic() - start

        # Bound must be enforced — must not wait 60s for the hung action.
        assert elapsed < 2.0, (
            f'_handle_action took {elapsed:.2f}s with a 0.1s timeout; '
            f'timeout was not enforced.'
        )

        # An ACTION_EXECUTION_TIMEOUT observation must have been emitted.
        event_stream.add_event.assert_called_once()
        emitted = event_stream.add_event.call_args.args[0]
        assert isinstance(emitted, ErrorObservation)
        assert emitted.error_id == 'ACTION_EXECUTION_TIMEOUT'
        assert emitted.timeout_kind == 'action_execution_timeout'
        assert '0' in emitted.content  # timeout value should be in content

    @pytest.mark.asyncio
    async def test_fast_action_completes_normally(self):
        """Non-hung actions still complete — timeout is a ceiling, not a floor."""
        from unittest.mock import AsyncMock

        from backend.ledger.observation import FileReadObservation

        runtime = _make_runtime_with_mocked_execute()
        normal_obs = FileReadObservation(content='hello world', path='/tmp/example.py')
        runtime._execute_action = AsyncMock(return_value=normal_obs)  # type: ignore[method-assign]

        event_stream = MagicMock()
        runtime.event_stream = event_stream

        action = FileReadAction(path='/tmp/example.py')
        await runtime._handle_action(action)

        # Normal observation was emitted, NOT the timeout.
        event_stream.add_event.assert_called_once()
        emitted = event_stream.add_event.call_args.args[0]
        assert emitted is normal_obs
        assert not isinstance(emitted, ErrorObservation)

    @pytest.mark.asyncio
    async def test_timeout_emits_exactly_one_observation(self):
        """The timeout branch processes and emits exactly one observation.

        Verifies:
        - ``_process_observation`` is called exactly once (no double-processing)
        - ``event_stream.add_event`` is called exactly once (no double-emit)
        - The emitted observation carries the ACTION_EXECUTION_TIMEOUT error_id
        """
        from unittest.mock import AsyncMock

        runtime = _make_runtime_with_mocked_execute()

        async def _hang_forever(_event):
            await asyncio.sleep(60)

        runtime._execute_action = AsyncMock(side_effect=_hang_forever)  # type: ignore[method-assign]

        process_obs_spy = MagicMock(return_value=True)
        runtime._process_observation = process_obs_spy  # type: ignore[method-assign]

        event_stream = MagicMock()
        runtime.event_stream = event_stream

        action = FileReadAction(path='/tmp/example.py')
        await runtime._handle_action(action)

        # Exactly one processing pass and one emit.
        process_obs_spy.assert_called_once()
        event_stream.add_event.assert_called_once()

        # The single emit must be the timeout observation.
        emitted = event_stream.add_event.call_args.args[0]
        assert isinstance(emitted, ErrorObservation)
        assert emitted.error_id == 'ACTION_EXECUTION_TIMEOUT'
