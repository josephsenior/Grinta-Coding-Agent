"""Tests for AutonomyService."""

import unittest
from unittest.mock import MagicMock, patch

from backend.orchestration.services.autonomy_service import AutonomyService


class TestAutonomyService(unittest.TestCase):
    """Test AutonomyService autonomy and validation setup."""

    def setUp(self):
        """Create mock controller for testing."""
        self.mock_controller = MagicMock()
        self.mock_controller.circuit_breaker_service = MagicMock()
        self.mock_controller.retry_service = MagicMock()
        # AutonomyService must not clobber the timeout set at controller construction.
        self.mock_controller.PENDING_ACTION_TIMEOUT = 123.0
        self.service = AutonomyService(self.mock_controller)

    @patch("backend.orchestration.autonomy.AutonomyController")
    def test_initialize_no_agent_config(self, mock_autonomy_controller_class):
        """Test initialize() with no agent config sets defaults."""
        mock_agent = MagicMock()
        mock_agent.config = None

        self.service.initialize(mock_agent)

        # Should reset circuit breaker
        self.mock_controller.circuit_breaker_service.reset.assert_called_once()

        # Should set controllers to None
        self.assertIsNone(self.mock_controller.autonomy_controller)
        self.assertIsNone(self.mock_controller.safety_validator)
        self.assertIsNone(self.mock_controller.task_validator)

        self.assertEqual(self.mock_controller.PENDING_ACTION_TIMEOUT, 123.0)

        # Should reset retry metrics
        self.mock_controller.retry_service.reset_retry_metrics.assert_called_once()

        # Should NOT create AutonomyController
        mock_autonomy_controller_class.assert_not_called()

    @patch("backend.orchestration.autonomy.AutonomyController")
    def test_initialize_invalid_agent_config(self, mock_autonomy_controller_class):
        """Test initialize() with invalid agent config type sets defaults."""
        mock_agent = MagicMock()
        mock_agent.config = "not_an_agent_config"  # Invalid type

        self.service.initialize(mock_agent)

        self.assertIsNone(self.mock_controller.autonomy_controller)
        self.assertIsNone(self.mock_controller.safety_validator)
        self.assertIsNone(self.mock_controller.task_validator)

    @patch("backend.core.config.agent_config.AgentConfig")
    @patch("backend.orchestration.autonomy.AutonomyController")
    def test_initialize_with_valid_agent_config(
        self, mock_autonomy_controller_class, mock_agent_config_class
    ):
        """Test initialize() creates AutonomyController with valid config."""
        # Create a mock agent config that passes isinstance check
        mock_agent_config = MagicMock()
        mock_agent_config_class.return_value = mock_agent_config

        # Make isinstance return True for this mock
        with patch(
            "backend.orchestration.services.autonomy_service.isinstance", return_value=True
        ):
            mock_agent_config.safety = MagicMock()
            mock_agent_config.safety.enable_mandatory_validation = False
            mock_agent_config.enable_completion_validation = False

            mock_agent = MagicMock()
            mock_agent.config = mock_agent_config

            mock_autonomy_controller = MagicMock()
            mock_autonomy_controller_class.return_value = mock_autonomy_controller

            with patch.object(self.service, "_initialize_safety_validator"):
                with patch.object(self.service, "_initialize_task_validator"):
                    self.service.initialize(mock_agent)

        # Should create AutonomyController
        mock_autonomy_controller_class.assert_called_once_with(mock_agent_config)
        self.assertEqual(
            self.mock_controller.autonomy_controller, mock_autonomy_controller
        )

        # Should reset retry metrics
        self.mock_controller.retry_service.reset_retry_metrics.assert_called_once()

        # Should configure circuit breaker
        self.mock_controller.circuit_breaker_service.configure.assert_called_once_with(
            mock_agent_config
        )

    @patch("backend.orchestration.safety_validator.SafetyValidator")
    def test_initialize_safety_validator_enabled(self, mock_safety_validator_class):
        """Test _initialize_safety_validator enables SafetyValidator when configured."""
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.safety = MagicMock()
        mock_agent.config.safety.enable_mandatory_validation = True

        mock_safety_validator = MagicMock()
        mock_safety_validator_class.return_value = mock_safety_validator

        self.service._initialize_safety_validator(mock_agent)

        mock_safety_validator_class.assert_called_once_with(mock_agent.config.safety)
        self.assertEqual(self.mock_controller.safety_validator, mock_safety_validator)

    def test_initialize_safety_validator_disabled(self):
        """Test _initialize_safety_validator sets None when disabled."""
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.safety = MagicMock()
        mock_agent.config.safety.enable_mandatory_validation = False

        self.service._initialize_safety_validator(mock_agent)

        self.assertIsNone(self.mock_controller.safety_validator)

    def test_initialize_safety_validator_no_safety_config(self):
        """Test _initialize_safety_validator handles missing safety config."""
        mock_agent = MagicMock()
        mock_agent.config = MagicMock(spec=[])  # No safety attribute

        self.service._initialize_safety_validator(mock_agent)

        self.assertIsNone(self.mock_controller.safety_validator)

    @patch("backend.validation.task_validator.CompositeValidator")
    @patch("backend.validation.task_validator.DiffValidator")
    @patch("backend.validation.task_validator.TestPassingValidator")
    def test_initialize_task_validator_enabled(
        self, mock_test_validator, mock_diff_validator, mock_composite_validator
    ):
        """Test _initialize_task_validator enables TaskValidator when configured."""
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.enable_completion_validation = True

        mock_test_val = MagicMock()
        mock_diff_val = MagicMock()
        mock_composite_val = MagicMock()

        mock_test_validator.return_value = mock_test_val
        mock_diff_validator.return_value = mock_diff_val
        mock_composite_validator.return_value = mock_composite_val

        self.service._initialize_task_validator(mock_agent)

        # Should create validators
        mock_test_validator.assert_called_once()
        mock_diff_validator.assert_called_once()

        # Should create CompositeValidator
        mock_composite_validator.assert_called_once_with(
            validators=[mock_test_val, mock_diff_val],
            min_confidence=0.7,
            require_all_pass=False,
            fail_open_on_empty=False,
        )

        self.assertEqual(self.mock_controller.task_validator, mock_composite_val)
        self.assertEqual(self.mock_controller.PENDING_ACTION_TIMEOUT, 123.0)

    def test_initialize_task_validator_disabled(self):
        """Test _initialize_task_validator sets None when disabled."""
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.enable_completion_validation = False

        self.service._initialize_task_validator(mock_agent)

        self.assertIsNone(self.mock_controller.task_validator)
        self.assertEqual(self.mock_controller.PENDING_ACTION_TIMEOUT, 123.0)

    def test_initialize_task_validator_no_validation_config(self):
        """Test _initialize_task_validator handles missing validation config."""
        mock_agent = MagicMock()
        mock_agent.config = MagicMock(spec=[])  # No enable_completion_validation

        self.service._initialize_task_validator(mock_agent)

        self.assertIsNone(self.mock_controller.task_validator)

    @patch("backend.orchestration.autonomy.AutonomyController")
    def test_initialize_calls_add_system_message(self, mock_autonomy_controller_class):
        """Test initialize() calls _add_system_message after task validator setup."""
        from backend.core.config.agent_config import AgentConfig

        mock_agent_config = MagicMock(spec=AgentConfig)
        mock_agent = MagicMock()
        mock_agent.config = mock_agent_config
        mock_agent_config.safety = MagicMock()
        mock_agent_config.safety.enable_mandatory_validation = False
        mock_agent_config.enable_completion_validation = False

        # Don't patch _initialize_task_validator - let it run so _add_system_message is called
        with patch.object(self.service, "_initialize_safety_validator"):
            self.service.initialize(mock_agent)

        # _add_system_message is called in _initialize_task_validator
        # Check it was called
        self.mock_controller._add_system_message.assert_called_once()

    @patch("backend.orchestration.autonomy.AutonomyController")
    @patch("backend.orchestration.services.autonomy_service.logger")
    def test_initialize_logs_safety_validator_enabled(
        self, mock_logger, mock_autonomy_controller_class
    ):
        """Test initialize() logs when SafetyValidator is enabled."""
        from backend.core.config.agent_config import AgentConfig

        mock_agent_config = MagicMock(spec=AgentConfig)
        mock_agent = MagicMock()
        mock_agent.config = mock_agent_config
        mock_agent_config.safety = MagicMock()
        mock_agent_config.safety.enable_mandatory_validation = True
        mock_agent_config.enable_completion_validation = False

        with patch("backend.orchestration.safety_validator.SafetyValidator"):
            self.service.initialize(mock_agent)

        debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
        self.assertTrue(any("SafetyValidator enabled" in msg for msg in debug_calls))

    @patch("backend.orchestration.autonomy.AutonomyController")
    @patch("backend.orchestration.services.autonomy_service.logger")
    def test_initialize_logs_task_validator_enabled(
        self, mock_logger, mock_autonomy_controller_class
    ):
        """Test initialize() logs when TaskValidator is enabled."""
        from backend.core.config.agent_config import AgentConfig

        mock_agent_config = MagicMock(spec=AgentConfig)
        mock_agent = MagicMock()
        mock_agent.config = mock_agent_config
        mock_agent_config.safety = MagicMock()
        mock_agent_config.safety.enable_mandatory_validation = False
        mock_agent_config.enable_completion_validation = True

        with patch("backend.validation.task_validator.CompositeValidator"):
            with patch("backend.validation.task_validator.TestPassingValidator"):
                with patch("backend.validation.task_validator.DiffValidator"):
                    self.service.initialize(mock_agent)

        debug_calls = [call[0][0] for call in mock_logger.debug.call_args_list]
        self.assertTrue(any("TaskValidator enabled" in msg for msg in debug_calls))

    @patch("backend.orchestration.autonomy.AutonomyController")
    def test_initialize_full_workflow(self, mock_autonomy_controller_class):
        """Test complete initialize() workflow with all components enabled."""
        from backend.core.config.agent_config import AgentConfig

        mock_agent_config = MagicMock(spec=AgentConfig)
        mock_agent = MagicMock()
        mock_agent.config = mock_agent_config
        mock_agent_config.safety = MagicMock()
        mock_agent_config.safety.enable_mandatory_validation = True
        mock_agent_config.enable_completion_validation = True

        with patch("backend.orchestration.safety_validator.SafetyValidator"):
            with patch("backend.validation.task_validator.CompositeValidator"):
                with patch("backend.validation.task_validator.TestPassingValidator"):
                    with patch("backend.validation.task_validator.DiffValidator"):
                        self.service.initialize(mock_agent)

        # Verify all setup steps occurred
        self.mock_controller.circuit_breaker_service.reset.assert_called_once()
        self.mock_controller.retry_service.reset_retry_metrics.assert_called()
        self.mock_controller.circuit_breaker_service.configure.assert_called_once_with(
            mock_agent_config
        )
        self.assertIsNotNone(self.mock_controller.autonomy_controller)
        self.assertIsNotNone(self.mock_controller.safety_validator)
        self.assertIsNotNone(self.mock_controller.task_validator)


if __name__ == "__main__":
    unittest.main()
