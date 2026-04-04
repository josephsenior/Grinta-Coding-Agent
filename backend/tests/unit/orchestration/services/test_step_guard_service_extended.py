"""Tests for StepGuardService covering repetition score and replan directives."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from backend.ledger import EventSource
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
        self.controller.state = state

        cb = MagicMock()
        cb.circuit_breaker.stuck_detection_count = 1
        self.controller.circuit_breaker_service = cb

        # Run first attempt
        result = await self.service._handle_stuck_detection(self.controller)

        # Verify
        self.assertTrue(result)
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

        cb = MagicMock()
        cb.circuit_breaker.stuck_detection_count = 3
        self.controller.circuit_breaker_service = cb

        self.controller.event_stream = MagicMock()

        # Run
        result = await self.service._handle_stuck_detection(self.controller)

        # Verify
        self.assertTrue(result)
        cb.record_stuck_detection.assert_called_once()
        self.controller.event_stream.add_event.assert_called_once()
