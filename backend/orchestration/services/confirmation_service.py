"""Handles confirmation policy decisions and action sourcing."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import Action, ActionConfirmationStatus

if TYPE_CHECKING:
    from backend.orchestration.services.orchestration_context import OrchestrationContext
    from backend.orchestration.services.safety_service import SafetyService
    from backend.orchestration.tool_pipeline import ToolInvocationContext
    from backend.ledger.observation import Observation


class ConfirmationService:
    """Encapsulates confirmation gates, replay sourcing, and pending transitions."""

    def __init__(
        self,
        context: OrchestrationContext,
        safety_service: SafetyService,
    ) -> None:
        self._context = context
        self._safety_service = safety_service
        self._replay_action_count = 0
        self._live_action_count = 0

    def get_next_action(self) -> Action:
        """Fetch the next action from replay logs or the agent directly."""
        controller = self._context.get_controller()
        if controller._replay_manager.should_replay():
            action = controller._replay_manager.step()
            self._replay_action_count += 1
            action_type = type(action).__name__
            action_id = getattr(action, "id", "unknown")
            controller.log(
                "debug",
                f"Replay action #{self._replay_action_count}: {action_type} (id={action_id})",
                extra={
                    "msg_type": "REPLAY_ACTION",
                    "replay_index": controller._replay_manager.replay_index,
                    "action_type": action_type,
                },
            )
            return action

        action = controller.agent.step(controller.state)
        action.source = EventSource.AGENT
        self._live_action_count += 1
        action_type = type(action).__name__
        controller.log(
            "debug",
            f"Live action #{self._live_action_count}: {action_type}",
            extra={
                "msg_type": "LIVE_ACTION",
                "action_type": action_type,
            },
        )
        return action

    @property
    def is_replay_mode(self) -> bool:
        """Check if the controller is currently in replay mode."""
        controller = self._context.get_controller()
        return controller._replay_manager.replay_mode

    @property
    def replay_progress(self) -> tuple[int, int] | None:
        """Return (current_index, total_events) if in replay mode, else None."""
        controller = self._context.get_controller()
        if not controller._replay_manager.replay_mode:
            return None
        total = (
            len(controller._replay_manager.replay_events)
            if controller._replay_manager.replay_events
            else 0
        )
        return (controller._replay_manager.replay_index, total)

    @property
    def action_counts(self) -> dict[str, int]:
        """Return counts of replay vs live actions for telemetry."""
        return {
            "replay_actions": self._replay_action_count,
            "live_actions": self._live_action_count,
        }

    async def evaluate_action(self, action: Action) -> None:
        """Run confirmation policy checks for a runnable action."""
        controller = self._context.get_controller()
        if not controller.state.confirmation_mode:
            return

        if not self._safety_service.action_requires_confirmation(action):
            return

        await self._safety_service.analyze_security(action)
        is_high_security_risk, is_ask_for_every_action = (
            self._safety_service.evaluate_security_risk(action)
        )
        self._safety_service.apply_confirmation_state(
            action,
            is_high_security_risk=is_high_security_risk,
            is_ask_for_every_action=is_ask_for_every_action,
        )

    async def handle_pending_confirmation(self, action: Action) -> bool:
        """Transition controller to awaiting state when confirmation is required."""
        if not hasattr(action, "confirmation_state"):
            return False

        if action.confirmation_state != ActionConfirmationStatus.AWAITING_CONFIRMATION:
            return False

        await self._context.set_agent_state(AgentState.AWAITING_USER_CONFIRMATION)
        return True

    async def handle_observation_for_pending_action(
        self, observation: Observation, ctx: ToolInvocationContext | None
    ) -> None:
        """Handle state transitions when an observation arrives for a pending action."""
        controller = self._context.get_controller()
        from backend.orchestration.services.observation_service import (
            transition_agent_state_logic,
        )

        await transition_agent_state_logic(controller, ctx, observation)
