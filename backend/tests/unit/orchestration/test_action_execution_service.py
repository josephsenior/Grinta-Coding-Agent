"""Tests for backend.orchestration.services.action_execution_service."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.orchestration.services.action_execution_service import ActionExecutionService
from backend.ledger import EventSource
from backend.ledger.action.agent import CondensationRequestAction
from backend.ledger.observation import ErrorObservation


def _make_context():
    """Create a mock OrchestrationContext."""
    ctx = MagicMock()
    ctx.event_stream = MagicMock()
    ctx.confirmation_service = None
    ctx.agent = MagicMock()
    ctx.state = MagicMock()
    ctx.tool_pipeline = None
    ctx.run_action = AsyncMock()
    ctx.telemetry_service = MagicMock()
    ctx.iteration_service = MagicMock()
    ctx.iteration_service.apply_dynamic_iterations = AsyncMock()
    ctx.register_action_context = MagicMock()
    return ctx


class TestActionExecutionServiceInit:
    def test_stores_context(self):
        ctx = _make_context()
        svc = ActionExecutionService(ctx)
        assert svc._context is ctx


class TestGetNextAction:
    @pytest.mark.asyncio
    async def test_returns_agent_step(self):
        ctx = _make_context()
        action = MagicMock()
        ctx.agent.step.return_value = action
        svc = ActionExecutionService(ctx)
        result = await svc.get_next_action()
        assert result is action
        assert action.source == EventSource.AGENT

    @pytest.mark.asyncio
    async def test_confirmation_service_takes_priority(self):
        ctx = _make_context()
        confirmed_action = MagicMock()
        ctx.confirmation_service = MagicMock()
        ctx.confirmation_service.get_next_action.return_value = confirmed_action
        mock_controller = MagicMock()
        mock_controller._replay_manager.should_replay.return_value = True
        ctx.get_controller.return_value = mock_controller
        svc = ActionExecutionService(ctx)
        result = await svc.get_next_action()
        assert result is confirmed_action
        ctx.agent.step.assert_not_called()

    @pytest.mark.asyncio
    async def test_live_run_prefers_astep_over_confirmation_sync_step(self):
        """When not in replay, confirmation must not route to agent.step (streaming uses astep)."""
        ctx = _make_context()
        ctx.confirmation_service = MagicMock()
        mock_controller = MagicMock()
        mock_controller._replay_manager.should_replay.return_value = False
        ctx.get_controller.return_value = mock_controller
        action = MagicMock()

        async def mock_astep(_state):
            return action

        ctx.agent.astep = mock_astep
        svc = ActionExecutionService(ctx)
        result = await svc.get_next_action()
        assert result is action
        ctx.confirmation_service.get_next_action.assert_not_called()
        ctx.agent.step.assert_not_called()

    @pytest.mark.asyncio
    async def test_astep_path_when_agent_has_async_step(self):
        """Uses agent.astep() when available and is coroutine."""
        ctx = _make_context()
        action = MagicMock()
        async def mock_astep(state):
            return action
        ctx.agent.astep = mock_astep
        ctx.agent.config = MagicMock()
        ctx.agent.config.llm_step_timeout_seconds = 30
        svc = ActionExecutionService(ctx)
        result = await svc.get_next_action()
        assert result is action
        assert action.source == EventSource.AGENT
        ctx.agent.step.assert_not_called()

    @pytest.mark.asyncio
    async def test_astep_timeout_raises(self):
        """astep timeout raises Timeout from llm.exceptions."""
        import asyncio
        from backend.inference.exceptions import Timeout

        ctx = _make_context()
        async def slow_astep(_state):
            await asyncio.sleep(10)
            return MagicMock()
        ctx.agent.astep = slow_astep
        ctx.agent.config = MagicMock()
        ctx.agent.config.llm_step_timeout_seconds = 0.01  # 10ms
        svc = ActionExecutionService(ctx)
        with pytest.raises(Timeout, match="timed out"):
            await svc.get_next_action()

    @pytest.mark.asyncio
    async def test_malformed_action_returns_none(self):
        from backend.core.errors import LLMMalformedActionError

        ctx = _make_context()
        ctx.agent.step.side_effect = LLMMalformedActionError("bad")
        svc = ActionExecutionService(ctx)
        result = await svc.get_next_action()
        assert result is None
        # Should have added an ErrorObservation
        ctx.event_stream.add_event.assert_called_once()
        args = ctx.event_stream.add_event.call_args[0]
        assert isinstance(args[0], ErrorObservation)
        assert args[1] == EventSource.AGENT

    @pytest.mark.asyncio
    async def test_no_action_error_returns_none(self):
        from backend.core.errors import LLMNoActionError

        ctx = _make_context()
        ctx.agent.step.side_effect = LLMNoActionError("no action")
        svc = ActionExecutionService(ctx)
        result = await svc.get_next_action()
        assert result is None

    @pytest.mark.asyncio
    async def test_response_error_returns_none(self):
        from backend.core.errors import LLMResponseError

        ctx = _make_context()
        ctx.agent.step.side_effect = LLMResponseError("bad response")
        svc = ActionExecutionService(ctx)
        result = await svc.get_next_action()
        assert result is None

    @pytest.mark.asyncio
    async def test_function_call_errors_return_none(self):
        from backend.core.errors import FunctionCallNotExistsError

        ctx = _make_context()
        ctx.agent.step.side_effect = FunctionCallNotExistsError("no func")
        svc = ActionExecutionService(ctx)
        result = await svc.get_next_action()
        assert result is None

    @pytest.mark.asyncio
    async def test_function_call_validation_error_returns_none(self):
        from backend.core.errors import FunctionCallValidationError

        ctx = _make_context()
        ctx.agent.step.side_effect = FunctionCallValidationError("invalid args")
        svc = ActionExecutionService(ctx)
        result = await svc.get_next_action()
        assert result is None
        ctx.event_stream.add_event.assert_called_once()
        args = ctx.event_stream.add_event.call_args[0]
        assert "Tool validation failed" in args[0].content

    @pytest.mark.asyncio
    async def test_api_connection_error_propagates(self):
        from backend.inference.exceptions import APIConnectionError

        ctx = _make_context()
        ctx.agent.step.side_effect = APIConnectionError("timeout")
        svc = ActionExecutionService(ctx)
        with pytest.raises(APIConnectionError):
            await svc.get_next_action()

    @pytest.mark.asyncio
    async def test_rate_limit_error_propagates(self):
        from backend.inference.exceptions import RateLimitError

        ctx = _make_context()
        ctx.agent.step.side_effect = RateLimitError("rate limited")
        svc = ActionExecutionService(ctx)
        with pytest.raises(RateLimitError):
            await svc.get_next_action()


class TestHandleContextWindowError:
    @pytest.mark.asyncio
    async def test_context_window_with_truncation_enabled(self):
        ctx = _make_context()
        ctx.agent.config.enable_history_truncation = True
        svc = ActionExecutionService(ctx)

        with patch(
            "backend.orchestration.services.action_execution_service.is_context_window_error",
            return_value=True,
        ):
            result = await svc._handle_context_window_error(
                Exception("context too long")
            )
        assert result is None
        # Should have added a CondensationRequestAction
        ctx.event_stream.add_event.assert_called_once()
        args = ctx.event_stream.add_event.call_args[0]
        assert isinstance(args[0], CondensationRequestAction)

    @pytest.mark.asyncio
    async def test_context_window_without_truncation_raises(self):
        from backend.core.errors import LLMContextWindowExceedError

        ctx = _make_context()
        ctx.agent.config.enable_history_truncation = False
        svc = ActionExecutionService(ctx)

        with patch(
            "backend.orchestration.services.action_execution_service.is_context_window_error",
            return_value=True,
        ):
            with pytest.raises(LLMContextWindowExceedError):
                await svc._handle_context_window_error(Exception("context too long"))

    @pytest.mark.asyncio
    async def test_non_context_window_error_reraises(self):
        ctx = _make_context()
        svc = ActionExecutionService(ctx)
        exc = Exception("not context window")

        with patch(
            "backend.orchestration.services.action_execution_service.is_context_window_error",
            return_value=False,
        ):
            with pytest.raises(Exception, match="not context window"):
                await svc._handle_context_window_error(exc)


class TestExecuteAction:
    @pytest.mark.asyncio
    async def test_non_runnable_action(self):
        ctx = _make_context()
        action = MagicMock()
        action.runnable = False
        svc = ActionExecutionService(ctx)

        with patch("backend.core.plugin.get_plugin_registry") as mock_reg:
            mock_reg.return_value.dispatch_action_pre = AsyncMock(return_value=action)
            await svc.execute_action(action)

        ctx.run_action.assert_called_once_with(action, None)

    @pytest.mark.asyncio
    async def test_runnable_with_pipeline(self):
        ctx = _make_context()
        action = MagicMock()
        action.runnable = True

        pipeline = MagicMock()
        tool_ctx = MagicMock()
        tool_ctx.blocked = False
        pipeline.create_context.return_value = tool_ctx
        pipeline.run_plan = AsyncMock()
        ctx.tool_pipeline = pipeline

        svc = ActionExecutionService(ctx)

        with patch("backend.core.plugin.get_plugin_registry") as mock_reg:
            mock_reg.return_value.dispatch_action_pre = AsyncMock(return_value=action)
            await svc.execute_action(action)

        pipeline.create_context.assert_called_once()
        pipeline.run_plan.assert_called_once_with(tool_ctx)
        ctx.run_action.assert_called_once_with(action, tool_ctx)

    @pytest.mark.asyncio
    async def test_blocked_action_not_run(self):
        ctx = _make_context()
        action = MagicMock()
        action.runnable = True

        pipeline = MagicMock()
        tool_ctx = MagicMock()
        tool_ctx.blocked = True
        pipeline.create_context.return_value = tool_ctx
        pipeline.run_plan = AsyncMock()
        ctx.tool_pipeline = pipeline

        svc = ActionExecutionService(ctx)

        with patch("backend.core.plugin.get_plugin_registry") as mock_reg:
            mock_reg.return_value.dispatch_action_pre = AsyncMock(return_value=action)
            await svc.execute_action(action)

        ctx.run_action.assert_not_called()
        ctx.telemetry_service.handle_blocked_invocation.assert_called_once()

    @pytest.mark.asyncio
    async def test_plugin_exception_swallowed(self):
        ctx = _make_context()
        action = MagicMock()
        action.runnable = False
        svc = ActionExecutionService(ctx)

        with patch("backend.core.plugin.get_plugin_registry") as mock_reg:
            mock_reg.return_value.dispatch_action_pre = AsyncMock(
                side_effect=RuntimeError("plugin crash")
            )
            # Should not raise — plugins must not break the pipeline
            await svc.execute_action(action)

        ctx.run_action.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_on_malformed_succeeds_on_second_attempt(self):
        """get_next_action retries on LLMMalformedActionError and succeeds."""
        from backend.core.errors import LLMMalformedActionError

        ctx = _make_context()
        action = MagicMock()
        ctx.agent.step.side_effect = [
            LLMMalformedActionError("bad first"),
            action,
        ]
        svc = ActionExecutionService(ctx)
        result = await svc.get_next_action()
        assert result is action
        assert ctx.agent.step.call_count == 2

    @pytest.mark.asyncio
    async def test_exhausted_retries_transitions_to_error_state(self):
        """When retries exhausted, transitions to ERROR state."""
        from backend.core.errors import LLMMalformedActionError
        from backend.core.schemas import AgentState

        ctx = _make_context()
        ctx.agent.step.side_effect = LLMMalformedActionError("bad")
        ctx.get_controller = MagicMock()
        ctx.get_controller.return_value.get_agent_state.return_value = AgentState.RUNNING
        ctx.get_controller.return_value.set_agent_state_to = AsyncMock()

        svc = ActionExecutionService(ctx)
        result = await svc.get_next_action()

        assert result is None
        ctx.get_controller.return_value.set_agent_state_to.assert_awaited_once_with(
            AgentState.ERROR
        )
