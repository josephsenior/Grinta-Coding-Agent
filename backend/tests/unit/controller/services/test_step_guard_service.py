"""Tests for StepGuardService."""

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock

from backend.controller.services.step_guard_service import StepGuardService


class TestStepGuardService(unittest.IsolatedAsyncioTestCase):
    """Test StepGuardService circuit breaker and stuck detection guards."""

    def setUp(self):
        """Create mock context and controller for testing."""
        self.mock_controller = MagicMock()
        self.mock_controller.event_stream = MagicMock()
        self.mock_controller.set_agent_state_to = AsyncMock()
        self.mock_controller._react_to_exception = AsyncMock()

        self.mock_context = MagicMock()
        self.mock_context.get_controller.return_value = self.mock_controller
        self.mock_context.agent_config = None

        self.service = StepGuardService(self.mock_context)

    async def test_ensure_can_step_all_checks_pass(self):
        """Test ensure_can_step returns True when all checks pass."""
        self.mock_controller.circuit_breaker_service = None
        self.mock_controller.stuck_service = None

        result = await self.service.ensure_can_step()

        self.assertTrue(result)

    async def test_ensure_can_step_circuit_breaker_warning_allows_continuation(self):
        """Test warning-first mode allows stepping for early circuit trips."""
        mock_cb_service = MagicMock()
        mock_result = MagicMock()
        mock_result.tripped = True
        mock_result.reason = "Too many errors"
        mock_result.action = "stop"
        mock_result.recommendation = "Fix the errors"
        mock_cb_service.check.return_value = mock_result

        self.mock_controller.circuit_breaker_service = mock_cb_service
        self.mock_controller.stuck_service = None
        self.mock_controller.state = MagicMock()
        self.mock_controller.state.extra_data = {}
        self.mock_controller.state.set_extra = MagicMock()
        self.mock_controller.state.set_planning_directive = MagicMock()
        self.mock_context.agent_config = SimpleNamespace(
            warning_first_trip_enabled=True,
            warning_first_trip_limit=2,
        )

        result = await self.service.ensure_can_step()

        self.assertTrue(result)
        self.mock_controller.event_stream.add_event.assert_called_once()
        emitted = self.mock_controller.event_stream.add_event.call_args.args[0]
        self.assertEqual(getattr(emitted, "error_id", ""), "CIRCUIT_BREAKER_WARNING")
        self.mock_controller.set_agent_state_to.assert_not_called()

    async def test_ensure_can_step_circuit_breaker_blocks_after_warning_limit(self):
        """Test circuit breaker escalates to hard block after warning budget is exhausted."""
        mock_cb_service = MagicMock()
        mock_result = MagicMock()
        mock_result.tripped = True
        mock_result.reason = "Too many errors"
        mock_result.action = "stop"
        mock_result.recommendation = "Fix the errors"
        mock_cb_service.check.return_value = mock_result

        self.mock_controller.circuit_breaker_service = mock_cb_service
        self.mock_controller.stuck_service = None
        self.mock_controller.state = MagicMock()
        self.mock_controller.state.extra_data = {}
        self.mock_controller.state.set_extra = MagicMock()
        self.mock_controller.state.set_planning_directive = MagicMock()
        self.mock_context.agent_config = SimpleNamespace(
            warning_first_trip_enabled=True,
            warning_first_trip_limit=2,
        )

        first = await self.service.ensure_can_step()
        second = await self.service.ensure_can_step()
        third = await self.service.ensure_can_step()

        self.assertTrue(first)
        self.assertTrue(second)
        self.assertFalse(third)
        self.mock_controller.set_agent_state_to.assert_called_once()
