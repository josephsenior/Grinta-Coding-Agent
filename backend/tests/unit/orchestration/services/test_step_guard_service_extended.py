"""Tests for StepGuardService covering repetition score and replan directives."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.ledger import EventSource
from backend.ledger.action import FileEditAction
from backend.ledger.observation import CmdOutputObservation
from backend.ledger.observation.error import ErrorObservation
from backend.orchestration.services.step_guard_service import StepGuardService


class TestStepGuardService(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = MagicMock()
        self.controller = MagicMock()
        self.context.get_controller.return_value = self.controller
        self.service = StepGuardService(self.context)

    async def test_handle_stuck_detection_injects_score(self):
        # Setup mocks
        stuck_svc = MagicMock()
        stuck_svc.compute_repetition_score.return_value = 0.75
        stuck_svc.is_stuck.return_value = False
        self.controller.stuck_service = stuck_svc

        state = MagicMock()
        state.extra_data = {}
        state.turn_signals = MagicMock()
        self.controller.state = state

        # Run
        result = await self.service._handle_stuck_detection(self.controller)

        # Verify
        self.assertTrue(result)
        self.assertEqual(state.turn_signals.repetition_score, 0.75)

    async def test_handle_stuck_detection_injects_replan_directive(self):
        # Setup mocks
        stuck_svc = MagicMock()
        stuck_svc.compute_repetition_score.return_value = 1.0
        stuck_svc.is_stuck.return_value = True
        self.controller.stuck_service = stuck_svc

        self.controller.event_stream = MagicMock()
        state = MagicMock()
        state.extra_data = {}
        self.controller.state = state

        cb = MagicMock()
        cb.circuit_breaker.stuck_detection_count = 1
        self.controller.circuit_breaker_service = cb

        # Run first attempt: sets replan latch and returns False
        result = await self.service._handle_stuck_detection(self.controller)

        # First call: latch set, directive injected, returns False
        self.assertFalse(result)
        cb.record_stuck_detection.assert_called_once()

        # Check event emitted
        self.controller.event_stream.add_event.assert_called()
        args, kwargs = self.controller.event_stream.add_event.call_args
        self.assertIsInstance(args[0], ErrorObservation)
        self.assertIn('STUCK LOOP DETECTED', args[0].content)
        self.assertEqual(args[1], EventSource.ENVIRONMENT)

    async def test_handle_stuck_detection_repeated_stuck_still_replans(self):
        # Setup mocks
        stuck_svc = MagicMock()
        stuck_svc.compute_repetition_score.return_value = 1.0
        stuck_svc.is_stuck.return_value = True
        self.controller.stuck_service = stuck_svc
        self.controller.state = MagicMock()
        self.controller.state.extra_data = {}

        cb = MagicMock()
        cb.circuit_breaker.stuck_detection_count = 3
        self.controller.circuit_breaker_service = cb

        self.controller.event_stream = MagicMock()

        # Run: first stuck call returns False (latch set)
        result = await self.service._handle_stuck_detection(self.controller)

        # Verify
        self.assertFalse(result)
        cb.record_stuck_detection.assert_called_once()
        self.controller.event_stream.add_event.assert_called_once()

    async def test_handle_stuck_detection_records_each_stuck_turn(self):
        stuck_svc = MagicMock()
        stuck_svc.compute_repetition_score.return_value = 1.0
        stuck_svc.is_stuck.return_value = True
        self.controller.stuck_service = stuck_svc
        self.controller.state = MagicMock()
        self.controller.state.extra_data = {}
        self.controller.event_stream = MagicMock()

        cb = MagicMock()
        cb.circuit_breaker = MagicMock()
        self.controller.circuit_breaker_service = cb

        first = await self.service._handle_stuck_detection(self.controller)
        second = await self.service._handle_stuck_detection(self.controller)

        # First call: is_stuck() True → sets latch → records cb → injects directive → returns False
        # Second call: latch is set → clears latch → returns True (skips is_stuck entirely)
        self.assertFalse(first)
        self.assertTrue(second)
        self.assertEqual(cb.record_stuck_detection.call_count, 1)
        self.assertEqual(self.controller.event_stream.add_event.call_count, 1)

    async def test_handle_stuck_detection_clears_agent_queued_actions(self):
        stuck_svc = MagicMock()
        stuck_svc.compute_repetition_score.return_value = 1.0
        stuck_svc.is_stuck.return_value = True
        self.controller.stuck_service = stuck_svc
        self.controller.state = MagicMock()
        self.controller.state.extra_data = {}
        self.controller.event_stream = MagicMock()

        cb = MagicMock()
        cb.circuit_breaker = MagicMock()
        self.controller.circuit_breaker_service = cb

        self.controller.agent = MagicMock()
        self.controller.agent.clear_queued_actions = MagicMock(return_value=3)

        result = await self.service._handle_stuck_detection(self.controller)

        # First stuck call: sets replan latch and returns False (will yield True on next call)
        self.assertFalse(result)
        self.controller.agent.clear_queued_actions.assert_called_once()

    async def test_handle_stuck_detection_requires_fresh_verification_after_edit_failure(
        self,
    ):
        stuck_svc = MagicMock()
        stuck_svc.compute_repetition_score.return_value = 1.0
        stuck_svc.is_stuck.return_value = True
        self.controller.stuck_service = stuck_svc

        state = MagicMock()
        state.extra_data = {}
        state.set_extra = MagicMock()
        state.set_planning_directive = MagicMock()
        state.history = [
            FileEditAction(
                path='backend/context/schemas.py',
                command='replace_text',
                old_str='old',
                new_str='new',
            ),
            CmdOutputObservation(
                content='FAILED: backend/context/schemas.py is out of sync',
                command='uv run pytest -q',
                exit_code=1,
            ),
        ]
        self.controller.state = state
        self.controller.event_stream = MagicMock()
        self.controller.agent = MagicMock()
        self.controller.agent.clear_queued_actions = MagicMock(return_value=1)

        result = await self.service._handle_stuck_detection(self.controller)

        self.assertFalse(result)
        requirement = state.extra_data['__step_guard_verification_required']
        self.assertEqual(requirement['reason'], 'recent_file_mutation_plus_failure')
        self.assertEqual(requirement['paths'], ['backend/context/schemas.py'])
        emitted = self.controller.event_stream.add_event.call_args.args[0]
        self.assertIsInstance(emitted, ErrorObservation)
        self.assertIn('Do NOT emit another write/edit or finish action', emitted.content)
