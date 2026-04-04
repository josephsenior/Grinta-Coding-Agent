"""Tests for backend.orchestration.services.orchestration_context.OrchestrationContext."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

from backend.orchestration.services.orchestration_context import OrchestrationContext

# ── helpers ──────────────────────────────────────────────────────────


def _make_ctx(**ctrl_attrs) -> OrchestrationContext:
    controller = MagicMock()
    for k, v in ctrl_attrs.items():
        setattr(controller, k, v)
    return OrchestrationContext(_controller=controller)


# ── property proxies ─────────────────────────────────────────────────


class TestOrchestrationContextProperties:
    def test_id(self):
        ctx = _make_ctx(id='test-id')
        assert ctx.id == 'test-id'

    def test_agent(self):
        agent = MagicMock()
        ctx = _make_ctx(agent=agent)
        assert ctx.agent is agent

    def test_agent_config(self):
        agent = MagicMock()
        agent.config = MagicMock()
        ctx = _make_ctx(agent=agent)
        assert ctx.agent_config is agent.config

    def test_agent_config_none_when_no_agent(self):
        controller = MagicMock(spec=[])  # no 'agent' attr
        ctx = OrchestrationContext(_controller=controller)
        assert ctx.agent_config is None

    def test_state(self):
        state = MagicMock()
        ctx = _make_ctx(state=state)
        assert ctx.state is state

    def test_headless_mode(self):
        ctx = _make_ctx(headless_mode=True)
        assert ctx.headless_mode is True

    def test_agent_name_property(self):
        agent = MagicMock()
        agent.name = 'TestBot'
        ctx = _make_ctx(agent=agent)
        assert ctx.controller_name == 'TestBot'

    def test_unknown_agent_name_without_agent(self):
        controller = MagicMock(spec=[])
        ctx = OrchestrationContext(_controller=controller)
        assert ctx.controller_name == 'unknown'

    def test_event_stream(self):
        es = MagicMock()
        ctx = _make_ctx(event_stream=es)
        assert ctx.event_stream is es

    def test_confirmation_mode(self):
        ctx = _make_ctx(confirmation_mode=True)
        assert ctx.confirmation_mode is True

    def test_autonomy_controller(self):
        ac = MagicMock()
        ctx = _make_ctx(autonomy_controller=ac)
        assert ctx.autonomy_controller is ac


# ── pending_action ───────────────────────────────────────────────────


class TestPendingAction:
    def test_from_pending_action_service(self):
        svc = MagicMock()
        svc.get.return_value = 'action_obj'
        services = MagicMock()
        services.pending_action = svc
        ctx = _make_ctx(services=services)
        assert ctx.pending_action == 'action_obj'

    def test_fallback_to_action_service(self):
        action_svc = MagicMock()
        action_svc.get_pending_action.return_value = 'action_obj'
        controller = MagicMock(spec=['action_service'])
        controller.action_service = action_svc
        ctx = OrchestrationContext(_controller=controller)
        assert ctx.pending_action == 'action_obj'


class TestOperationPipeline:
    def test_prefers_canonical_operation_pipeline(self):
        pipeline = MagicMock()
        ctx = _make_ctx(operation_pipeline=pipeline)
        assert ctx.operation_pipeline is pipeline

    def test_falls_back_to_tool_pipeline(self):
        pipeline = MagicMock()
        controller = MagicMock(spec=['tool_pipeline'])
        controller.tool_pipeline = pipeline
        ctx = OrchestrationContext(_controller=controller)
        assert ctx.operation_pipeline is pipeline

    def test_initialize_operation_pipeline_alias(self):
        controller = MagicMock()
        ctx = OrchestrationContext(_controller=controller)
        pipeline = ctx.initialize_operation_pipeline([])
        assert pipeline is controller.operation_pipeline
        assert controller.tool_pipeline is pipeline


# ── set_pending_action / clear ───────────────────────────────────────


class TestSetPendingAction:
    def test_set_via_action_service(self):
        action_svc = MagicMock()
        ctx = _make_ctx(action_service=action_svc)
        ctx.set_pending_action(cast(Any, 'new_action'))
        action_svc.set_pending_action.assert_called_once_with('new_action')

    def test_clear(self):
        action_svc = MagicMock()
        ctx = _make_ctx(action_service=action_svc)
        ctx.clear_pending_action()
        action_svc.set_pending_action.assert_called_with(None)


# ── emit_event ───────────────────────────────────────────────────────


class TestEmitEvent:
    def test_emit(self):
        es = MagicMock()
        ctx = _make_ctx(event_stream=es)
        ctx.emit_event(cast(Any, 'event'), cast(Any, 'source'))
        es.add_event.assert_called_once_with('event', 'source')


# ── pop_action_context ───────────────────────────────────────────────


class TestPopActionContext:
    def test_found(self):
        mapping = {42: 'ctx_obj'}
        ctx = _make_ctx(_action_contexts_by_event_id=mapping)
        assert ctx.pop_action_context(42) == 'ctx_obj'
        assert 42 not in mapping

    def test_missing(self):
        ctx = _make_ctx(_action_contexts_by_event_id={})
        assert ctx.pop_action_context(99) is None

    def test_no_mapping(self):
        controller = MagicMock(spec=[])
        ctx = OrchestrationContext(_controller=controller)
        assert ctx.pop_action_context(1) is None


# ── get_controller ───────────────────────────────────────────────────


class TestGetController:
    def test_returns_controller(self):
        controller = MagicMock()
        ctx = OrchestrationContext(_controller=controller)
        assert ctx.get_controller() is controller
