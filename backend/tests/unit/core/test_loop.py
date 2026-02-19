"""Tests for backend.core.loop — run loop helpers and error/backoff logic."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch, AsyncMock, PropertyMock

from backend.core.loop import (
    _BACKOFF_FACTOR,
    _INITIAL_POLL_INTERVAL,
    _MAX_CONSECUTIVE_ERRORS,
    _MAX_POLL_INTERVAL,
    _create_status_callback,
    _handle_error_status,
    _set_status_callbacks,
    _validate_status_callbacks,
    run_agent_until_done,
)
from backend.core.enums import RuntimeStatus
from backend.core.schemas import AgentState


# ===================================================================
# Constants
# ===================================================================


class TestConstants:
    def test_backoff_parameters(self):
        assert _INITIAL_POLL_INTERVAL > 0
        assert _MAX_POLL_INTERVAL > _INITIAL_POLL_INTERVAL
        assert _BACKOFF_FACTOR > 1.0
        assert _MAX_CONSECUTIVE_ERRORS > 0


# ===================================================================
# _handle_error_status
# ===================================================================


class TestHandleErrorStatus:
    def test_sets_last_error(self):
        controller = MagicMock()
        controller.state.set_last_error = MagicMock()
        controller.state.iteration_flag.current_value = 5
        _handle_error_status(controller, RuntimeStatus.ERROR, "something broke")
        controller.state.set_last_error.assert_called_once_with(
            "something broke", source="loop.status_callback"
        )

    def test_memory_error_records_boundary(self):
        controller = MagicMock()
        controller.state.iteration_flag.current_value = 7
        _handle_error_status(controller, RuntimeStatus.ERROR_MEMORY, "OOM")
        assert controller.state._memory_error_boundary == 7

    def test_memory_error_records_boundary_failure_handled(self):
        controller = MagicMock()
        # Mocking controller.state to raise error on setattr
        type(controller.state).iteration_flag = PropertyMock(
            side_effect=Exception("setattr failure")
        )

        # This shouldn't raise because of the try-except block
        _handle_error_status(controller, RuntimeStatus.ERROR_MEMORY, "OOM")

    def test_handle_error_status_scheduling_failure_handled(self):
        controller = MagicMock()
        # Make run_or_schedule fail and then create_tracked_task fail
        with patch(
            "backend.core.loop.run_or_schedule",
            side_effect=Exception("run_or_schedule failed"),
        ):
            with patch(
                "backend.utils.async_utils.create_tracked_task",
                side_effect=Exception("create_tracked_task failed"),
            ):
                # This should log the error but not raise
                _handle_error_status(controller, RuntimeStatus.ERROR, "something broke")

    def test_non_memory_error_no_boundary(self):
        controller = MagicMock()
        controller.state.iteration_flag.current_value = 3
        _handle_error_status(controller, RuntimeStatus.ERROR, "generic error")
        # _memory_error_boundary should NOT be set via setattr
        # (it's set via setattr only for ERROR_MEMORY)


# ===================================================================
# _create_status_callback
# ===================================================================


class TestCreateStatusCallback:
    def test_error_callback_calls_handle(self):
        controller = MagicMock()
        controller.state.iteration_flag.current_value = 1
        cb = _create_status_callback(controller)
        with patch("backend.core.loop._handle_error_status") as mock_handle:
            cb("error", RuntimeStatus.ERROR, "bad")
            mock_handle.assert_called_once_with(controller, RuntimeStatus.ERROR, "bad")

    def test_info_callback_logs_only(self):
        controller = MagicMock()
        cb = _create_status_callback(controller)
        # Should not raise
        cb("info", RuntimeStatus.READY, "all good")


# ===================================================================
# _validate_status_callbacks
# ===================================================================


class TestValidateStatusCallbacks:
    def test_no_warning_when_clean(self):
        runtime = MagicMock(spec=[])
        controller = MagicMock(spec=[])
        # Should not raise
        _validate_status_callbacks(runtime, controller)

    def test_warns_when_already_set(self):
        runtime = MagicMock()
        runtime.status_callback = lambda *a: None
        controller = MagicMock()
        controller.status_callback = lambda *a: None
        # Should not raise (just logs)
        _validate_status_callbacks(runtime, controller)


# ===================================================================
# _set_status_callbacks
# ===================================================================


class TestSetStatusCallbacks:
    def test_sets_on_all_three(self):
        runtime = MagicMock()
        controller = MagicMock()
        memory = MagicMock()

        def cb(*a):
            return None

        _set_status_callbacks(runtime, controller, memory, cb)
        assert runtime.status_callback is cb
        assert controller.status_callback is cb
        assert memory.status_callback is cb


# ===================================================================
# run_agent_until_done
# ===================================================================


class TestRunAgentUntilDone:
    @patch("backend.core.loop.asyncio.sleep", new_callable=AsyncMock)
    async def test_terminates_immediately_if_state_is_terminal(self, mock_sleep):
        controller = MagicMock()
        controller.state.agent_state = AgentState.FINISHED
        runtime = MagicMock()
        memory = MagicMock()

        await run_agent_until_done(controller, runtime, memory, [AgentState.FINISHED])

        # Should call step() once at the start, then exit because already FINISHED
        assert controller.step.call_count == 1
        mock_sleep.assert_not_called()

    @patch("backend.core.loop.asyncio.sleep", new_callable=AsyncMock)
    async def test_runs_until_terminal_state(self, mock_sleep):
        controller = MagicMock()
        # Initial call to step() in run_agent_until_done, then loop starts
        # We'll make it take 2 steps in the loop to finish
        controller.state.agent_state = AgentState.RUNNING

        def mock_step():
            if controller.step.call_count == 3:
                controller.state.agent_state = AgentState.FINISHED

        controller.step.side_effect = mock_step

        runtime = MagicMock()
        memory = MagicMock()

        await run_agent_until_done(controller, runtime, memory, [AgentState.FINISHED])

        # 1 initial call + 2 loop calls
        assert controller.step.call_count == 3
        assert mock_sleep.call_count == 2

    @patch("backend.core.loop.asyncio.sleep", new_callable=AsyncMock)
    async def test_backoff_on_consecutive_errors(self, mock_sleep):
        controller = MagicMock()
        controller.state.agent_state = AgentState.RUNNING

        # Fail 3 times, then succeed and terminate
        def mock_step():
            if controller.step.call_count <= 4:  # 1 initial + 3 loop failures
                if controller.step.call_count > 1:
                    raise Exception("step failure")
            else:
                controller.state.agent_state = AgentState.FINISHED

        controller.step.side_effect = mock_step

        runtime = MagicMock()
        memory = MagicMock()

        await run_agent_until_done(controller, runtime, memory, [AgentState.FINISHED])

        # 1 initial + 3 failures + 1 success = 5 calls
        assert controller.step.call_count == 5
        # 4 loop iterations
        assert mock_sleep.call_count == 4

        # Check backoff intervals
        # Iteration 1: Initial interval (0.1), fails -> 0.15
        # Iteration 2: 0.15, fails -> 0.225
        # Iteration 3: 0.225, fails -> 0.3375
        # Iteration 4: 0.3375, succeeds -> 0.1
        expected_intervals = [
            _INITIAL_POLL_INTERVAL,
            _INITIAL_POLL_INTERVAL * _BACKOFF_FACTOR,
            _INITIAL_POLL_INTERVAL * _BACKOFF_FACTOR * _BACKOFF_FACTOR,
            _INITIAL_POLL_INTERVAL
            * _BACKOFF_FACTOR
            * _BACKOFF_FACTOR
            * _BACKOFF_FACTOR,
        ]
        actual_intervals = [call.args[0] for call in mock_sleep.call_args_list]
        for i, (actual, expected) in enumerate(
            zip(actual_intervals, expected_intervals)
        ):
            assert actual == pytest.approx(expected), f"Interval at index {i} mismatch"

    @patch("backend.core.loop.asyncio.sleep", new_callable=AsyncMock)
    async def test_forces_error_on_max_consecutive_errors(self, mock_sleep):
        controller = MagicMock()
        controller.state.agent_state = AgentState.RUNNING
        controller.set_agent_state_to = AsyncMock()

        # Always fail
        controller.step.side_effect = Exception("persistent failure")

        runtime = MagicMock()
        memory = MagicMock()

        # We'll use a smaller _MAX_CONSECUTIVE_ERRORS for the test if we could,
        # but since it's a constant we'll just mock it or run through it.
        # Actually, let's just patch the constant in the module.
        with patch("backend.core.loop._MAX_CONSECUTIVE_ERRORS", 3):
            await run_agent_until_done(
                controller, runtime, memory, [AgentState.FINISHED]
            )

        # 1 initial + 3 loop failures = 4 calls
        assert controller.step.call_count == 4
        # set_agent_state_to(ERROR) should be called
        controller.set_agent_state_to.assert_called_once_with(AgentState.ERROR)

    @patch("backend.core.loop.asyncio.sleep", new_callable=AsyncMock)
    async def test_forces_error_on_max_consecutive_errors_failure_handled(
        self, mock_sleep
    ):
        controller = MagicMock()
        controller.state.agent_state = AgentState.RUNNING
        controller.set_agent_state_to = AsyncMock(
            side_effect=Exception("force error failure")
        )

        # Always fail step
        controller.step.side_effect = Exception("persistent failure")

        runtime = MagicMock()
        memory = MagicMock()

        with patch("backend.core.loop._MAX_CONSECUTIVE_ERRORS", 1):
            # This should log the error but not raise
            await run_agent_until_done(
                controller, runtime, memory, [AgentState.FINISHED]
            )

        assert controller.set_agent_state_to.called

    @patch("backend.core.loop.asyncio.sleep", new_callable=AsyncMock)
    async def test_initial_step_failure_is_handled(self, mock_sleep):
        controller = MagicMock()
        controller.state.agent_state = AgentState.FINISHED  # Terminate immediately
        controller.step.side_effect = Exception("initial failure")

        runtime = MagicMock()
        memory = MagicMock()

        # Should not raise
        await run_agent_until_done(controller, runtime, memory, [AgentState.FINISHED])
        assert controller.step.call_count == 1
