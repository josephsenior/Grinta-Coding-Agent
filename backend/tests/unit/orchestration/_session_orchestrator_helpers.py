# pyright: reportAttributeAccessIssue=false, reportMissingParameterType=false, reportPrivateUsage=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false
# mypy: disable-error-code="assignment,attr-defined,method-assign,misc"
"""Shared helpers for SessionOrchestrator unit tests."""
# pylint: disable=protected-access,too-many-lines

import asyncio
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from backend.core.enums import LifecyclePhase
from backend.core.schemas import AgentState
from backend.ledger import EventSource
from backend.ledger.action import MessageAction
from backend.orchestration.action_scheduler import ActionScheduler
from backend.orchestration.orchestration_config import OrchestrationConfig
from backend.orchestration.session_orchestrator import (
    ERROR_ACTION_NOT_EXECUTED_ERROR,
    ERROR_ACTION_NOT_EXECUTED_STOPPED,
    ERROR_ACTION_NOT_EXECUTED_STOPPED_ID,
    TRAFFIC_CONTROL_REMINDER,
    SessionOrchestrator,
)

def _noop_init(self: SessionOrchestrator, *args: object, **kwargs: object) -> None:
    del self, args, kwargs


def _make_controller() -> SessionOrchestrator:
    """Create an SessionOrchestrator with fully mocked internals (no real __init__)."""
    with patch.object(SessionOrchestrator, '__init__', _noop_init):
        ctrl = SessionOrchestrator.__new__(SessionOrchestrator)

    # Config
    ctrl.config = MagicMock()
    ctrl.config.sid = 'test-sid'
    ctrl.config.event_stream = MagicMock()
    ctrl.config.event_stream.sid = 'test-sid'
    ctrl.config.agent = MagicMock()
    ctrl.config.conversation_stats = MagicMock()

    # Services container
    ctrl.services = MagicMock()
    ctrl.services.pending_action.barrier_wait_budget_seconds = MagicMock(
        return_value=30.0
    )
    ctrl.services.pending_action.has_outstanding = MagicMock(return_value=False)
    # Provide explicit async mocks for methods awaited in normal flows:
    ctrl.services.step_guard.ensure_can_step = AsyncMock(return_value=True)
    ctrl.services.exception_handler.handle_step_exception = AsyncMock()
    ctrl.services.step_guard.ensure_can_step = AsyncMock(return_value=True)
    ctrl.services.exception_handler.handle_step_exception = AsyncMock()

    # State tracker
    ctrl.state_tracker = MagicMock()
    ctrl.state_tracker.state = MagicMock()
    ctrl.state_tracker.state.agent_state = AgentState.RUNNING
    ctrl.state_tracker.state.start_id = 0
    ctrl.state_tracker.state.history = []

    # Rate governor / memory
    ctrl.rate_governor = MagicMock()
    ctrl.memory_pressure = MagicMock()
    ctrl.memory_pressure._min_history_events = 0

    # Action contexts
    ctrl._action_contexts_by_event_id = {}
    ctrl._action_contexts_by_object = {}

    # Lifecycle
    ctrl._lifecycle = LifecyclePhase.ACTIVE
    ctrl._cached_first_user_message = None
    ctrl._step_task = None
    # _step_lock is a property with lazy initialization — set the backing
    # attribute directly so tests can inject a pre-configured lock.
    ctrl._step_lock_instance = asyncio.Lock()
    ctrl._step_lock_loop = None
    ctrl._step_request_count = 0
    ctrl._main_loop = None
    ctrl._draining_batch = False

    return ctrl

