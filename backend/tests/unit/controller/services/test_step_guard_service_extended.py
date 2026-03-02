"""Tests for StepGuardService covering repetition score and replan directives."""

from __future__ import annotations
import unittest
from unittest.mock import MagicMock, AsyncMock
from backend.controller.services.step_guard_service import StepGuardService
from backend.events import EventSource
from backend.events.action import AgentThinkAction

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
        
        # Run first attempt
        result = await self.service._handle_stuck_detection(self.controller)
        
        # Verify
        self.assertTrue(result)
        self.assertEqual(self.service._replan_attempts, 1)
        
        # Check event emitted
        self.controller.event_stream.add_event.assert_called()
        args, kwargs = self.controller.event_stream.add_event.call_args
        self.assertIsInstance(args[0], AgentThinkAction)
        self.assertIn("STUCK LOOP DETECTED", args[0].thought)
        self.assertEqual(args[1], EventSource.AGENT)

    async def test_handle_stuck_detection_exhausts_replan_attempts(self):
        # Setup mocks
        stuck_svc = MagicMock()
        stuck_svc.is_stuck.return_value = True
        self.controller.stuck_service = stuck_svc
        self.controller._react_to_exception = AsyncMock()
        
        # Set attempts to max
        self.service._replan_attempts = 2
        
        # Run
        result = await self.service._handle_stuck_detection(self.controller)
        
        # Verify
        self.assertFalse(result)
        self.assertEqual(self.service._replan_attempts, 0)
        self.controller._react_to_exception.assert_awaited_once()
