"""Accessor mixins for SessionOrchestrator."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.orchestration.agent import Agent
    from backend.orchestration.conversation_stats import ConversationStats
    from backend.orchestration.state.state import State
    from backend.ledger import EventStream


class SessionOrchestratorAccessorsMixin:
    @property
    def id(self) -> str | None:
        return self.config.sid or (
            self.config.event_stream.sid if self.config.event_stream else None
        )

    @property
    def agent(self) -> Agent:
        return self.config.agent

    @property
    def event_stream(self) -> EventStream:
        return self.config.event_stream

    @property
    def state(self) -> State:
        return self.state_tracker.state

    @property
    def conversation_stats(self) -> ConversationStats:
        return self.config.conversation_stats

    @property
    def task_id(self) -> str | None:
        return self.id

    @property
    def action_service(self):
        return self.services.action

    @property
    def pending_action_service(self):
        return self.services.pending_action

    @property
    def autonomy_service(self):
        return self.services.autonomy

    @property
    def iteration_service(self):
        return self.services.iteration

    @property
    def lifecycle_service(self):
        return self.services.lifecycle

    @property
    def state_service(self):
        return self.services.state

    @property
    def retry_service(self):
        return self.services.retry

    @property
    def recovery_service(self):
        return self.services.recovery

    @property
    def stuck_service(self):
        return self.services.stuck

    @property
    def circuit_breaker_service(self):
        return self.services.circuit_breaker

    @property
    def observation_service(self):
        return self.services.observation

    @property
    def task_validation_service(self):
        return self.services.task_validation

    @property
    def iteration_guard(self):
        return self.services.iteration_guard

    @property
    def step_guard(self):
        return self.services.step_guard

    @property
    def step_prerequisites(self):
        return self.services.step_prerequisites

    @property
    def exception_handler(self):
        return self.services.exception_handler

    @property
    def event_router(self):
        return self.services.event_router

    @property
    def step_decision(self):
        return self.services.step_decision

    @property
    def action_execution(self):
        return self.services.action_execution