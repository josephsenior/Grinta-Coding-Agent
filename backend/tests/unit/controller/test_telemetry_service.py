"""Tests for backend.controller.services.telemetry_service."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from typing import cast


from backend.controller.services.telemetry_service import TelemetryService
from backend.events.action.action import Action


def _make_context(**overrides) -> MagicMock:
    controller = MagicMock()
    ctx = MagicMock()
    ctx.get_controller.return_value = controller
    ctx.agent_config = overrides.get("agent_config")
    return ctx


# ── initialize_tool_pipeline ─────────────────────────────────────────


class TestInitializeToolPipeline:
    def test_creates_default_pipeline(self):
        ctx = _make_context()
        svc = TelemetryService(ctx)
        svc.initialize_tool_pipeline()
        ctx.initialize_tool_pipeline.assert_called_once()
        middlewares = ctx.initialize_tool_pipeline.call_args[0][0]
        assert (
            len(middlewares) >= 5
        )  # at least safety, idempotency, cb, cost, rollback, ...

    def test_includes_reflection_middleware_when_enabled(self):
        config = SimpleNamespace(
            enable_planning_middleware=False,
            enable_reflection_middleware=True,
        )
        ctx = _make_context(agent_config=config)
        svc = TelemetryService(ctx)
        svc.initialize_tool_pipeline()
        middlewares = ctx.initialize_tool_pipeline.call_args[0][0]
        class_names = [type(m).__name__ for m in middlewares]
        assert "ReflectionMiddleware" in class_names

    def test_no_optional_middleware_when_disabled(self):
        config = SimpleNamespace(
            enable_planning_middleware=False,
            enable_reflection_middleware=False,
        )
        ctx = _make_context(agent_config=config)
        svc = TelemetryService(ctx)
        svc.initialize_tool_pipeline()
        middlewares = ctx.initialize_tool_pipeline.call_args[0][0]
        class_names = [type(m).__name__ for m in middlewares]
        assert "PlanningMiddleware" not in class_names
        assert "ReflectionMiddleware" not in class_names


# ── handle_blocked_invocation ────────────────────────────────────────


class TestHandleBlockedInvocation:
    def test_emits_error_observation(self):
        ctx = _make_context()
        svc = TelemetryService(ctx)
        action = cast(Action, SimpleNamespace(id=1))
        invocation_ctx = MagicMock()
        invocation_ctx.block_reason = "Too dangerous"
        invocation_ctx.metadata = {}
        with patch("backend.controller.tool_telemetry.ToolTelemetry") as MockTT:
            MockTT.get_instance.return_value = MagicMock()
            svc.handle_blocked_invocation(action, invocation_ctx)
        ctx.emit_event.assert_called_once()
        obs = ctx.emit_event.call_args[0][0]
        assert "Too dangerous" in obs.content
        ctx.clear_pending_action.assert_called_once()

    def test_handled_metadata_skips_error_observation(self):
        ctx = _make_context()
        svc = TelemetryService(ctx)
        action = cast(Action, SimpleNamespace(id=1))
        invocation_ctx = MagicMock()
        invocation_ctx.block_reason = "blocked"
        invocation_ctx.metadata = {"handled": True}
        with patch("backend.controller.tool_telemetry.ToolTelemetry") as MockTT:
            MockTT.get_instance.return_value = MagicMock()
            svc.handle_blocked_invocation(action, invocation_ctx)
        ctx.emit_event.assert_not_called()

    def test_telemetry_failure_does_not_propagate(self):
        ctx = _make_context()
        svc = TelemetryService(ctx)
        action = cast(Action, SimpleNamespace(id=1))
        invocation_ctx = MagicMock()
        invocation_ctx.block_reason = "boom"
        invocation_ctx.metadata = {}
        with patch("backend.controller.tool_telemetry.ToolTelemetry") as MockTT:
            MockTT.get_instance.return_value.on_blocked.side_effect = RuntimeError(
                "telemetry fail"
            )
            # Should NOT raise
            svc.handle_blocked_invocation(action, invocation_ctx)
        ctx.emit_event.assert_called_once()
