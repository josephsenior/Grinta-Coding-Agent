"""Unit tests for GuardBus."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.orchestration.services.guard_bus import (
    _STATE_KEY,  # type: ignore[reportPrivateUsage]
    CHECKPOINT,
    CIRCUIT_WARNING,
    HARD_STOP,
    STUCK,
    VERIFICATION,
    GuardBus,
    _get_slot,  # type: ignore[reportPrivateUsage]
    _TurnSlot,  # type: ignore[reportPrivateUsage]
)


def _make_controller(turn: int = 0) -> SimpleNamespace:
    """Build a minimal controller duck-type for GuardBus tests."""
    iteration_flag = SimpleNamespace(current_value=turn)
    state = SimpleNamespace(
        iteration_flag=iteration_flag,
        extra_data={},
    )
    state.set_planning_directive = MagicMock()
    event_stream = MagicMock()
    return SimpleNamespace(state=state, event_stream=event_stream)


class TestTurnSlot(unittest.TestCase):
    def test_fresh_slot_allows_any_priority(self):
        slot = _TurnSlot(0)
        self.assertTrue(slot.can_emit(HARD_STOP))
        self.assertTrue(slot.can_emit(STUCK))
        self.assertTrue(slot.can_emit(CIRCUIT_WARNING))

    def test_after_record_lower_number_wins_slot(self):
        slot = _TurnSlot(0)
        slot.record(CIRCUIT_WARNING)  # 4
        # STUCK (2) < CIRCUIT_WARNING (4) → still allowed
        self.assertTrue(slot.can_emit(STUCK))
        # same priority → not allowed
        self.assertFalse(slot.can_emit(CIRCUIT_WARNING))
        # lower priority (higher number) → not allowed
        self.assertFalse(slot.can_emit(CHECKPOINT))

    def test_record_updates_best_priority(self):
        slot = _TurnSlot(0)
        slot.record(VERIFICATION)  # 3
        slot.record(STUCK)  # 2 — should update
        self.assertEqual(slot.best_priority, STUCK)

    def test_record_does_not_update_to_lower_priority(self):
        slot = _TurnSlot(0)
        slot.record(STUCK)  # 2
        slot.record(CIRCUIT_WARNING)  # 4 — should NOT update
        self.assertEqual(slot.best_priority, STUCK)


class TestGetSlot(unittest.TestCase):
    def test_creates_slot_on_first_call(self):
        state = SimpleNamespace(
            extra_data={}, iteration_flag=SimpleNamespace(current_value=5)
        )
        slot = _get_slot(state)
        self.assertEqual(slot.turn, 5)
        self.assertIs(state.extra_data[_STATE_KEY], slot)

    def test_returns_same_slot_same_turn(self):
        state = SimpleNamespace(
            extra_data={}, iteration_flag=SimpleNamespace(current_value=3)
        )
        s1 = _get_slot(state)
        s2 = _get_slot(state)
        self.assertIs(s1, s2)

    def test_creates_fresh_slot_on_new_turn(self):
        state = SimpleNamespace(
            extra_data={}, iteration_flag=SimpleNamespace(current_value=1)
        )
        s1 = _get_slot(state)
        s1.record(CIRCUIT_WARNING)
        state.iteration_flag.current_value = 2
        s2 = _get_slot(state)
        self.assertIsNone(s2.best_priority)
        self.assertEqual(s2.turn, 2)

    def test_no_extra_data_returns_orphan_slot(self):
        state = SimpleNamespace(iteration_flag=SimpleNamespace(current_value=0))
        slot = _get_slot(state)
        self.assertEqual(slot.turn, 0)


class TestGuardBusEmit(unittest.TestCase):
    # ── XOR rule ─────────────────────────────────────────────────────────────

    def test_emits_observation_and_no_directive_when_budget_available(self):
        ctrl = _make_controller(turn=1)
        result = GuardBus.emit(
            ctrl, CIRCUIT_WARNING, 'TEST_OBS', 'content', 'directive text'
        )
        self.assertTrue(result)
        ctrl.event_stream.add_event.assert_called_once()
        obs = ctrl.event_stream.add_event.call_args.args[0]
        self.assertEqual(obs.error_id, 'TEST_OBS')
        # XOR: directive must NOT be set
        ctrl.state.set_planning_directive.assert_not_called()

    def test_sets_directive_and_no_observation_when_budget_exhausted(self):
        ctrl = _make_controller(turn=1)
        # First emit spends the budget
        GuardBus.emit(ctrl, CIRCUIT_WARNING, 'FIRST', 'content1', 'directive1')
        ctrl.event_stream.add_event.reset_mock()
        # Second emit at same priority is downgraded
        result = GuardBus.emit(
            ctrl, CIRCUIT_WARNING, 'SECOND', 'content2', 'directive2'
        )
        self.assertFalse(result)
        ctrl.event_stream.add_event.assert_not_called()
        ctrl.state.set_planning_directive.assert_called_once_with(
            'directive2', source='GuardBus'
        )

    # ── Per-turn budget ───────────────────────────────────────────────────────

    def test_budget_resets_on_new_turn(self):
        ctrl = _make_controller(turn=1)
        GuardBus.emit(ctrl, CIRCUIT_WARNING, 'OBS_T1', 'content', 'directive')
        # Advance turn
        ctrl.state.iteration_flag.current_value = 2
        ctrl.event_stream.add_event.reset_mock()
        result = GuardBus.emit(ctrl, CIRCUIT_WARNING, 'OBS_T2', 'content', 'directive')
        self.assertTrue(result)
        ctrl.event_stream.add_event.assert_called_once()

    def test_higher_priority_allowed_after_lower_priority_emitted(self):
        ctrl = _make_controller(turn=1)
        # Lower priority (higher number) emitted first
        GuardBus.emit(ctrl, CIRCUIT_WARNING, 'WARN', 'content', 'dir')
        ctrl.event_stream.add_event.reset_mock()
        # Higher priority (lower number) should still be allowed
        result = GuardBus.emit(ctrl, STUCK, 'STUCK_OBS', 'stuck content', 'stuck dir')
        self.assertTrue(result)
        ctrl.event_stream.add_event.assert_called_once()

    def test_lower_priority_blocked_after_higher_priority_emitted(self):
        ctrl = _make_controller(turn=1)
        GuardBus.emit(ctrl, STUCK, 'STUCK_OBS', 'content', 'dir')
        ctrl.event_stream.add_event.reset_mock()
        ctrl.state.set_planning_directive.reset_mock()
        result = GuardBus.emit(ctrl, CIRCUIT_WARNING, 'WARN', 'content2', 'dir2')
        self.assertFalse(result)
        ctrl.event_stream.add_event.assert_not_called()
        # Directive-only fallback should fire
        ctrl.state.set_planning_directive.assert_called_once()

    # ── Force flag ────────────────────────────────────────────────────────────

    def test_force_bypasses_budget_limit(self):
        ctrl = _make_controller(turn=1)
        # Spend budget with HARD_STOP priority
        GuardBus.emit(ctrl, HARD_STOP, 'FIRST', 'content1')
        ctrl.event_stream.add_event.reset_mock()
        # force=True should still emit a second observation
        result = GuardBus.emit(ctrl, HARD_STOP, 'FORCED', 'content2', force=True)
        self.assertTrue(result)
        ctrl.event_stream.add_event.assert_called_once()

    def test_force_does_not_set_directive(self):
        ctrl = _make_controller(turn=1)
        GuardBus.emit(ctrl, HARD_STOP, 'FORCED', 'content', 'directive', force=True)
        # XOR still applies for force: observation emitted → no directive
        ctrl.state.set_planning_directive.assert_not_called()

    # ── Edge cases ────────────────────────────────────────────────────────────

    def test_missing_state_returns_false(self):
        ctrl = SimpleNamespace(state=None, event_stream=MagicMock())
        result = GuardBus.emit(ctrl, CIRCUIT_WARNING, 'OBS', 'content')
        self.assertFalse(result)
        ctrl.event_stream.add_event.assert_not_called()

    def test_missing_event_stream_returns_false(self):
        state = SimpleNamespace(
            extra_data={}, iteration_flag=SimpleNamespace(current_value=0)
        )
        state.set_planning_directive = MagicMock()
        ctrl = SimpleNamespace(state=state, event_stream=None)
        result = GuardBus.emit(ctrl, CIRCUIT_WARNING, 'OBS', 'content')
        self.assertFalse(result)

    def test_no_directive_provided_budget_exhausted_does_not_crash(self):
        ctrl = _make_controller(turn=1)
        GuardBus.emit(ctrl, CIRCUIT_WARNING, 'FIRST', 'content')
        # Second call without directive — should not crash
        result = GuardBus.emit(ctrl, CIRCUIT_WARNING, 'SECOND', 'content2')
        self.assertFalse(result)
        ctrl.state.set_planning_directive.assert_not_called()

    def test_cause_is_attached_when_provided(self):
        ctrl = _make_controller(turn=1)
        fake_cause = MagicMock()
        fake_cause.id = 42
        with patch(
            'backend.orchestration.services.guard_bus.attach_observation_cause'
        ) as mock_attach:
            GuardBus.emit(
                ctrl,
                CIRCUIT_WARNING,
                'OBS',
                'content',
                cause=fake_cause,
                cause_context='test.ctx',
            )
            mock_attach.assert_called_once()
            _, call_cause, *_ = mock_attach.call_args.args
            self.assertIs(call_cause, fake_cause)

    def test_cause_not_attached_when_none(self):
        ctrl = _make_controller(turn=1)
        with patch(
            'backend.orchestration.services.guard_bus.attach_observation_cause'
        ) as mock_attach:
            GuardBus.emit(ctrl, CIRCUIT_WARNING, 'OBS', 'content', cause=None)
            mock_attach.assert_not_called()

    # ── Priority order sanity ─────────────────────────────────────────────────

    def test_priority_constants_ordered_correctly(self):
        self.assertLess(HARD_STOP, STUCK)
        self.assertLess(STUCK, VERIFICATION)
        self.assertLess(VERIFICATION, CIRCUIT_WARNING)
        self.assertLess(CIRCUIT_WARNING, CHECKPOINT)


if __name__ == '__main__':
    unittest.main()
