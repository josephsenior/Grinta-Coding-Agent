"""Tests for SafetyService."""

import unittest
from unittest.mock import MagicMock, AsyncMock, patch

from backend.orchestration.services.safety_service import SafetyService
from backend.ledger import EventSource
from backend.ledger.action import (
    Action,
    ActionConfirmationStatus,
    ActionSecurityRisk,
    CmdRunAction,
    BrowseInteractiveAction,
    FileEditAction,
    FileReadAction,
)


class TestSafetyService(unittest.IsolatedAsyncioTestCase):
    """Test SafetyService security and confirmation management."""

    def setUp(self):
        """Create mock context for testing."""
        self.mock_context = MagicMock()
        self.mock_context.autonomy_controller = None
        self.mock_context.security_analyzer = None
        self.mock_context.confirmation_mode = False
        self.mock_context.pending_action = None

        self.mock_controller = MagicMock()
        self.mock_controller.agent = MagicMock()
        self.mock_controller.agent.config = MagicMock()
        self.mock_controller.agent.config.cli_mode = False
        self.mock_context.get_controller.return_value = self.mock_controller

        self.service = SafetyService(self.mock_context)

    def test_action_requires_confirmation_cmd_run(self):
        """Test action_requires_confirmation for CmdRunAction."""
        action = CmdRunAction(command="ls")

        result = self.service.action_requires_confirmation(action)

        self.assertTrue(result)

    def test_action_requires_confirmation_browse(self):
        """Test action_requires_confirmation for BrowseInteractiveAction."""
        action = BrowseInteractiveAction(browser_actions="test")

        result = self.service.action_requires_confirmation(action)

        self.assertTrue(result)

    def test_action_requires_confirmation_file_edit(self):
        """Test action_requires_confirmation for FileEditAction."""
        action = FileEditAction(path="/test", content="test")

        result = self.service.action_requires_confirmation(action)

        self.assertTrue(result)

    def test_action_requires_confirmation_file_read(self):
        """Test action_requires_confirmation for FileReadAction."""
        action = FileReadAction(path="/test")

        result = self.service.action_requires_confirmation(action)

        self.assertTrue(result)

    def test_action_requires_confirmation_other_action(self):
        """Test action_requires_confirmation for non-confirmation actions."""
        action = MagicMock(spec=Action)

        result = self.service.action_requires_confirmation(action)

        self.assertFalse(result)

    def test_evaluate_security_risk_high_risk(self):
        """Test evaluate_security_risk identifies high risk."""
        action = MagicMock()
        action.security_risk = ActionSecurityRisk.HIGH

        is_high_risk, ask_for_every = self.service.evaluate_security_risk(action)

        self.assertTrue(is_high_risk)
        self.assertFalse(ask_for_every)

    def test_evaluate_security_risk_low_risk(self):
        """Test evaluate_security_risk with low risk."""
        action = MagicMock()
        action.security_risk = ActionSecurityRisk.LOW

        is_high_risk, ask_for_every = self.service.evaluate_security_risk(action)

        self.assertFalse(is_high_risk)
        self.assertFalse(ask_for_every)

    def test_evaluate_security_risk_unknown_no_analyzer(self):
        """Test evaluate_security_risk with unknown risk and no analyzer."""
        action = MagicMock()
        action.security_risk = ActionSecurityRisk.UNKNOWN
        self.mock_context.security_analyzer = None

        is_high_risk, ask_for_every = self.service.evaluate_security_risk(action)

        self.assertFalse(is_high_risk)
        self.assertTrue(ask_for_every)

    def test_evaluate_security_risk_unknown_with_analyzer(self):
        """Test evaluate_security_risk with unknown risk but analyzer exists."""
        action = MagicMock()
        action.security_risk = ActionSecurityRisk.UNKNOWN
        self.mock_context.security_analyzer = MagicMock()

        is_high_risk, ask_for_every = self.service.evaluate_security_risk(action)

        self.assertFalse(is_high_risk)
        self.assertFalse(ask_for_every)

    def test_evaluate_security_risk_no_security_risk_attr(self):
        """Test evaluate_security_risk with action without security_risk."""
        action = MagicMock(spec=[])  # No security_risk attribute

        is_high_risk, ask_for_every = self.service.evaluate_security_risk(action)

        # UNKNOWN risk + no analyzer = ask for every action
        self.assertFalse(is_high_risk)
        self.assertTrue(ask_for_every)

    async def test_analyze_security_no_analyzer(self):
        """Test analyze_security sets UNKNOWN risk when no analyzer."""
        action = MagicMock()
        action.security_risk = None
        self.mock_context.security_analyzer = None

        await self.service.analyze_security(action)

        # Should set to UNKNOWN
        self.assertEqual(action.security_risk, ActionSecurityRisk.UNKNOWN)

    async def test_analyze_security_with_analyzer(self):
        """Test analyze_security invokes analyzer."""
        action = MagicMock()
        action.security_risk = None

        mock_analyzer = MagicMock()
        mock_analyzer.security_risk = AsyncMock(return_value=ActionSecurityRisk.LOW)
        self.mock_context.security_analyzer = mock_analyzer

        await self.service.analyze_security(action)

        # Should set result from analyzer
        self.assertEqual(action.security_risk, ActionSecurityRisk.LOW)
        mock_analyzer.security_risk.assert_called_once_with(action)

    async def test_analyze_security_analyzer_exception(self):
        """Test analyze_security handles analyzer exceptions."""
        action = MagicMock()
        action.security_risk = ActionSecurityRisk.HIGH

        mock_analyzer = MagicMock()
        mock_analyzer.security_risk = AsyncMock(
            side_effect=RuntimeError("Analyzer failed")
        )
        self.mock_context.security_analyzer = mock_analyzer

        with patch("backend.orchestration.services.safety_service.logger") as mock_logger:
            await self.service.analyze_security(action)

        # Should set to UNKNOWN and log warning
        self.assertEqual(action.security_risk, ActionSecurityRisk.UNKNOWN)
        mock_logger.warning.assert_called_once()

    async def test_analyze_security_no_security_risk_attr(self):
        """Test analyze_security with action lacking security_risk attribute."""
        action = MagicMock(spec=[])  # No security_risk

        mock_analyzer = MagicMock()
        self.mock_context.security_analyzer = mock_analyzer

        # Should not crash
        await self.service.analyze_security(action)

    def test_apply_confirmation_state_no_autonomy(self):
        """Test apply_confirmation_state when no autonomy controller."""
        action = CmdRunAction(command="test")
        self.mock_context.autonomy_controller = None

        self.service.apply_confirmation_state(
            action, is_high_security_risk=True, is_ask_for_every_action=False
        )

        # Should not set confirmation state
        self.assertNotEqual(
            getattr(action, "confirmation_state", None),
            ActionConfirmationStatus.AWAITING_CONFIRMATION,
        )

    def test_apply_confirmation_state_autonomy_no_request(self):
        """Test apply_confirmation_state when autonomy doesn't request confirmation."""
        action = CmdRunAction(command="test")

        mock_autonomy = MagicMock()
        mock_autonomy.should_request_confirmation.return_value = False
        self.mock_context.autonomy_controller = mock_autonomy

        self.service.apply_confirmation_state(
            action, is_high_security_risk=True, is_ask_for_every_action=False
        )

        # Should not set confirmation state
        self.assertNotEqual(
            getattr(action, "confirmation_state", None),
            ActionConfirmationStatus.AWAITING_CONFIRMATION,
        )

    def test_apply_confirmation_state_cli_mode(self):
        """Test apply_confirmation_state in CLI mode."""
        action = CmdRunAction(command="test")

        mock_autonomy = MagicMock()
        mock_autonomy.should_request_confirmation.return_value = True
        self.mock_context.autonomy_controller = mock_autonomy
        self.mock_controller.agent.config.cli_mode = True

        self.service.apply_confirmation_state(
            action, is_high_security_risk=False, is_ask_for_every_action=False
        )

        # Should set awaiting confirmation in CLI mode
        self.assertEqual(
            action.confirmation_state, ActionConfirmationStatus.AWAITING_CONFIRMATION
        )

    def test_apply_confirmation_state_high_risk_non_cli(self):
        """Test apply_confirmation_state for high risk in non-CLI mode."""
        action = CmdRunAction(command="test")

        mock_autonomy = MagicMock()
        mock_autonomy.should_request_confirmation.return_value = True
        self.mock_context.autonomy_controller = mock_autonomy
        self.mock_controller.agent.config.cli_mode = False
        self.mock_context.confirmation_mode = True

        self.service.apply_confirmation_state(
            action, is_high_security_risk=True, is_ask_for_every_action=False
        )

        # Should set awaiting confirmation for high risk
        self.assertEqual(
            action.confirmation_state, ActionConfirmationStatus.AWAITING_CONFIRMATION
        )

    def test_apply_confirmation_state_ask_every_non_cli(self):
        """Test apply_confirmation_state for ask_every in non-CLI mode."""
        action = CmdRunAction(command="test")

        mock_autonomy = MagicMock()
        mock_autonomy.should_request_confirmation.return_value = True
        self.mock_context.autonomy_controller = mock_autonomy
        self.mock_controller.agent.config.cli_mode = False
        self.mock_context.confirmation_mode = True

        self.service.apply_confirmation_state(
            action, is_high_security_risk=False, is_ask_for_every_action=True
        )

        # Should set awaiting confirmation
        self.assertEqual(
            action.confirmation_state, ActionConfirmationStatus.AWAITING_CONFIRMATION
        )

    def test_apply_confirmation_state_low_risk_no_confirm_mode(self):
        """Test apply_confirmation_state for low risk without confirmation mode."""
        action = CmdRunAction(command="test")

        mock_autonomy = MagicMock()
        mock_autonomy.should_request_confirmation.return_value = True
        self.mock_context.autonomy_controller = mock_autonomy
        self.mock_controller.agent.config.cli_mode = False
        self.mock_context.confirmation_mode = False

        self.service.apply_confirmation_state(
            action, is_high_security_risk=False, is_ask_for_every_action=False
        )

        # Should not set confirmation state
        self.assertNotEqual(
            getattr(action, "confirmation_state", None),
            ActionConfirmationStatus.AWAITING_CONFIRMATION,
        )

    def test_finalize_pending_action_confirmed(self):
        """Test finalize_pending_action with confirmation."""
        mock_pending = MagicMock()
        mock_pending.thought = "Original thought"
        mock_pending._id = "action-123"
        self.mock_context.pending_action = mock_pending

        self.service.finalize_pending_action(confirmed=True)

        # Should clear thought and set confirmation state
        self.assertEqual(mock_pending.thought, "")
        self.assertEqual(
            mock_pending.confirmation_state, ActionConfirmationStatus.CONFIRMED
        )
        self.assertIsNone(mock_pending._id)

        # Should emit and clear
        self.mock_context.emit_event.assert_called_once_with(
            mock_pending, EventSource.AGENT
        )
        self.mock_context.clear_pending_action.assert_called_once()

    def test_finalize_pending_action_rejected(self):
        """Test finalize_pending_action with rejection."""
        mock_pending = MagicMock()
        mock_pending.thought = "Thought"
        mock_pending._id = "action-456"
        self.mock_context.pending_action = mock_pending

        self.service.finalize_pending_action(confirmed=False)

        # Should set rejected state
        self.assertEqual(
            mock_pending.confirmation_state, ActionConfirmationStatus.REJECTED
        )

    def test_finalize_pending_action_none(self):
        """Test finalize_pending_action when no pending action."""
        self.mock_context.pending_action = None

        self.service.finalize_pending_action(confirmed=True)

        # Should not crash
        self.mock_context.emit_event.assert_not_called()

    def test_finalize_pending_action_no_thought(self):
        """Test finalize_pending_action with action lacking thought attribute."""
        mock_pending = MagicMock(spec=["_id", "confirmation_state"])
        mock_pending._id = "action-789"
        self.mock_context.pending_action = mock_pending

        self.service.finalize_pending_action(confirmed=True)

        # Should still process without thought attribute
        self.mock_context.emit_event.assert_called_once()


if __name__ == "__main__":
    unittest.main()
