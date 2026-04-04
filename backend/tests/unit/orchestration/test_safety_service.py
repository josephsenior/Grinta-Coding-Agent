"""Tests for backend.orchestration.services.safety_service."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.ledger.action import (
    ActionConfirmationStatus,
    ActionSecurityRisk,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
)
from backend.orchestration.services.safety_service import SafetyService


def _make_context(**overrides) -> MagicMock:
    ctx = MagicMock()
    ctx.security_analyzer = overrides.get('security_analyzer')
    ctx.autonomy_controller = overrides.get('autonomy_controller')
    ctx.confirmation_mode = overrides.get('confirmation_mode', False)
    ctx.pending_action = overrides.get('pending_action')
    ctx.emit_event = MagicMock()
    ctx.clear_pending_action = MagicMock()
    return ctx


def _as_action(payload: SimpleNamespace) -> Any:
    return cast(Any, payload)


# ── action_requires_confirmation ─────────────────────────────────────


class TestActionRequiresConfirmation:
    def test_cmd_run_requires_confirmation(self):
        svc = SafetyService(_make_context())
        action = CmdRunAction(command='echo hi')
        assert svc.action_requires_confirmation(action) is True

    def test_file_edit_requires_confirmation(self):
        svc = SafetyService(_make_context())
        action = FileEditAction(path='/tmp/x.py', content='x')
        assert svc.action_requires_confirmation(action) is True

    def test_file_read_requires_confirmation(self):
        svc = SafetyService(_make_context())
        action = FileReadAction(path='/tmp/x.py')
        assert svc.action_requires_confirmation(action) is True

    def test_generic_action_does_not_require_confirmation(self):
        svc = SafetyService(_make_context())
        action = _as_action(SimpleNamespace())  # not a confirmation type
        assert svc.action_requires_confirmation(action) is False


# ── evaluate_security_risk ───────────────────────────────────────────


class TestEvaluateSecurityRisk:
    def test_high_risk(self):
        ctx = _make_context(security_analyzer=MagicMock())
        svc = SafetyService(ctx)
        action = _as_action(SimpleNamespace(security_risk=ActionSecurityRisk.HIGH))
        is_high, is_ask = svc.evaluate_security_risk(action)
        assert is_high is True
        assert is_ask is False

    def test_unknown_risk_no_analyzer(self):
        ctx = _make_context(security_analyzer=None)
        svc = SafetyService(ctx)
        action = _as_action(SimpleNamespace(security_risk=ActionSecurityRisk.UNKNOWN))
        is_high, is_ask = svc.evaluate_security_risk(action)
        assert is_high is False
        assert is_ask is True

    def test_unknown_risk_with_analyzer(self):
        ctx = _make_context(security_analyzer=MagicMock())
        svc = SafetyService(ctx)
        action = _as_action(SimpleNamespace(security_risk=ActionSecurityRisk.UNKNOWN))
        is_high, is_ask = svc.evaluate_security_risk(action)
        assert is_high is False
        assert is_ask is False  # analyzer present → don't ask for every action

    def test_low_risk(self):
        ctx = _make_context()
        svc = SafetyService(ctx)
        action = _as_action(SimpleNamespace(security_risk=ActionSecurityRisk.LOW))
        is_high, is_ask = svc.evaluate_security_risk(action)
        assert is_high is False
        assert is_ask is False

    def test_no_security_risk_attr_defaults_unknown(self):
        ctx = _make_context(security_analyzer=None)
        svc = SafetyService(ctx)
        action = _as_action(SimpleNamespace())  # no security_risk attribute
        is_high, is_ask = svc.evaluate_security_risk(action)
        assert is_high is False
        assert is_ask is True  # getattr returns UNKNOWN, no analyzer


# ── analyze_security (async) ─────────────────────────────────────────


class TestAnalyzeSecurity:
    @pytest.mark.asyncio
    async def test_no_analyzer_sets_unknown(self):
        ctx = _make_context(security_analyzer=None)
        svc = SafetyService(ctx)
        action = _as_action(SimpleNamespace(security_risk=ActionSecurityRisk.LOW))
        await svc.analyze_security(action)
        assert action.security_risk == ActionSecurityRisk.UNKNOWN

    @pytest.mark.asyncio
    async def test_with_analyzer_sets_risk(self):
        analyzer = AsyncMock()
        analyzer.security_risk.return_value = ActionSecurityRisk.HIGH
        ctx = _make_context(security_analyzer=analyzer)
        svc = SafetyService(ctx)
        action = _as_action(SimpleNamespace(security_risk=ActionSecurityRisk.LOW))
        await svc.analyze_security(action)
        assert action.security_risk == ActionSecurityRisk.HIGH

    @pytest.mark.asyncio
    async def test_no_security_risk_attr_skips(self):
        """Action without security_risk attr is unmodified."""
        ctx = _make_context(security_analyzer=None)
        svc = SafetyService(ctx)
        action = _as_action(SimpleNamespace())
        await svc.analyze_security(action)
        assert not hasattr(action, 'security_risk')


# ── apply_confirmation_state ─────────────────────────────────────────


class TestApplyConfirmationState:
    def test_autonomy_requests_confirmation(self):
        autonomy = MagicMock()
        autonomy.should_request_confirmation.return_value = True
        controller = MagicMock()
        ctx = _make_context(autonomy_controller=autonomy)
        ctx.get_controller.return_value = controller
        svc = SafetyService(ctx)
        action = _as_action(SimpleNamespace(confirmation_state=None))
        svc.apply_confirmation_state(
            action, is_high_security_risk=True, is_ask_for_every_action=False
        )
        assert (
            action.confirmation_state == ActionConfirmationStatus.AWAITING_CONFIRMATION
        )

    def test_confirmation_when_autonomy_requests(self):
        autonomy = MagicMock()
        autonomy.should_request_confirmation.return_value = True
        controller = MagicMock()
        ctx = _make_context(autonomy_controller=autonomy)
        ctx.get_controller.return_value = controller
        svc = SafetyService(ctx)
        action = _as_action(SimpleNamespace(confirmation_state=None))
        svc.apply_confirmation_state(
            action, is_high_security_risk=True, is_ask_for_every_action=False
        )
        assert (
            action.confirmation_state == ActionConfirmationStatus.AWAITING_CONFIRMATION
        )

    def test_autonomous_no_confirmation(self):
        autonomy = MagicMock()
        autonomy.should_request_confirmation.return_value = False
        controller = MagicMock()
        ctx = _make_context(autonomy_controller=autonomy)
        ctx.get_controller.return_value = controller
        svc = SafetyService(ctx)
        action = _as_action(SimpleNamespace(confirmation_state=None))
        svc.apply_confirmation_state(
            action, is_high_security_risk=True, is_ask_for_every_action=True
        )
        assert action.confirmation_state is None  # untouched


# ── finalize_pending_action ──────────────────────────────────────────


class TestFinalizePendingAction:
    def test_confirmed(self):
        action = _as_action(
            SimpleNamespace(thought='thinking...', confirmation_state=None, _id=42)
        )
        ctx = _make_context(pending_action=action)
        svc = SafetyService(ctx)
        svc.finalize_pending_action(confirmed=True)
        assert action.confirmation_state == ActionConfirmationStatus.CONFIRMED
        assert action.thought == ''
        assert action._id is None
        ctx.emit_event.assert_called_once()
        ctx.clear_pending_action.assert_called_once()

    def test_rejected(self):
        action = _as_action(
            SimpleNamespace(thought='thinking...', confirmation_state=None, _id=42)
        )
        ctx = _make_context(pending_action=action)
        svc = SafetyService(ctx)
        svc.finalize_pending_action(confirmed=False)
        assert action.confirmation_state == ActionConfirmationStatus.REJECTED

    def test_no_pending_action_is_noop(self):
        ctx = _make_context(pending_action=None)
        svc = SafetyService(ctx)
        svc.finalize_pending_action(confirmed=True)
        ctx.emit_event.assert_not_called()
