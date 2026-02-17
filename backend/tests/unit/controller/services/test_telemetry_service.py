"""Tests for TelemetryService."""

import unittest
from unittest.mock import MagicMock, Mock, patch

from backend.controller.services.telemetry_service import TelemetryService


class TestTelemetryService(unittest.TestCase):
    """Test TelemetryService tool pipeline and telemetry."""

    def setUp(self):
        """Create mock context and controller for testing."""
        self.mock_controller = MagicMock()
        self.mock_context = MagicMock()
        self.mock_context.get_controller.return_value = self.mock_controller
        self.mock_context.agent_config = MagicMock()
        
        self.service = TelemetryService(self.mock_context)

    @patch('backend.controller.tool_pipeline.SafetyValidatorMiddleware')
    @patch('backend.controller.idempotency.IdempotencyMiddleware')
    @patch('backend.controller.tool_pipeline.CircuitBreakerMiddleware')
    @patch('backend.controller.tool_pipeline.CostQuotaMiddleware')
    @patch('backend.controller.rollback_middleware.RollbackMiddleware')
    @patch('backend.controller.pre_exec_diff.PreExecDiffMiddleware')
    @patch('backend.controller.tool_pipeline.LoggingMiddleware')
    @patch('backend.controller.tool_pipeline.TelemetryMiddleware')
    @patch('backend.controller.tool_result_validator.ToolResultValidator')
    def test_initialize_tool_pipeline_default(
        self, mock_validator, mock_telemetry, mock_logging, mock_diff,
        mock_rollback, mock_cost, mock_circuit, mock_idempotency, mock_safety
    ):
        """Test initialize_tool_pipeline creates default middleware stack."""
        self.mock_context.agent_config.enable_planning_middleware = False
        self.mock_context.agent_config.enable_reflection_middleware = False
        
        self.service.initialize_tool_pipeline()
        
        # Check all default middlewares were created
        mock_safety.assert_called_once_with(self.mock_controller)
        mock_idempotency.assert_called_once()
        mock_circuit.assert_called_once_with(self.mock_controller)
        mock_cost.assert_called_once_with(self.mock_controller)
        mock_rollback.assert_called_once()
        mock_diff.assert_called_once()
        mock_logging.assert_called_once_with(self.mock_controller)
        mock_telemetry.assert_called_once_with(self.mock_controller)
        mock_validator.assert_called_once()
        
        # Check pipeline was initialized
        self.mock_context.initialize_tool_pipeline.assert_called_once()

    @patch('backend.controller.tool_pipeline.PlanningMiddleware')
    @patch('backend.controller.tool_pipeline.SafetyValidatorMiddleware')
    @patch('backend.controller.idempotency.IdempotencyMiddleware')
    @patch('backend.controller.tool_pipeline.CircuitBreakerMiddleware')
    @patch('backend.controller.tool_pipeline.CostQuotaMiddleware')
    @patch('backend.controller.rollback_middleware.RollbackMiddleware')
    @patch('backend.controller.pre_exec_diff.PreExecDiffMiddleware')
    @patch('backend.controller.tool_pipeline.LoggingMiddleware')
    @patch('backend.controller.tool_pipeline.TelemetryMiddleware')
    @patch('backend.controller.tool_result_validator.ToolResultValidator')
    def test_initialize_tool_pipeline_with_planning(
        self, mock_validator, mock_telemetry, mock_logging, mock_diff,
        mock_rollback, mock_cost, mock_circuit, mock_idempotency, 
        mock_safety, mock_planning
    ):
        """Test initialize_tool_pipeline includes planning middleware when enabled."""
        self.mock_context.agent_config.enable_planning_middleware = True
        self.mock_context.agent_config.enable_reflection_middleware = False
        
        self.service.initialize_tool_pipeline()
        
        # Check planning middleware was created
        mock_planning.assert_called_once_with(self.mock_controller)

    @patch('backend.controller.tool_pipeline.ReflectionMiddleware')
    @patch('backend.controller.tool_pipeline.SafetyValidatorMiddleware')
    @patch('backend.controller.idempotency.IdempotencyMiddleware')
    @patch('backend.controller.tool_pipeline.CircuitBreakerMiddleware')
    @patch('backend.controller.tool_pipeline.CostQuotaMiddleware')
    @patch('backend.controller.rollback_middleware.RollbackMiddleware')
    @patch('backend.controller.pre_exec_diff.PreExecDiffMiddleware')
    @patch('backend.controller.tool_pipeline.LoggingMiddleware')
    @patch('backend.controller.tool_pipeline.TelemetryMiddleware')
    @patch('backend.controller.tool_result_validator.ToolResultValidator')
    def test_initialize_tool_pipeline_with_reflection(
        self, mock_validator, mock_telemetry, mock_logging, mock_diff,
        mock_rollback, mock_cost, mock_circuit, mock_idempotency,
        mock_safety, mock_reflection
    ):
        """Test initialize_tool_pipeline includes reflection middleware when enabled."""
        self.mock_context.agent_config.enable_planning_middleware = False
        self.mock_context.agent_config.enable_reflection_middleware = True
        
        self.service.initialize_tool_pipeline()
        
        # Check reflection middleware was created
        mock_reflection.assert_called_once_with(self.mock_controller)

    @patch('backend.controller.tool_pipeline.SafetyValidatorMiddleware')
    @patch('backend.controller.idempotency.IdempotencyMiddleware')
    @patch('backend.controller.tool_pipeline.CircuitBreakerMiddleware')
    @patch('backend.controller.tool_pipeline.CostQuotaMiddleware')
    @patch('backend.controller.rollback_middleware.RollbackMiddleware')
    @patch('backend.controller.pre_exec_diff.PreExecDiffMiddleware')
    @patch('backend.controller.tool_pipeline.LoggingMiddleware')
    @patch('backend.controller.tool_pipeline.TelemetryMiddleware')
    @patch('backend.controller.tool_result_validator.ToolResultValidator')
    def test_initialize_tool_pipeline_none_config(
        self, mock_validator, mock_telemetry, mock_logging, mock_diff,
        mock_rollback, mock_cost, mock_circuit, mock_idempotency, mock_safety
    ):
        """Test initialize_tool_pipeline handles None config."""
        self.mock_context.agent_config = None
        
        # Should not raise exception
        self.service.initialize_tool_pipeline()
        
        # Should still initialize pipeline
        self.mock_context.initialize_tool_pipeline.assert_called_once()

    @patch('backend.controller.tool_telemetry.ToolTelemetry')
    @patch('backend.events.observation.ErrorObservation')
    def test_handle_blocked_invocation(self, mock_error_obs, mock_tool_telemetry):
        """Test handle_blocked_invocation emits error and cleans up."""
        mock_action = MagicMock()
        mock_action.id = "action-123"
        
        mock_ctx = MagicMock()
        mock_ctx.blocked = True
        mock_ctx.block_reason = "Security risk detected"
        mock_ctx.metadata = {}
        
        mock_telemetry_instance = MagicMock()
        mock_tool_telemetry.get_instance.return_value = mock_telemetry_instance
        
        mock_obs = MagicMock()
        mock_error_obs.return_value = mock_obs
        
        self.service.handle_blocked_invocation(mock_action, mock_ctx)
        
        # Should cleanup action context
        self.mock_context.cleanup_action_context.assert_called_once_with(mock_ctx, action=mock_action)
        
        # Should record telemetry
        mock_telemetry_instance.on_blocked.assert_called_once_with(mock_ctx, reason="Security risk detected")
        
        # Should emit error observation
        mock_error_obs.assert_called_once()
        call_kwargs = mock_error_obs.call_args[1]
        self.assertIn("Security risk detected", call_kwargs['content'])
        self.assertEqual(call_kwargs['error_id'], "TOOL_PIPELINE_BLOCKED")
        self.assertEqual(mock_obs.cause, "action-123")
        
        # Should emit event
        self.mock_context.emit_event.assert_called_once()
        
        # Should clear pending action
        self.mock_context.clear_pending_action.assert_called_once()

    @patch('backend.controller.tool_telemetry.ToolTelemetry')
    def test_handle_blocked_invocation_already_handled(self, mock_tool_telemetry):
        """Test handle_blocked_invocation skips error when already handled."""
        mock_action = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.blocked = True
        mock_ctx.block_reason = "Test reason"
        mock_ctx.metadata = {"handled": True}
        
        mock_telemetry_instance = MagicMock()
        mock_tool_telemetry.get_instance.return_value = mock_telemetry_instance
        
        self.service.handle_blocked_invocation(mock_action, mock_ctx)
        
        # Should not emit error observation when already handled
        self.mock_context.emit_event.assert_not_called()
        
        # Should still cleanup and clear
        self.mock_context.cleanup_action_context.assert_called_once()
        self.mock_context.clear_pending_action.assert_called_once()

    @patch('backend.controller.tool_telemetry.ToolTelemetry')
    @patch('backend.events.observation.ErrorObservation')
    @patch('backend.controller.services.telemetry_service.logger')
    def test_handle_blocked_invocation_telemetry_exception(
        self, mock_logger, mock_error_obs, mock_tool_telemetry
    ):
        """Test handle_blocked_invocation handles telemetry exceptions gracefully."""
        mock_action = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.blocked = True
        mock_ctx.block_reason = "Test"
        mock_ctx.metadata = {}
        
        mock_telemetry_instance = MagicMock()
        mock_telemetry_instance.on_blocked.side_effect = RuntimeError("Telemetry failed")
        mock_tool_telemetry.get_instance.return_value = mock_telemetry_instance
        
        # Should not raise exception
        self.service.handle_blocked_invocation(mock_action, mock_ctx)
        
        # Should log the error
        mock_logger.debug.assert_called_once()
        
        # Should still emit error observation and cleanup
        self.mock_context.emit_event.assert_called_once()
        self.mock_context.cleanup_action_context.assert_called_once()

    @patch('backend.controller.tool_telemetry.ToolTelemetry')
    @patch('backend.events.observation.ErrorObservation')
    def test_handle_blocked_invocation_none_block_reason(
        self, mock_error_obs, mock_tool_telemetry
    ):
        """Test handle_blocked_invocation uses default message when no block_reason."""
        mock_action = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.blocked = True
        mock_ctx.block_reason = None
        mock_ctx.metadata = {}
        
        mock_telemetry_instance = MagicMock()
        mock_tool_telemetry.get_instance.return_value = mock_telemetry_instance
        
        self.service.handle_blocked_invocation(mock_action, mock_ctx)
        
        # Should use default message
        call_kwargs = mock_error_obs.call_args[1]
        self.assertIn("Action blocked by middleware pipeline", call_kwargs['content'])

    @patch('backend.controller.tool_telemetry.ToolTelemetry')
    @patch('backend.events.observation.ErrorObservation')
    def test_handle_blocked_invocation_none_action_id(
        self, mock_error_obs, mock_tool_telemetry
    ):
        """Test handle_blocked_invocation handles action without id."""
        mock_action = MagicMock(spec=[])  # No id attribute
        mock_ctx = MagicMock()
        mock_ctx.blocked = True
        mock_ctx.block_reason = "Test"
        mock_ctx.metadata = {}
        
        mock_telemetry_instance = MagicMock()
        mock_tool_telemetry.get_instance.return_value = mock_telemetry_instance
        
        mock_obs = MagicMock()
        mock_error_obs.return_value = mock_obs
        
        self.service.handle_blocked_invocation(mock_action, mock_ctx)
        
        # Should set cause to None
        self.assertIsNone(mock_obs.cause)


if __name__ == '__main__':
    unittest.main()
