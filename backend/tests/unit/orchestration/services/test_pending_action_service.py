"""Tests for PendingActionService."""

import time
import unittest
from unittest.mock import MagicMock, patch

from backend.core.constants import BROWSER_TOOL_SYNC_TIMEOUT_SECONDS
from backend.ledger.action.browser_tool import BrowserToolAction
from backend.ledger.action.commands import CmdRunAction
from backend.orchestration.services.pending_action_service import PendingActionService


class TestPendingActionService(unittest.TestCase):
    """Test PendingActionService pending action tracking."""

    def setUp(self):
        """Create mock context for testing."""
        self.mock_controller = MagicMock()
        self.mock_controller.log = MagicMock()
        self.mock_controller.event_stream = MagicMock()

        self.mock_context = MagicMock()
        self.mock_context.get_controller.return_value = self.mock_controller

        # Without a running event loop, _schedule_watchdog falls back to
        # run_until_complete(sleep(timeout+2)) and blocks each test for minutes.
        self._watchdog_patcher = patch.object(
            PendingActionService, '_schedule_watchdog', autospec=True
        )
        self._watchdog_patcher.start()
        self.addCleanup(self._watchdog_patcher.stop)

        self.service = PendingActionService(self.mock_context, timeout=120.0)

    def test_initialization(self):
        """Test service initializes with None pending action."""
        self.assertEqual(self.service._context, self.mock_context)
        self.assertEqual(self.service._timeout, 120.0)
        self.assertIsNone(self.service._legacy_pending)

    def test_set_action(self):
        """Test set() stores action with timestamp."""
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        mock_action.id = 'action-123'

        self.service.set(mock_action)

        self.assertIsNotNone(self.service._legacy_pending)
        assert self.service._legacy_pending is not None
        action, timestamp = self.service._legacy_pending
        self.assertEqual(action, mock_action)
        self.assertIsInstance(timestamp, float)
        self.mock_controller.log.assert_called_once()

    def test_set_none_clears_pending(self):
        """Test set(None) clears pending action."""
        # First set an action
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        mock_action.id = 'action-123'
        self.service.set(mock_action)

        # Then clear it
        self.service.set(None)

        self.assertIsNone(self.service._legacy_pending)
        # Should have logged clearing
        self.assertEqual(self.mock_controller.log.call_count, 2)  # Set + clear

    def test_set_none_clears_get_and_info_views(self):
        """Clearing a pending action must remove all observable pending state."""
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        mock_action.id = 'action-123'

        self.service.set(mock_action)
        self.service.set(None)

        self.assertIsNone(self.service.get())
        self.assertIsNone(self.service.info())

    def test_set_none_when_no_pending(self):
        """Test set(None) when no pending action does nothing."""
        self.service.set(None)

        self.assertIsNone(self.service._legacy_pending)
        self.mock_controller.log.assert_not_called()

    def test_get_returns_action_when_not_timed_out(self):
        """Test get() returns action when within timeout."""
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        mock_action.id = 'action-123'

        self.service.set(mock_action)
        action = self.service.get()

        self.assertEqual(action, mock_action)

    def test_get_returns_none_when_no_pending(self):
        """Test get() returns None when no pending action."""
        action = self.service.get()

        self.assertIsNone(action)

    @patch('time.time')
    def test_get_returns_none_when_timed_out(self, mock_time):
        """Test get() returns None and handles timeout when exceeded."""
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        mock_action.id = 'action-123'

        # Set action at t=0
        mock_time.return_value = 100.0
        self.service.set(mock_action)

        # Get at t=125 (timeout=120)
        mock_time.return_value = 225.1
        action = self.service.get()

        self.assertIsNone(action)
        self.assertEqual(len(self.service._outstanding), 0)
        self.assertIsNone(self.service._legacy_pending)

        # Should have logged timeout
        self.mock_controller.event_stream.add_event.assert_called_once()

    @patch('time.time')
    def test_get_logs_periodic_updates(self, mock_time):
        """Test get() logs periodic updates for long-running actions."""
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        mock_action.id = 'action-123'

        # Set action at t=0
        mock_time.return_value = 100.0
        self.service.set(mock_action)

        # Get at t=90 (should log update)
        mock_time.return_value = 190.0
        action = self.service.get()

        self.assertEqual(action, mock_action)
        # Should have logged both set and periodic update
        log_calls = [call[0][1] for call in self.mock_controller.log.call_args_list]
        self.assertTrue(any('Pending action still running' in msg for msg in log_calls))

    @patch('time.time')
    def test_get_logs_progress_update_once_per_bucket(self, mock_time):
        """Repeated polling in the same 30s bucket should not spam progress logs."""
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        mock_action.id = 'action-123'

        mock_time.return_value = 100.0
        self.service.set(mock_action)

        mock_time.return_value = 190.0
        self.assertEqual(self.service.get(), mock_action)

        mock_time.return_value = 190.8
        self.assertEqual(self.service.get(), mock_action)

        progress_logs = [
            call for call in self.mock_controller.log.call_args_list
            if 'Pending action still running' in call[0][1]
        ]
        self.assertEqual(len(progress_logs), 1)

    def test_info_returns_pending_tuple(self):
        """Test info() returns (action, timestamp) tuple."""
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        mock_action.id = 'action-123'

        self.service.set(mock_action)
        result = self.service.info()

        self.assertIsNotNone(result)
        assert result is not None
        action, timestamp = result
        self.assertEqual(action, mock_action)
        self.assertIsInstance(timestamp, float)

    @patch('time.time')
    def test_info_returns_none_when_pending_has_timed_out(self, mock_time):
        """info() should not expose stale pending state after timeout."""
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        mock_action.id = 'action-123'

        mock_time.return_value = 100.0
        self.service.set(mock_action)

        mock_time.return_value = 225.1
        result = self.service.info()

        self.assertIsNone(result)
        self.assertIsNone(self.service._legacy_pending)
        self.mock_controller.event_stream.add_event.assert_called_once()

    def test_info_returns_none_when_no_pending(self):
        """Test info() returns None when no pending action."""
        result = self.service.info()

        self.assertIsNone(result)

    def test_log_clear(self):
        """Test _log_clear logs action clearing."""
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        mock_action.id = 'action-123'
        timestamp = time.time() - 5.0

        self.service._log_clear(self.mock_controller, mock_action, timestamp)

        self.mock_controller.log.assert_called_once()
        log_args = self.mock_controller.log.call_args[0]
        self.assertIn('Cleared pending action', log_args[1])

    @patch('backend.orchestration.services.pending_action_service.ErrorObservation')
    def test_handle_timeout(self, mock_error_obs):
        """Test _handle_timeout logs and emits timeout error."""
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        mock_action.id = 456

        mock_obs = MagicMock()
        mock_error_obs.return_value = mock_obs

        self.service._handle_timeout(self.mock_controller, mock_action, 125.5)

        # Should log warning
        self.mock_controller.log.assert_called_once()
        log_args = self.mock_controller.log.call_args[0]
        self.assertEqual(log_args[0], 'warning')
        self.assertIn('timed out', log_args[1])

        # Should create ErrorObservation
        mock_error_obs.assert_called_once()
        call_kwargs = mock_error_obs.call_args[1]
        self.assertIn('timed out', call_kwargs['content'])
        self.assertEqual(call_kwargs['error_id'], 'PENDING_ACTION_TIMEOUT')

        # Should set cause to action ID
        self.assertEqual(mock_obs.cause, 456)

        # Should emit event
        self.mock_controller.event_stream.add_event.assert_called_once()

    @patch('backend.orchestration.services.pending_action_service.ErrorObservation')
    def test_handle_timeout_unknown_action_id(self, mock_error_obs):
        """Test _handle_timeout handles unknown action ID."""
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        mock_action.id = 'unknown'

        mock_obs = MagicMock()
        mock_error_obs.return_value = mock_obs

        self.service._handle_timeout(self.mock_controller, mock_action, 125.5)

        # Cause should remain None for invalid IDs
        self.assertIsNone(mock_obs.cause)

    @patch('backend.orchestration.services.pending_action_service.ErrorObservation')
    def test_handle_timeout_non_integer_action_id(self, mock_error_obs):
        """Test _handle_timeout handles non-integer action ID."""
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        mock_action.id = 'not-an-int'

        mock_obs = MagicMock()
        mock_error_obs.return_value = mock_obs

        # Should not raise exception
        self.service._handle_timeout(self.mock_controller, mock_action, 125.5)

        self.assertIsNone(mock_obs.cause)

    @patch('time.time')
    def test_set_action_replaces_previous(self, mock_time):
        """Test set() replaces previous pending action."""
        mock_action1 = MagicMock()
        mock_action1.__class__.__name__ = 'Action1'
        mock_action1.id = 'action-1'

        mock_action2 = MagicMock()
        mock_action2.__class__.__name__ = 'Action2'
        mock_action2.id = 'action-2'

        mock_time.return_value = 100.0
        self.service.set(mock_action1)

        mock_time.return_value = 110.0
        self.service.set(mock_action2)

        # Should log setting each action (source doesn't auto-clear on replace)
        self.assertEqual(self.mock_controller.log.call_count, 2)  # set1 + set2

        # Current pending should be action2
        assert self.service._legacy_pending is not None
        action, timestamp = self.service._legacy_pending
        self.assertEqual(action, mock_action2)

    def test_custom_timeout(self):
        """Test service with custom timeout value."""
        service = PendingActionService(self.mock_context, timeout=60.0)

        self.assertEqual(service._timeout, 60.0)

    def test_shutdown_clears_pending_and_cancels_watchdog(self):
        """shutdown() should clear pending state and cancel watchdog."""
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        mock_action.id = 'action-123'
        self.service.set(mock_action)

        fake_handle = MagicMock()
        self.service._watchdog_handle = fake_handle

        self.service.shutdown()

        self.assertIsNone(self.service._legacy_pending)
        self.assertIsNone(self.service._watchdog_handle)
        fake_handle.cancel.assert_called_once_with()

    @patch('time.time')
    def test_zero_timeout_never_times_out(self, mock_time):
        """pending_action_timeout <= 0 disables timeout and watchdog."""
        service = PendingActionService(self.mock_context, timeout=0.0)
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        mock_action.id = 'action-123'

        mock_time.return_value = 100.0
        service.set(mock_action)
        mock_time.return_value = 100.0 + 86400.0 * 365
        action = service.get()

        self.assertEqual(action, mock_action)
        self.mock_controller.event_stream.add_event.assert_not_called()

    @patch('time.time')
    def test_mcp_action_with_zero_base_uses_no_floor(self, mock_time):
        """When base timeout is disabled, MCP floor must not apply."""
        service = PendingActionService(self.mock_context, timeout=0.0)
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'MCPAction'
        mock_action.id = 'mcp-1'

        mock_time.return_value = 0.0
        service.set(mock_action)
        mock_time.return_value = 1e9
        action = service.get()

        self.assertEqual(action, mock_action)
        self.mock_controller.event_stream.add_event.assert_not_called()

    @patch('time.time')
    def test_cmd_run_action_uses_long_timeout_floor(self, mock_time):
        """Long-running shell commands should outlive default pending timeout."""
        service = PendingActionService(self.mock_context, timeout=120.0)
        action = CmdRunAction(
            command='python -m venv .venv && pip install -r requirements.txt'
        )

        mock_time.return_value = 100.0
        service.set(action)

        # Past default pending timeout (120s), command should still be considered pending.
        mock_time.return_value = 320.0
        self.assertEqual(service.get(), action)

        # Past long command floor (600s), timeout should trigger.
        mock_time.return_value = 705.0
        self.assertIsNone(service.get())
        self.mock_controller.event_stream.add_event.assert_called_once()

    @patch('time.time')
    def test_cmd_run_action_progress_log_uses_effective_timeout(self, mock_time):
        """Long-running command progress logs should not be labeled as timeouts."""
        service = PendingActionService(self.mock_context, timeout=120.0)
        action = CmdRunAction(command='python -m venv .venv && pip install fastapi')

        mock_time.return_value = 100.0
        service.set(action)

        mock_time.return_value = 320.0
        self.assertEqual(service.get(), action)

        progress_logs = [
            call for call in self.mock_controller.log.call_args_list
            if 'Pending action still running' in call[0][1]
        ]
        self.assertEqual(len(progress_logs), 1)
        self.assertIn('timeout 600.0s', progress_logs[0][0][1])
        self.assertEqual(
            progress_logs[0][1]['extra']['msg_type'],
            'PENDING_ACTION_STILL_RUNNING',
        )

    @patch('time.time')
    def test_browser_tool_action_uses_long_timeout_floor(self, mock_time):
        """Native browser tool should outlive default pending timeout (Chromium launch)."""
        service = PendingActionService(self.mock_context, timeout=120.0)
        action = BrowserToolAction(
            command='navigate', params={'url': 'https://example.com'}
        )

        mock_time.return_value = 100.0
        service.set(action)

        # Still within browser_tool floor (165s default), past default pending (120s).
        mock_time.return_value = 100.0 + float(BROWSER_TOOL_SYNC_TIMEOUT_SECONDS) - 10.0
        self.assertEqual(service.get(), action)

        mock_time.return_value = 100.0 + float(BROWSER_TOOL_SYNC_TIMEOUT_SECONDS) + 5.0
        self.assertIsNone(service.get())
        self.mock_controller.event_stream.add_event.assert_called_once()


if __name__ == '__main__':
    unittest.main()


class TestPendingActionWatchdog(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mock_controller = MagicMock()
        self.mock_controller.log = MagicMock()
        self.mock_controller.event_stream = MagicMock()

        self.mock_context = MagicMock()
        self.mock_context.get_controller.return_value = self.mock_controller
        self.mock_context.trigger_step = MagicMock()

        self.service = PendingActionService(self.mock_context, timeout=5.0)

    @patch('time.time')
    async def test_watchdog_fire_calls_trigger_step_after_timeout(self, mock_time):
        mock_action = MagicMock()
        mock_action.__class__.__name__ = 'TestAction'
        mock_action.id = 'action-123'

        mock_time.return_value = 100.0
        self.service._legacy_pending = (mock_action, 100.0)

        mock_time.return_value = 106.0
        self.service._watchdog_fire()

        self.mock_context.trigger_step.assert_called_once_with()

    @patch(
        'backend.orchestration.services.pending_action_service.asyncio.get_running_loop'
    )
    @patch('backend.utils.async_utils.get_main_event_loop')
    async def test_schedule_watchdog_skips_when_no_active_loop_exists(
        self, mock_get_main_event_loop, mock_get_running_loop
    ):
        mock_get_running_loop.side_effect = RuntimeError('no running loop')
        mock_get_main_event_loop.return_value = None

        self.service._schedule_watchdog()

        self.assertIsNone(self.service._watchdog_handle)

    @patch('time.time')
    async def test_mcp_action_uses_timeout_floor_when_base_below_floor(self, mock_time):
        service = PendingActionService(self.mock_context, timeout=1.0)
        mock_action = type('MCPAction', (), {})()
        mock_action.id = '42'

        with patch(
            'backend.orchestration.services.pending_action_service.MCP_PENDING_ACTION_TIMEOUT_FLOOR',
            30.0,
        ):
            mock_time.return_value = 100.0
            service.set(mock_action)
            mock_time.return_value = 129.0
            self.assertEqual(service.get(), mock_action)

            mock_time.return_value = 131.0
            self.assertIsNone(service.get())
            self.mock_controller.event_stream.add_event.assert_called_once()
        service.shutdown()
