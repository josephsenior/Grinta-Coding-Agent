"""Controller configuration and service container types.

Extracted from :mod:`backend.controller.agent_controller` to keep module
sizes within the repository guideline (~400 LOC).
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.controller.agent_controller import AgentController
    from backend.core.config import AgentConfig, LLMConfig
    from backend.events.event import Event
    from backend.security.analyzer import SecurityAnalyzer
    from backend.server.services.conversation_stats import ConversationStats
    from backend.storage.files import FileStore

from backend.controller.agent import Agent
from backend.controller.services import (
    ActionExecutionService,
    ActionService,
    AutonomyService,
    BudgetGuardService,
    CircuitBreakerService,
    ConfirmationService,
    ControllerContext,
    EventRouterService,
    ExceptionHandlerService,
    IterationGuardService,
    IterationService,
    LifecycleService,
    MetricsService,
    ObservationService,
    PendingActionService,
    RecoveryService,
    RetryService,
    SafetyService,
    StateTransitionService,
    StepDecisionService,
    StepGuardService,
    StepPrerequisiteService,
    StuckDetectionService,
    TaskValidationService,
    TelemetryService,
)
from backend.controller.state.state import State
from backend.events import EventStream


@dataclass
class ControllerConfig:
    """Consolidated configuration for AgentController."""

    agent: Agent
    event_stream: EventStream
    conversation_stats: ConversationStats
    iteration_delta: int
    budget_per_task_delta: float | None = None
    agent_to_llm_config: dict[str, LLMConfig] | None = None
    agent_configs: dict[str, AgentConfig] | None = None
    sid: str | None = None
    file_store: FileStore | None = None
    user_id: str | None = None
    confirmation_mode: bool = False
    initial_state: State | None = None
    headless_mode: bool = True
    status_callback: Callable | None = None
    replay_events: list[Event] | None = None
    security_analyzer: SecurityAnalyzer | None = None


class ControllerServices:
    """Container for AgentController support services."""

    def __init__(self, controller: AgentController):
        self.lifecycle = LifecycleService(controller)
        self.autonomy = AutonomyService(controller)
        self.context = ControllerContext(controller)
        self.iteration = IterationService(self.context)
        self.iteration_guard = IterationGuardService(self.context)
        self.step_guard = StepGuardService(self.context)
        self.step_prerequisites = StepPrerequisiteService(self.context)
        self.budget_guard = BudgetGuardService(self.context)
        self.safety = SafetyService(self.context)
        self.pending_action = PendingActionService(
            self.context, controller.PENDING_ACTION_TIMEOUT
        )
        self.observation = ObservationService(self.context, self.pending_action)
        self.confirmation = ConfirmationService(self.context, self.safety)
        self.action = ActionService(
            self.context,
            self.pending_action,
            self.confirmation,
        )
        self.action_execution = ActionExecutionService(self.context)
        self.state = StateTransitionService(self.context)
        self.telemetry = TelemetryService(self.context)
        self.metrics = MetricsService(self.context)
        self.retry = RetryService(self.context)
        self.recovery = RecoveryService(self.context, self.retry)
        self.circuit_breaker = CircuitBreakerService(self.context)
        self.stuck = StuckDetectionService(controller)
        self.task_validation = TaskValidationService(self.context)
        self.event_router = EventRouterService(controller)
        self.step_decision = StepDecisionService(controller)
        self.exception_handler = ExceptionHandlerService(controller)
