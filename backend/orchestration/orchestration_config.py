"""Controller configuration and service container types.

Extracted from :mod:`backend.orchestration.session_orchestrator` to keep module
sizes within the repository guideline (~400 LOC).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from backend.core.config import AgentConfig, LLMConfig
    from backend.ledger.event import Event
    from backend.orchestration.conversation_stats import ConversationStats
    from backend.orchestration.session_orchestrator import SessionOrchestrator
    from backend.persistence.files import FileStore
    from backend.security.analyzer import SecurityAnalyzer

from backend.core.constants import DEFAULT_PENDING_ACTION_TIMEOUT
from backend.ledger import EventStream
from backend.orchestration.agent import Agent
from backend.orchestration.services import (
    ActionExecutionService,
    ActionService,
    AutonomyService,
    CircuitBreakerService,
    ConfirmationService,
    EventRouterService,
    ExceptionHandlerService,
    IterationGuardService,
    IterationService,
    LifecycleService,
    ObservationService,
    OrchestrationContext,
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
)
from backend.orchestration.state.state import State


@dataclass
class OrchestrationConfig:
    """Consolidated configuration for SessionOrchestrator."""

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
    delegate_task_blackboard_enabled: bool = False
    blackboard: Any = None  # Shared blackboard for worker agents when delegate_task_blackboard_enabled
    pending_action_timeout: float = DEFAULT_PENDING_ACTION_TIMEOUT


class OrchestrationServices:
    """Container for SessionOrchestrator support services."""

    def __init__(self, controller: SessionOrchestrator):
        self.lifecycle = LifecycleService(controller)
        self.autonomy = AutonomyService(controller)
        self.context = OrchestrationContext(controller)
        self.iteration = IterationService(self.context)
        self.iteration_guard = IterationGuardService(self.context)
        self.step_guard = StepGuardService(self.context)
        self.step_prerequisites = StepPrerequisiteService(self.context)
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
        self.retry = RetryService(self.context)
        self.recovery = RecoveryService(self.context)
        self.circuit_breaker = CircuitBreakerService(self.context)
        self.stuck = StuckDetectionService(controller)
        self.task_validation = TaskValidationService(self.context)
        self.event_router = EventRouterService(controller)
        self.step_decision = StepDecisionService(controller)
        self.exception_handler = ExceptionHandlerService(controller)
