import pytest
from unittest.mock import MagicMock
from backend.controller.agent_controller import AgentController
from backend.controller.services.step_guard_service import StepGuardService
from backend.controller.agent_circuit_breaker import CircuitBreakerResult
from backend.events.action import SystemMessageAction
from backend.events.observation import ErrorObservation

class TestCircuitBreakerIntegration:
    @pytest.mark.asyncio
    async def test_circuit_breaker_switch_context_integration(self):
        """
        Verify that when the circuit breaker returns a 'switch_context' action,
        the StepGuardService:
        1. Injects a SystemMessageAction into the event stream.
        2. Injects an ErrorObservation (for visibility) into the event stream.
        3. Returns True (allows the step to proceed so the agent can see the message).
        """
        # Setup Controller Context Mock
        mock_context = MagicMock()
        mock_controller = MagicMock(spec=AgentController)
        mock_context.get_controller.return_value = mock_controller

        # Setup Event Stream
        mock_controller.event_stream = MagicMock()
        mock_controller.event_stream.add_event = MagicMock()

        # Setup Circuit Breaker Service on Controller
        mock_cb_service = MagicMock()
        mock_controller.circuit_breaker_service = mock_cb_service

        # Create StepGuardService with the mock context
        step_guard = StepGuardService(mock_context)

        # Configure Circuit Breaker to return 'switch_context'
        mock_cb_service.check.return_value = CircuitBreakerResult(
            tripped=True,
            reason="Stuck loop detected (2)",
            action="switch_context",
            system_message="SYSTEM INTERVENTION: Switch context immediately.",
            recommendation="Use escalate() or analyze_project_structure()."
        )

        # Execute
        can_step = await step_guard.ensure_can_step()

        # Assert 1: Step should be allowed (True) so agent can process the new message
        assert can_step is True, "Step should be allowed for context switching"

        # Assert 2: Verify SystemMessageAction injection
        # Check calls to event_stream.add_event
        calls = mock_controller.event_stream.add_event.call_args_list
        assert len(calls) >= 2, "Should add at least SystemMessage and ErrorObservation"

        # Find SystemMessageAction
        sys_msg_call = next((call for call in calls if isinstance(call[0][0], SystemMessageAction)), None)
        assert sys_msg_call is not None, "SystemMessageAction was not added"
        sys_msg = sys_msg_call[0][0]
        assert "Switch context immediately" in sys_msg.content

        # Find ErrorObservation
        error_obs_call = next((call for call in calls if isinstance(call[0][0], ErrorObservation)), None)
        assert error_obs_call is not None, "ErrorObservation was not added"
        error_obs = error_obs_call[0][0]
        assert "SYSTEM INTERVENTION" in error_obs.content
        assert error_obs.error_id == "CIRCUIT_BREAKER_SWITCH_CONTEXT"

    @pytest.mark.asyncio
    async def test_circuit_breaker_stop_action(self):
        """
        Verify that 'stop' action actually stops the agent.
        """
        # Setup
        mock_context = MagicMock()
        mock_controller = MagicMock(spec=AgentController)
        mock_context.get_controller.return_value = mock_controller
        mock_controller.event_stream = MagicMock()
        mock_cb_service = MagicMock()
        mock_controller.circuit_breaker_service = mock_cb_service
        step_guard = StepGuardService(mock_context)

        # Configure Circuit Breaker to return 'stop'
        mock_cb_service.check.return_value = CircuitBreakerResult(
            tripped=True,
            reason="Too many errors",
            action="stop",
            recommendation="Restart."
        )

        # Execute
        can_step = await step_guard.ensure_can_step()

        # Assert
        assert can_step is False, "Step should be blocked for stop action"
        mock_controller.set_agent_state_to.assert_called() # Should call with STOPPED
