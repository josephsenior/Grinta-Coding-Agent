"""Tests for backend.runtime.security_enforcement module.

Targets the 17.4% (38 missed lines) coverage gap.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.runtime.security_enforcement import SecurityEnforcementMixin


class _FakeRuntime(SecurityEnforcementMixin):
    """Concrete host for the mixin."""

    def __init__(self, analyzer=None, enforce=False, block_high=False):
        self.security_analyzer = analyzer
        self.config = MagicMock()
        self.config.security.enforce_security = enforce
        self.config.security.block_high_risk = block_high


# ------------------------------------------------------------------
# _check_action_confirmation
# ------------------------------------------------------------------
class TestCheckActionConfirmation:
    def test_no_confirmation_state(self):
        rt = _FakeRuntime()
        action = MagicMock(spec=[])  # no confirmation_state attr
        assert rt._check_action_confirmation(action) is None

    def test_awaiting_confirmation_non_file_edit(self):
        from backend.events.action import ActionConfirmationStatus

        rt = _FakeRuntime()
        action = MagicMock()
        action.confirmation_state = ActionConfirmationStatus.AWAITING_CONFIRMATION
        result = rt._check_action_confirmation(action)
        # Non-FileEditAction should return NullObservation
        assert result is not None
        assert result.__class__.__name__ == "NullObservation"

    def test_awaiting_confirmation_file_edit_allowed(self):
        from backend.events.action import ActionConfirmationStatus, FileEditAction

        rt = _FakeRuntime()
        action = MagicMock(spec=FileEditAction)
        action.confirmation_state = ActionConfirmationStatus.AWAITING_CONFIRMATION
        result = rt._check_action_confirmation(action)
        # FileEditAction is allowed through for dry-run preview
        assert result is None

    def test_rejected_returns_user_reject(self):
        from backend.events.action import ActionConfirmationStatus

        rt = _FakeRuntime()
        action = MagicMock()
        action.confirmation_state = ActionConfirmationStatus.REJECTED
        result = rt._check_action_confirmation(action)
        assert result is not None
        assert result.__class__.__name__ == "UserRejectObservation"

    def test_confirmed_returns_none(self):
        from backend.events.action import ActionConfirmationStatus

        rt = _FakeRuntime()
        action = MagicMock()
        action.confirmation_state = ActionConfirmationStatus.CONFIRMED
        result = rt._check_action_confirmation(action)
        assert result is None


# ------------------------------------------------------------------
# _enforce_security
# ------------------------------------------------------------------
class TestEnforceSecurity:
    def test_no_analyzer_returns_none(self):
        rt = _FakeRuntime(analyzer=None, enforce=True)
        action = MagicMock()
        result = rt._enforce_security(action)
        assert result is None

    def test_enforce_disabled_returns_none(self):
        rt = _FakeRuntime(analyzer=MagicMock(), enforce=False)
        action = MagicMock()
        result = rt._enforce_security(action)
        assert result is None

    def test_high_risk_blocked(self):
        from backend.core.enums import ActionSecurityRisk

        analyzer = MagicMock()
        analyzer.security_risk = AsyncMock(return_value=ActionSecurityRisk.HIGH)
        rt = _FakeRuntime(analyzer=analyzer, enforce=True, block_high=True)
        action = MagicMock()
        action.action = "test_action"
        with patch("asyncio.get_running_loop", side_effect=RuntimeError):
            with patch("asyncio.run", return_value=ActionSecurityRisk.HIGH):
                result = rt._enforce_security(action)
        assert result is not None
        assert result.__class__.__name__ == "ErrorObservation"

    def test_high_risk_requires_confirmation(self):
        from backend.core.enums import ActionSecurityRisk
        from backend.events.action import ActionConfirmationStatus

        analyzer = MagicMock()
        rt = _FakeRuntime(analyzer=analyzer, enforce=True, block_high=False)
        action = MagicMock()
        action.action = "test_action"
        action.confirmation_state = ActionConfirmationStatus.REJECTED  # Not CONFIRMED
        with patch("asyncio.get_running_loop", side_effect=RuntimeError):
            with patch("asyncio.run", return_value=ActionSecurityRisk.HIGH):
                result = rt._enforce_security(action)
        assert result is not None
        assert result.__class__.__name__ == "NullObservation"
        assert action.confirmation_state == ActionConfirmationStatus.AWAITING_CONFIRMATION

    def test_medium_risk_allowed(self):
        from backend.core.enums import ActionSecurityRisk

        analyzer = MagicMock()
        rt = _FakeRuntime(analyzer=analyzer, enforce=True, block_high=False)
        action = MagicMock()
        action.action = "test_action"
        with patch("asyncio.get_running_loop", side_effect=RuntimeError):
            with patch("asyncio.run", return_value=ActionSecurityRisk.MEDIUM):
                result = rt._enforce_security(action)
        assert result is None

    def test_low_risk_allowed(self):
        from backend.core.enums import ActionSecurityRisk

        analyzer = MagicMock()
        rt = _FakeRuntime(analyzer=analyzer, enforce=True, block_high=False)
        action = MagicMock()
        action.action = "test_action"
        with patch("asyncio.get_running_loop", side_effect=RuntimeError):
            with patch("asyncio.run", return_value=ActionSecurityRisk.LOW):
                result = rt._enforce_security(action)
        assert result is None
