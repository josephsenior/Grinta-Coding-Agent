from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.orchestration.agent import Agent
    from backend.orchestration.session_orchestrator import SessionOrchestrator


class AutonomyService:
    """Encapsulates autonomy, safety, and validation setup for an agent."""

    def __init__(self, controller: SessionOrchestrator) -> None:
        self._controller = controller

    def initialize(self, agent: Agent) -> None:
        """Configure autonomy controller and related validators."""
        from backend.core.config.agent_config import AgentConfig as _AgentConfig
        from backend.orchestration.autonomy import AutonomyController

        controller = self._controller
        agent_config = getattr(agent, 'config', None)

        controller.circuit_breaker_service.reset()

        if agent_config is None or not isinstance(agent_config, _AgentConfig):
            controller.autonomy_controller = None
            controller.safety_validator = None
            controller.task_validator = None
            controller.retry_service.reset_retry_metrics()
            return

        controller.autonomy_controller = AutonomyController(agent_config)
        controller.retry_service.reset_retry_metrics()

        self._initialize_safety_validator(agent)
        self._initialize_task_validator(agent)
        controller.circuit_breaker_service.configure(agent_config)

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    def _initialize_safety_validator(self, agent: Agent) -> None:
        controller = self._controller
        controller.safety_validator = None

        if (
            hasattr(agent.config, 'safety')
            and agent.config.safety.enable_mandatory_validation
        ):
            from backend.orchestration.safety_validator import SafetyValidator

            controller.safety_validator = SafetyValidator(agent.config.safety)
            logger.debug('SafetyValidator enabled for production safety')

    def _initialize_task_validator(self, agent: Agent) -> None:
        controller = self._controller
        controller.task_validator = None

        if (
            hasattr(agent.config, 'enable_completion_validation')
            and agent.config.enable_completion_validation
        ):
            from backend.validation.task_validator import (
                CompositeValidator,
                DiffValidator,
                FileExistsValidator,
                TestPassingValidator,
            )

            validators = [
                TestPassingValidator(),
                DiffValidator(),
                FileExistsValidator(),
            ]
            controller.task_validator = CompositeValidator(
                validators=validators,
                min_confidence=0.7,
                require_all_pass=False,
                fail_open_on_empty=False,
            )
            logger.debug('TaskValidator enabled for completion checking')

        controller._add_system_message()


__all__ = ['AutonomyService']
