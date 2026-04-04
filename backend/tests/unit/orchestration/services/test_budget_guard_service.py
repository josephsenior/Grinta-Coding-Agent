"""Tests for BudgetGuardService."""

import unittest
from unittest.mock import MagicMock, patch

from backend.orchestration.services.budget_guard_service import (
    _BUDGET_THRESHOLDS,
    BudgetGuardService,
)


class TestBudgetGuardService(unittest.TestCase):
    """Test BudgetGuardService budget tracking and alerting."""

    def setUp(self):
        """Create mock context for testing."""
        self.mock_context = MagicMock()
        self.mock_context.id = 'test-session-123'
        self.mock_context.state_tracker = MagicMock()
        self.service = BudgetGuardService(self.mock_context)

    def test_initialization(self):
        """Test service initializes with empty alert tracking."""
        self.assertEqual(self.service._context, self.mock_context)
        self.assertEqual(self.service._alerted_thresholds, set())

    def test_sync_with_metrics_calls_state_tracker(self):
        """Test sync_with_metrics calls state tracker sync."""
        self.service.sync_with_metrics()

        self.mock_context.state_tracker.sync_budget_flag_with_metrics.assert_called_once()

    def test_sync_with_metrics_no_state_tracker(self):
        """Test sync_with_metrics handles missing state tracker."""
        self.mock_context.state_tracker = None

        # Should not raise exception
        self.service.sync_with_metrics()

    def test_sync_with_metrics_missing_sync_method(self):
        """Test sync_with_metrics handles state tracker without sync method."""
        self.mock_context.state_tracker = MagicMock(spec=[])

        # Should not raise exception
        self.service.sync_with_metrics()

    def test_check_budget_thresholds_no_state(self):
        """Test budget check with no state does nothing."""
        self.mock_context.state = None

        self.service._check_budget_thresholds()

        self.assertEqual(len(self.service._alerted_thresholds), 0)

    def test_check_budget_thresholds_no_budget_flag(self):
        """Test budget check with no budget flag does nothing."""
        self.mock_context.state = MagicMock()
        del self.mock_context.state.budget_flag

        self.service._check_budget_thresholds()

        self.assertEqual(len(self.service._alerted_thresholds), 0)

    def test_check_budget_thresholds_missing_values(self):
        """Test budget check with None current/max values does nothing."""
        budget_flag = MagicMock()
        budget_flag.current_value = None
        budget_flag.max_value = 100.0

        self.mock_context.state = MagicMock()
        self.mock_context.state.budget_flag = budget_flag

        self.service._check_budget_thresholds()

        self.assertEqual(len(self.service._alerted_thresholds), 0)

    def test_check_budget_thresholds_zero_max_value(self):
        """Test budget check with zero max value does nothing."""
        budget_flag = MagicMock()
        budget_flag.current_value = 50.0
        budget_flag.max_value = 0.0

        self.mock_context.state = MagicMock()
        self.mock_context.state.budget_flag = budget_flag

        self.service._check_budget_thresholds()

        self.assertEqual(len(self.service._alerted_thresholds), 0)

    @patch('backend.orchestration.services.budget_guard_service.logger')
    def test_check_budget_thresholds_50_percent(self, mock_logger):
        """Test budget alert at 50% threshold."""
        budget_flag = MagicMock()
        budget_flag.current_value = 50.0
        budget_flag.max_value = 100.0

        self.mock_context.state = MagicMock()
        self.mock_context.state.budget_flag = budget_flag

        with patch.object(self.service, '_emit_budget_alert') as mock_emit:
            self.service._check_budget_thresholds()

            mock_emit.assert_called_once()
            args = mock_emit.call_args[0]
            self.assertEqual(args[0], 0.50)  # threshold
            self.assertEqual(args[1], 50.0)  # current
            self.assertEqual(args[2], 100.0)  # max_value
            self.assertEqual(args[3], 0.5)  # pct

        self.assertIn(0.50, self.service._alerted_thresholds)

    @patch('backend.orchestration.services.budget_guard_service.logger')
    def test_check_budget_thresholds_80_percent(self, mock_logger):
        """Test budget alert at 80% threshold."""
        budget_flag = MagicMock()
        budget_flag.current_value = 80.0
        budget_flag.max_value = 100.0

        self.mock_context.state = MagicMock()
        self.mock_context.state.budget_flag = budget_flag

        with patch.object(self.service, '_emit_budget_alert') as mock_emit:
            self.service._check_budget_thresholds()

            # Should emit for both 50% and 80%
            self.assertEqual(mock_emit.call_count, 2)

        self.assertIn(0.50, self.service._alerted_thresholds)
        self.assertIn(0.80, self.service._alerted_thresholds)

    @patch('backend.orchestration.services.budget_guard_service.logger')
    def test_check_budget_thresholds_90_percent(self, mock_logger):
        """Test budget alert at 90% threshold."""
        budget_flag = MagicMock()
        budget_flag.current_value = 91.0
        budget_flag.max_value = 100.0

        self.mock_context.state = MagicMock()
        self.mock_context.state.budget_flag = budget_flag

        with patch.object(self.service, '_emit_budget_alert') as mock_emit:
            self.service._check_budget_thresholds()

            # Should emit for all three thresholds
            self.assertEqual(mock_emit.call_count, 3)

        self.assertEqual(self.service._alerted_thresholds, {0.50, 0.80, 0.90})

    @patch('backend.orchestration.services.budget_guard_service.logger')
    def test_check_budget_thresholds_no_duplicate_alerts(self, mock_logger):
        """Test threshold alerts only fire once."""
        budget_flag = MagicMock()
        budget_flag.current_value = 60.0
        budget_flag.max_value = 100.0

        self.mock_context.state = MagicMock()
        self.mock_context.state.budget_flag = budget_flag

        with patch.object(self.service, '_emit_budget_alert') as mock_emit:
            # First check at 60%
            self.service._check_budget_thresholds()
            self.assertEqual(mock_emit.call_count, 1)

            # Second check still at 60% - no new alerts
            self.service._check_budget_thresholds()
            self.assertEqual(mock_emit.call_count, 1)  # Still just 1

            # Increase to 85%
            budget_flag.current_value = 85.0
            self.service._check_budget_thresholds()
            # Should emit one more for 80% threshold
            self.assertEqual(mock_emit.call_count, 2)

    @patch('backend.orchestration.services.budget_guard_service.logger')
    def test_emit_budget_alert_creates_status_observation(self, mock_logger):
        """Test _emit_budget_alert creates and emits StatusObservation."""
        with patch(
            'backend.orchestration.services.budget_guard_service.StatusObservation'
        ) as mock_obs_class:
            mock_obs = MagicMock()
            mock_obs_class.return_value = mock_obs

            self.service._emit_budget_alert(0.50, 50.0, 100.0, 0.5)

            # Check StatusObservation was created with correct data
            mock_obs_class.assert_called_once()
            call_kwargs = mock_obs_class.call_args[1]

            self.assertIn('50%', call_kwargs['content'])
            self.assertIn('$100.00', call_kwargs['content'])
            self.assertEqual(call_kwargs['status_type'], 'budget_alert')
            self.assertEqual(call_kwargs['extras']['threshold'], 0.50)
            self.assertEqual(call_kwargs['extras']['pct_used'], 0.5)
            self.assertEqual(call_kwargs['extras']['current_cost'], 50.0)
            self.assertEqual(call_kwargs['extras']['max_budget'], 100.0)

            # Check event was emitted
            self.mock_context.emit_event.assert_called_once()

    @patch('backend.orchestration.services.budget_guard_service.logger')
    def test_emit_budget_alert_logs_warning(self, mock_logger):
        """Test _emit_budget_alert logs warning message."""
        with patch(
            'backend.orchestration.services.budget_guard_service.StatusObservation'
        ):
            self.service._emit_budget_alert(0.80, 80.0, 100.0, 0.8)

            mock_logger.warning.assert_called_once()
            log_call = mock_logger.warning.call_args
            # Check that 80 (the percentage value) is in the args
            self.assertEqual(log_call[0][1], 80)  # level_pct argument
            self.assertIn('threshold', log_call[0][0])  # format string

    @patch('backend.orchestration.services.budget_guard_service.logger')
    def test_emit_budget_alert_handles_exception(self, mock_logger):
        """Test _emit_budget_alert handles exception gracefully."""
        with patch(
            'backend.orchestration.services.budget_guard_service.StatusObservation',
            side_effect=Exception('Test error'),
        ):
            # Should not raise exception
            self.service._emit_budget_alert(0.50, 50.0, 100.0, 0.5)

            # Should log debug message
            mock_logger.debug.assert_called_once()

    def test_budget_thresholds_constant(self):
        """Test _BUDGET_THRESHOLDS is properly defined."""
        self.assertEqual(_BUDGET_THRESHOLDS, (0.50, 0.80, 0.90))
        self.assertEqual(len(_BUDGET_THRESHOLDS), 3)

    @patch('backend.orchestration.services.budget_guard_service.logger')
    def test_sync_with_metrics_integration(self, mock_logger):
        """Test full sync_with_metrics integration."""
        budget_flag = MagicMock()
        budget_flag.current_value = 55.0
        budget_flag.max_value = 100.0

        self.mock_context.state = MagicMock()
        self.mock_context.state.budget_flag = budget_flag

        with patch(
            'backend.orchestration.services.budget_guard_service.StatusObservation'
        ):
            self.service.sync_with_metrics()

            # Should have called state tracker
            self.mock_context.state_tracker.sync_budget_flag_with_metrics.assert_called_once()

            # Should have emitted 50% threshold alert
            self.assertIn(0.50, self.service._alerted_thresholds)
            self.mock_context.emit_event.assert_called_once()

    def test_high_precision_budget_values(self):
        """Test budget tracking with high-precision decimal values."""
        budget_flag = MagicMock()
        budget_flag.current_value = 50.456789  # Above 50% of 100.789
        budget_flag.max_value = 100.789

        self.mock_context.state = MagicMock()
        self.mock_context.state.budget_flag = budget_flag

        with patch.object(self.service, '_emit_budget_alert') as mock_emit:
            self.service._check_budget_thresholds()

            # Should trigger 50% threshold (50.456789 / 100.789 = 50.06%)
            mock_emit.assert_called_once()
            self.assertIn(0.50, self.service._alerted_thresholds)


if __name__ == '__main__':
    unittest.main()
