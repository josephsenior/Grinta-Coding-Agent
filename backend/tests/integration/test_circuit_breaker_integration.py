import pytest
from unittest.mock import MagicMock
from backend.orchestration.session_orchestrator import SessionOrchestrator
from backend.orchestration.services.step_guard_service import StepGuardService
from backend.orchestration.agent_circuit_breaker import CircuitBreakerResult
from backend.ledger.observation import ErrorObservation

class TestCircuitBreakerIntegration:
    @pytest.mark.asyncio
    async def test_circuit_breaker_warning_trip(self):
        """
        Verify that when the circuit breaker trips within the warning limit,
        the StepGuardService:
        1. Injects an ErrorObservation with CIRCUIT_BREAKER_WARNING.
        2. Returns True (allows the step to proceed so the agent can self-correct).
        """
        mock_context = MagicMock()
        mock_controller = MagicMock(spec=SessionOrchestrator)
        mock_context.get_controller.return_value = mock_controller

        mock_controller.event_stream = MagicMock()
        mock_controller.event_stream.add_event = MagicMock()

        # Provide state with extra_data for warning trip counting
        mock_state = MagicMock()
        mock_state.extra_data = {}
        mock_controller.state = mock_state

        mock_cb_service = MagicMock()
        mock_controller.circuit_breaker_service = mock_cb_service
        # No stuck_service so _handle_stuck_detection is a no-op
        mock_controller.stuck_service = None

        step_guard = StepGuardService(mock_context)

        mock_cb_service.check.return_value = CircuitBreakerResult(
            tripped=True,
            reason="Stuck loop detected (2)",
            action="switch_context",
            system_message="SYSTEM INTERVENTION: Switch context immediately.",
            recommendation="Use escalate() or analyze_project_structure()."
        )

        can_step = await step_guard.ensure_can_step()

        # Warning trip allows stepping
        assert can_step is True, "Step should be allowed during warning trip"

        # Verify warning ErrorObservation was injected
        calls = mock_controller.event_stream.add_event.call_args_list
        assert len(calls) >= 1, "Should add at least one ErrorObservation"

        error_obs_call = next(
            (call for call in calls if isinstance(call[0][0], ErrorObservation)),
            None,
        )
        assert error_obs_call is not None, "ErrorObservation was not added"
        error_obs = error_obs_call[0][0]
        assert error_obs.error_id == "CIRCUIT_BREAKER_WARNING"
        assert "Stuck loop detected" in error_obs.content

    @pytest.mark.asyncio
    async def test_circuit_breaker_stop_action(self):
        """
        Verify that 'stop' action actually stops the agent after warning limit is exceeded.
        """
        mock_context = MagicMock()
        mock_controller = MagicMock(spec=SessionOrchestrator)
        mock_context.get_controller.return_value = mock_controller
        mock_controller.event_stream = MagicMock()
        mock_controller.stuck_service = None

        # Pre-fill warning trip counts to exceed the default limit of 3
        # so the next trip goes straight to hard stop.
        mock_state = MagicMock()
        mock_state.extra_data = {
            StepGuardService._WARNING_TRIP_COUNTS_KEY: {
                "stop:Too many errors": 4,
            }
        }
        mock_controller.state = mock_state

        mock_cb_service = MagicMock()
        mock_controller.circuit_breaker_service = mock_cb_service
        step_guard = StepGuardService(mock_context)

        mock_cb_service.check.return_value = CircuitBreakerResult(
            tripped=True,
            reason="Too many errors",
            action="stop",
            recommendation="Restart."
        )

        can_step = await step_guard.ensure_can_step()

        assert can_step is False, "Step should be blocked for stop action"
        mock_controller.set_agent_state_to.assert_called()
