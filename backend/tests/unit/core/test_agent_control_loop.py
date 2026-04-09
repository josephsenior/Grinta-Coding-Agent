"""Tests for backend.core.bootstrap.agent_control_loop."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from backend.core.bootstrap.agent_control_loop import (
    _create_status_callback,
    _handle_error_status,
    _set_status_callbacks,
    _validate_status_callbacks,
    run_agent_until_done,
)
from backend.core.enums import RuntimeStatus
from backend.core.schemas import AgentState


class TestHandleErrorStatus:
    def test_sets_last_error_and_schedules_error_state(self) -> None:
        controller = MagicMock()
        controller.set_agent_state_to = MagicMock(return_value='error-coro')
        controller.state.iteration_flag.current_value = 5

        with patch(
            'backend.core.bootstrap.agent_control_loop.run_or_schedule'
        ) as mock_run_or_schedule:
            _handle_error_status(controller, RuntimeStatus.ERROR, 'something broke')

        controller.state.set_last_error.assert_called_once_with(
            'something broke', source='loop.status_callback'
        )
        controller.set_agent_state_to.assert_called_once_with(AgentState.ERROR)
        mock_run_or_schedule.assert_called_once_with('error-coro')

    def test_memory_error_records_boundary(self) -> None:
        controller = MagicMock()
        controller.set_agent_state_to = MagicMock(return_value='error-coro')
        controller.state.iteration_flag.current_value = 7

        with patch('backend.core.bootstrap.agent_control_loop.run_or_schedule'):
            _handle_error_status(controller, RuntimeStatus.ERROR_MEMORY, 'OOM')

        assert controller.state._memory_error_boundary == 7

    def test_falls_back_to_tracked_task_when_schedule_fails(self) -> None:
        controller = MagicMock()
        controller.set_agent_state_to = MagicMock(return_value='error-coro')

        with patch(
            'backend.core.bootstrap.agent_control_loop.run_or_schedule',
            side_effect=Exception('run_or_schedule failed'),
        ):
            with patch(
                'backend.utils.async_utils.create_tracked_task'
            ) as mock_create_task:
                _handle_error_status(controller, RuntimeStatus.ERROR, 'something broke')

        mock_create_task.assert_called_once_with(
            'error-coro',
            name='error-state-fallback',
        )

    def test_swallows_failures_when_all_error_transitions_fail(self) -> None:
        controller = MagicMock()
        controller.set_agent_state_to = MagicMock(return_value='error-coro')

        with patch(
            'backend.core.bootstrap.agent_control_loop.run_or_schedule',
            side_effect=Exception('run_or_schedule failed'),
        ):
            with patch(
                'backend.utils.async_utils.create_tracked_task',
                side_effect=Exception('create_tracked_task failed'),
            ):
                _handle_error_status(controller, RuntimeStatus.ERROR, 'something broke')


class TestCreateStatusCallback:
    def test_error_callback_routes_to_handle_error_status(self) -> None:
        controller = MagicMock()
        callback = _create_status_callback(controller)

        with patch(
            'backend.core.bootstrap.agent_control_loop._handle_error_status'
        ) as mock_handle:
            callback('error', RuntimeStatus.ERROR, 'bad')

        mock_handle.assert_called_once_with(controller, RuntimeStatus.ERROR, 'bad')

    def test_info_callback_does_not_route_to_error_handler(self) -> None:
        controller = MagicMock()
        callback = _create_status_callback(controller)

        with patch(
            'backend.core.bootstrap.agent_control_loop._handle_error_status'
        ) as mock_handle:
            callback('info', RuntimeStatus.READY, 'all good')

        mock_handle.assert_not_called()


class TestValidateStatusCallbacks:
    def test_no_warning_when_callbacks_are_unset(self) -> None:
        runtime = MagicMock(spec=[])
        controller = MagicMock(spec=[])

        with patch('backend.core.bootstrap.agent_control_loop.logger.warning') as warning:
            _validate_status_callbacks(runtime, controller)

        warning.assert_not_called()

    def test_warns_when_callbacks_are_already_set(self) -> None:
        runtime = MagicMock()
        runtime.status_callback = lambda *args: None
        controller = MagicMock()
        controller.status_callback = lambda *args: None

        with patch('backend.core.bootstrap.agent_control_loop.logger.warning') as warning:
            _validate_status_callbacks(runtime, controller)

        assert warning.call_count == 2


class TestSetStatusCallbacks:
    def test_sets_runtime_controller_and_memory_callbacks(self) -> None:
        runtime = MagicMock()
        controller = MagicMock()
        memory = MagicMock()

        def callback(*_args):
            return None

        _set_status_callbacks(runtime, controller, memory, callback)

        assert runtime.status_callback is callback
        assert controller.status_callback is callback
        assert memory.status_callback is callback


class TestRunAgentUntilDone:
    @patch(
        'backend.core.bootstrap.agent_control_loop.asyncio.sleep',
        new_callable=AsyncMock,
    )
    async def test_sets_callbacks_and_exits_when_already_terminal(self, mock_sleep) -> None:
        controller = MagicMock()
        controller.state.agent_state = AgentState.FINISHED
        runtime = MagicMock()
        memory = MagicMock()

        await run_agent_until_done(controller, runtime, memory, [AgentState.FINISHED])

        assert callable(runtime.status_callback)
        assert runtime.status_callback is controller.status_callback
        assert controller.status_callback is memory.status_callback
        controller.step.assert_called_once_with()
        mock_sleep.assert_not_awaited()

    @patch(
        'backend.core.bootstrap.agent_control_loop.asyncio.sleep',
        new_callable=AsyncMock,
    )
    async def test_waits_for_event_driven_state_changes(self, mock_sleep) -> None:
        controller = MagicMock()
        controller.state.agent_state = AgentState.RUNNING
        runtime = MagicMock()
        memory = MagicMock()

        sleep_count = 0

        async def finish_after_two_polls(_interval: float) -> None:
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count == 2:
                controller.state.agent_state = AgentState.FINISHED

        mock_sleep.side_effect = finish_after_two_polls

        await run_agent_until_done(controller, runtime, memory, [AgentState.FINISHED])

        controller.step.assert_called_once_with()
        assert mock_sleep.await_count == 2

    @patch(
        'backend.core.bootstrap.agent_control_loop.asyncio.sleep',
        new_callable=AsyncMock,
    )
    async def test_initial_step_failure_is_logged_but_not_raised(self, mock_sleep) -> None:
        controller = MagicMock()
        controller.state.agent_state = AgentState.RUNNING
        controller.step.side_effect = Exception('initial failure')
        runtime = MagicMock()
        memory = MagicMock()

        async def finish_after_first_poll(_interval: float) -> None:
            controller.state.agent_state = AgentState.FINISHED

        mock_sleep.side_effect = finish_after_first_poll

        await run_agent_until_done(controller, runtime, memory, [AgentState.FINISHED])

        controller.step.assert_called_once_with()
        mock_sleep.assert_awaited_once()
