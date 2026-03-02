"""Unit tests for backend.controller.services.step_prerequisite_service."""

from __future__ import annotations

from unittest.mock import MagicMock
from typing import cast

from backend.controller.services.controller_context import ControllerContext


from backend.controller.services.step_prerequisite_service import (
    StepPrerequisiteService,
)
from backend.core.schemas import AgentState


class _FakeContext:
    def __init__(self, agent_state: AgentState, pending_action=None):
        self._agent_state = agent_state
        self.pending_action = pending_action
        self._ctrl = MagicMock()
        self._ctrl.get_agent_state.return_value = agent_state
        self._ctrl.log = MagicMock()

    def get_controller(self):
        return self._ctrl


class TestStepPrerequisiteService:
    def test_can_step_when_running_no_pending(self):
        ctx = _FakeContext(AgentState.RUNNING)
        svc = StepPrerequisiteService(cast(ControllerContext, ctx))
        assert svc.can_step() is True

    def test_cannot_step_when_paused(self):
        ctx = _FakeContext(AgentState.PAUSED)
        svc = StepPrerequisiteService(cast(ControllerContext, ctx))
        assert svc.can_step() is False

    def test_cannot_step_when_stopped(self):
        ctx = _FakeContext(AgentState.STOPPED)
        svc = StepPrerequisiteService(cast(ControllerContext, ctx))
        assert svc.can_step() is False

    def test_cannot_step_when_error(self):
        ctx = _FakeContext(AgentState.ERROR)
        svc = StepPrerequisiteService(cast(ControllerContext, ctx))
        assert svc.can_step() is False

    def test_cannot_step_when_finished(self):
        ctx = _FakeContext(AgentState.FINISHED)
        svc = StepPrerequisiteService(cast(ControllerContext, ctx))
        assert svc.can_step() is False

    def test_cannot_step_when_pending_action(self):
        pending = MagicMock()
        pending.id = 42
        ctx = _FakeContext(AgentState.RUNNING, pending_action=pending)
        svc = StepPrerequisiteService(cast(ControllerContext, ctx))
        assert svc.can_step() is False

    def test_can_step_no_pending_running(self):
        ctx = _FakeContext(AgentState.RUNNING, pending_action=None)
        svc = StepPrerequisiteService(cast(ControllerContext, ctx))
        assert svc.can_step() is True
