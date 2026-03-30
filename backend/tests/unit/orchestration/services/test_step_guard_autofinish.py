"""Tests for StepGuardService reliability-first behavior."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.orchestration.services.step_guard_service import StepGuardService
from backend.ledger.action.files import FileEditAction, FileWriteAction


class TestNormalizePath(unittest.TestCase):
    """Test _normalize_path strips workspace prefix and normalizes slashes."""

    def test_workspace_prefix(self):
        self.assertEqual(
            StepGuardService._normalize_path("/workspace/src/app/page.tsx"),
            "src/app/page.tsx",
        )

    def test_backslash_normalization(self):
        self.assertEqual(
            StepGuardService._normalize_path("workspace\\src\\app\\page.tsx"),
            "src/app/page.tsx",
        )

    def test_plain_path(self):
        self.assertEqual(
            StepGuardService._normalize_path("src/app/page.tsx"),
            "src/app/page.tsx",
        )


class TestRecoveryMessage(unittest.TestCase):
    def test_build_message_with_created_files_is_generic(self):
        msg, planning = StepGuardService(MagicMock())._build_stuck_recovery_message(
            {"src/app/page.tsx", "src/app/layout.tsx"}
        )
        self.assertIn("Files already touched in this session", msg)
        self.assertIn("Do NOT assume the task is complete", msg)
        self.assertIn("verify current state", planning)

    def test_build_message_without_created_files_is_generic(self):
        msg, planning = StepGuardService(MagicMock())._build_stuck_recovery_message(set())
        self.assertIn("Stop repeating", msg)
        self.assertIn("verify state", planning)


class TestInjectReplanDirective(unittest.TestCase):
    def setUp(self):
        self.context = MagicMock()
        self.controller = MagicMock()
        self.controller.event_stream = MagicMock()
        self.context.get_controller.return_value = self.controller
        self.service = StepGuardService(self.context)
        self.controller.state = MagicMock()
        self.controller.state.history = [
            FileWriteAction(path="/workspace/src/app/page.tsx"),
            FileEditAction(path="src/app/layout.tsx"),
        ]
        self.controller.state.set_planning_directive = MagicMock()

    def test_inject_replan_directive_emits_error_observation(self):
        self.service._inject_replan_directive(self.controller)
        self.controller.event_stream.add_event.assert_called_once()
        obs = self.controller.event_stream.add_event.call_args[0][0]
        self.assertIn("STUCK LOOP DETECTED", obs.content)
        self.assertIn("Files already touched", obs.content)

    def test_inject_replan_directive_sets_planning_directive(self):
        self.service._inject_replan_directive(self.controller)
        self.controller.state.set_planning_directive.assert_called_once()


class TestEnsureCanStep(unittest.IsolatedAsyncioTestCase):
    async def test_circuit_breaker_blocks_before_stuck_detection(self):
        context = MagicMock()
        controller = MagicMock()
        context.get_controller.return_value = controller
        service = StepGuardService(context)
        with (
            patch.object(service, "_check_circuit_breaker", new=AsyncMock(return_value=False)) as mock_check,
            patch.object(service, "_handle_stuck_detection", new=AsyncMock(return_value=True)) as mock_handle,
        ):
            allowed = await service.ensure_can_step()

        self.assertFalse(allowed)
        mock_check.assert_awaited_once_with(controller)
        mock_handle.assert_not_awaited()

    async def test_stuck_detection_runs_after_circuit_breaker_clear(self):
        context = MagicMock()
        controller = MagicMock()
        context.get_controller.return_value = controller
        service = StepGuardService(context)
        with (
            patch.object(service, "_check_circuit_breaker", new=AsyncMock(return_value=True)) as mock_check,
            patch.object(service, "_handle_stuck_detection", new=AsyncMock(return_value=True)) as mock_handle,
        ):
            allowed = await service.ensure_can_step()

        self.assertTrue(allowed)
        mock_check.assert_awaited_once_with(controller)
        mock_handle.assert_awaited_once_with(controller)
