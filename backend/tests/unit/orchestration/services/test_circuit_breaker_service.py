"""Tests for CircuitBreakerService."""

import unittest
from unittest.mock import MagicMock, patch

from backend.orchestration.services.circuit_breaker_service import CircuitBreakerService


class TestCircuitBreakerService(unittest.TestCase):
    """Test CircuitBreakerService configuration and interactions."""

    def setUp(self):
        """Create mock context and controller for testing."""
        self.mock_controller = MagicMock()
        self.mock_context = MagicMock()
        self.mock_context.get_controller.return_value = self.mock_controller
        self.service = CircuitBreakerService(self.mock_context)

    def test_initialization(self):
        """Test service initializes with no circuit breaker."""
        self.assertEqual(self.service._context, self.mock_context)
        self.assertIsNone(self.service._circuit_breaker)

    def test_controller_accessor(self):
        """Test controller accessor returns controller from context."""
        controller = self.service.controller

        self.assertEqual(controller, self.mock_controller)
        self.mock_context.get_controller.assert_called_once()

    def test_reset_clears_circuit_breaker(self):
        """Test reset() disables circuit breaker."""
        # Set up circuit breaker
        mock_cb = MagicMock()
        self.service._circuit_breaker = mock_cb
        setattr(self.mock_controller, 'circuit_breaker', mock_cb)

        self.service.reset()

        self.assertIsNone(self.service._circuit_breaker)
        # Verify controller attribute was also cleared
        self.assertIsNone(getattr(self.mock_controller, 'circuit_breaker', 'NOT_SET'))

    @patch('backend.orchestration.services.circuit_breaker_service.CircuitBreaker')
    @patch(
        'backend.orchestration.services.circuit_breaker_service.CircuitBreakerConfig'
    )
    @patch('backend.orchestration.services.circuit_breaker_service.logger')
    def test_configure_enables_circuit_breaker(
        self, mock_logger, mock_config_class, mock_cb_class
    ):
        """Test configure() enables circuit breaker with agent config."""
        mock_agent_config = MagicMock()
        mock_agent_config.enable_circuit_breaker = True
        mock_agent_config.max_consecutive_errors = 5
        mock_agent_config.max_high_risk_actions = 10
        mock_agent_config.max_stuck_detections = 3

        mock_cb = MagicMock()
        mock_cb_class.return_value = mock_cb

        self.service.configure(mock_agent_config)

        # Should create CircuitBreakerConfig
        mock_config_class.assert_called_once_with(
            enabled=True,
            max_consecutive_errors=5,
            max_high_risk_actions=10,
            max_stuck_detections=3,
        )

        # Should create CircuitBreaker
        mock_cb_class.assert_called_once()

        # Should set on controller
        self.assertEqual(self.service._circuit_breaker, mock_cb)

        # Should log info message
        mock_logger.info.assert_called_once()

    @patch('backend.orchestration.services.circuit_breaker_service.logger')
    def test_configure_disabled_circuit_breaker(self, mock_logger):
        """Test configure() with disabled circuit breaker."""
        mock_agent_config = MagicMock()
        mock_agent_config.enable_circuit_breaker = False

        self.service.configure(mock_agent_config)

        self.assertIsNone(self.service._circuit_breaker)
        # Should not log info message
        mock_logger.info.assert_not_called()

    @patch('backend.orchestration.services.circuit_breaker_service.CircuitBreaker')
    @patch(
        'backend.orchestration.services.circuit_breaker_service.CircuitBreakerConfig'
    )
    def test_configure_uses_default_values(self, mock_config_class, mock_cb_class):
        """Test configure() uses default values when not specified."""
        mock_agent_config = MagicMock(spec=[])
        # enable_circuit_breaker not set - should default via getattr

        with patch.object(self.service, 'reset'):
            self.service.configure(mock_agent_config)

        # Check defaults were used
        config_call = mock_config_class.call_args[1]
        self.assertEqual(config_call['max_consecutive_errors'], 5)
        self.assertEqual(config_call['max_high_risk_actions'], 10)
        self.assertEqual(config_call['max_stuck_detections'], 15)

    @patch('backend.orchestration.services.circuit_breaker_service.CircuitBreaker')
    @patch(
        'backend.orchestration.services.circuit_breaker_service.CircuitBreakerConfig'
    )
    def test_configure_calls_reset_first(self, mock_config_class, mock_cb_class):
        """Test configure() calls reset before configuring."""
        mock_agent_config = MagicMock()
        mock_agent_config.enable_circuit_breaker = True

        with patch.object(self.service, 'reset') as mock_reset:
            self.service.configure(mock_agent_config)

            mock_reset.assert_called_once()

    def test_circuit_breaker_property_returns_instance(self):
        """Test circuit_breaker property returns configured instance."""
        mock_cb = MagicMock()
        self.service._circuit_breaker = mock_cb

        result = self.service.circuit_breaker

        self.assertEqual(result, mock_cb)

    def test_circuit_breaker_property_returns_none(self):
        """Test circuit_breaker property returns None when not configured."""
        result = self.service.circuit_breaker

        self.assertIsNone(result)

    def test_check_with_circuit_breaker(self):
        """Test check() calls circuit breaker check."""
        mock_cb = MagicMock()
        mock_result = MagicMock()
        mock_cb.check.return_value = mock_result

        self.service._circuit_breaker = mock_cb
        self.mock_controller.state = MagicMock()

        result = self.service.check()

        mock_cb.check.assert_called_once_with(self.mock_controller.state)
        self.assertEqual(result, mock_result)

    def test_check_without_circuit_breaker(self):
        """Test check() returns None when circuit breaker not configured."""
        result = self.service.check()

        self.assertIsNone(result)

    def test_record_error_with_circuit_breaker(self):
        """Test record_error() calls circuit breaker."""
        mock_cb = MagicMock()
        self.service._circuit_breaker = mock_cb

        test_error = ValueError('Test error')
        self.service.record_error(test_error)

        mock_cb.record_error.assert_called_once_with(test_error, tool_name='')

    def test_record_error_without_circuit_breaker(self):
        """Test record_error() does nothing when circuit breaker not configured."""
        test_error = ValueError('Test error')

        # Should not raise exception
        self.service.record_error(test_error)

    def test_record_success_with_circuit_breaker(self):
        """Test record_success() calls circuit breaker."""
        mock_cb = MagicMock()
        self.service._circuit_breaker = mock_cb

        self.service.record_success()

        mock_cb.record_success.assert_called_once()

    def test_record_success_without_circuit_breaker(self):
        """Test record_success() does nothing when circuit breaker not configured."""
        # Should not raise exception
        self.service.record_success()

    def test_record_high_risk_action_with_circuit_breaker(self):
        """Test record_high_risk_action() calls circuit breaker."""
        mock_cb = MagicMock()
        self.service._circuit_breaker = mock_cb

        mock_security_risk = MagicMock()
        self.service.record_high_risk_action(mock_security_risk)

        mock_cb.record_high_risk_action.assert_called_once_with(mock_security_risk)

    def test_record_high_risk_action_none_security_risk(self):
        """Test record_high_risk_action() does nothing when security_risk is None."""
        mock_cb = MagicMock()
        self.service._circuit_breaker = mock_cb

        self.service.record_high_risk_action(None)

        mock_cb.record_high_risk_action.assert_not_called()

    def test_record_high_risk_action_without_circuit_breaker(self):
        """Test record_high_risk_action() does nothing when circuit breaker not configured."""
        mock_security_risk = MagicMock()

        # Should not raise exception
        self.service.record_high_risk_action(mock_security_risk)

    def test_record_stuck_detection_with_circuit_breaker(self):
        """Test record_stuck_detection() calls circuit breaker."""
        mock_cb = MagicMock()
        self.service._circuit_breaker = mock_cb

        self.service.record_stuck_detection()

        mock_cb.record_stuck_detection.assert_called_once()

    def test_record_stuck_detection_without_circuit_breaker(self):
        """Test record_stuck_detection() does nothing when circuit breaker not configured."""
        # Should not raise exception
        self.service.record_stuck_detection()

    @patch('backend.orchestration.services.circuit_breaker_service.CircuitBreaker')
    @patch(
        'backend.orchestration.services.circuit_breaker_service.CircuitBreakerConfig'
    )
    def test_configure_then_reset_workflow(self, mock_config_class, mock_cb_class):
        """Test configure followed by reset clears circuit breaker."""
        mock_agent_config = MagicMock()
        mock_agent_config.enable_circuit_breaker = True

        # Configure
        self.service.configure(mock_agent_config)
        self.assertIsNotNone(self.service._circuit_breaker)

        # Reset
        self.service.reset()
        self.assertIsNone(self.service._circuit_breaker)

    @patch('backend.orchestration.services.circuit_breaker_service.CircuitBreaker')
    @patch(
        'backend.orchestration.services.circuit_breaker_service.CircuitBreakerConfig'
    )
    def test_multiple_configure_calls(self, mock_config_class, mock_cb_class):
        """Test multiple configure() calls properly reset."""
        mock_agent_config = MagicMock()
        mock_agent_config.enable_circuit_breaker = True

        # Configure mock to return different instances
        first_mock = MagicMock(name='first_cb')
        second_mock = MagicMock(name='second_cb')
        mock_cb_class.side_effect = [first_mock, second_mock]

        # First configure
        self.service.configure(mock_agent_config)
        first_cb = self.service._circuit_breaker

        # Second configure
        self.service.configure(mock_agent_config)
        second_cb = self.service._circuit_breaker

        # Should have created a new instance
        self.assertIsNot(first_cb, second_cb)


if __name__ == '__main__':
    unittest.main()
