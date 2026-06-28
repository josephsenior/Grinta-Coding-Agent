# pyright: reportAttributeAccessIssue=false, reportMissingParameterType=false, reportPrivateUsage=false, reportUnknownArgumentType=false, reportUnknownLambdaType=false, reportUnknownMemberType=false, reportUnknownParameterType=false, reportUnknownVariableType=false
# mypy: disable-error-code="assignment,attr-defined,method-assign,misc"
"""Tests for SessionOrchestrator — the main agent orchestration controller."""
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


class TestHandleBlockedInvocation:
    """Blocked tool pipeline paths and ErrorObservation shaping."""

    @pytest.fixture(autouse=True)
    def _setup(self, ctrl):
        self.ctrl = ctrl


    def test_emits_agent_only_error_when_block_agent_only_metadata_set(self):
        from backend.orchestration.tool_pipeline import ToolInvocationContext

        mock_action = MagicMock()
        state = MagicMock()
        ctx = ToolInvocationContext(
            controller=self.ctrl,
            action=mock_action,
            state=state,
            metadata={'block_agent_only': True},
        )
        ctx.block_reason = '[FILE_STATE_GUARD] read first'

        with (
            patch(
                'backend.orchestration.telemetry.tool_telemetry.ToolTelemetry.get_instance'
            ) as mock_tm,
            patch('backend.ledger.observation_cause.attach_observation_cause'),
            patch(
                'backend.orchestration.mixins.lifecycle_mixin.ErrorObservation'
            ) as mock_err_cls,
        ):
            mock_obs = MagicMock()
            mock_err_cls.return_value = mock_obs
            mock_tm.return_value.on_blocked = MagicMock()
            self.ctrl.handle_blocked_invocation(mock_action, ctx)

        mock_err_cls.assert_called_once_with(
            content='[FILE_STATE_GUARD] read first',
            error_id='TOOL_PIPELINE_BLOCKED',
            agent_only=True,
        )
        self.ctrl.event_stream.add_event.assert_called_once_with(
            mock_obs, EventSource.ENVIRONMENT
        )

    def test_emits_user_visible_error_when_agent_only_not_set(self):
        from backend.orchestration.tool_pipeline import ToolInvocationContext

        mock_action = MagicMock()
        state = MagicMock()
        ctx = ToolInvocationContext(
            controller=self.ctrl,
            action=mock_action,
            state=state,
        )
        ctx.block_reason = 'safety_validator_blocked'

        with (
            patch(
                'backend.orchestration.telemetry.tool_telemetry.ToolTelemetry.get_instance'
            ) as mock_tm,
            patch('backend.ledger.observation_cause.attach_observation_cause'),
            patch(
                'backend.orchestration.mixins.lifecycle_mixin.ErrorObservation'
            ) as mock_err_cls,
        ):
            mock_obs = MagicMock()
            mock_err_cls.return_value = mock_obs
            mock_tm.return_value.on_blocked = MagicMock()
            self.ctrl.handle_blocked_invocation(mock_action, ctx)

        mock_err_cls.assert_called_once_with(
            content='safety_validator_blocked',
            error_id='TOOL_PIPELINE_BLOCKED',
            agent_only=False,
        )


# ── Properties ───────────────────────────────────────────────────────




class TestControlFlags:
    """Test _run_control_flags_safely."""

    @pytest.fixture(autouse=True)
    def _setup(self, ctrl):
        self.ctrl = ctrl


    @pytest.mark.asyncio
    async def test_run_control_flags_success(self):
        self.ctrl.services.iteration_guard.run_control_flags = AsyncMock()
        result = await self.ctrl._run_control_flags_safely()
        assert result

    @pytest.mark.asyncio
    async def test_run_control_flags_exception(self):
        self.ctrl.services.iteration_guard.run_control_flags = AsyncMock(
            side_effect=RuntimeError('boom')
        )
        self.ctrl.services.recovery.react_to_exception = AsyncMock()

        result = await self.ctrl._run_control_flags_safely()

        assert not result
        self.ctrl.services.recovery.react_to_exception.assert_awaited_once()


# ── Event handling ───────────────────────────────────────────────────


