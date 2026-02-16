"""Tests for backend.controller.services.stuck_detection_service."""

from __future__ import annotations

from unittest.mock import MagicMock


from backend.controller.services.stuck_detection_service import StuckDetectionService


# ── is_stuck ─────────────────────────────────────────────────────────

class TestIsStuck:
    def test_no_detector(self):
        ctrl = MagicMock(spec=["delegate", "headless_mode"])
        ctrl.delegate = None
        svc = StuckDetectionService(ctrl)
        assert svc.is_stuck() is False

    def test_detector_not_stuck(self):
        ctrl = MagicMock(spec=["delegate", "headless_mode"])
        ctrl.headless_mode = False
        ctrl.delegate = None
        svc = StuckDetectionService(ctrl)
        # Initialize with a mock state
        state = MagicMock()
        state.history = []
        svc.initialize(state)
        # StuckDetector.is_stuck checks history — with empty history, not stuck
        assert svc.is_stuck() is False

    def test_delegate_stuck(self):
        delegate = MagicMock()
        delegate.stuck_service.is_stuck.return_value = True
        ctrl = MagicMock()
        ctrl.delegate = delegate
        ctrl.headless_mode = False
        svc = StuckDetectionService(ctrl)
        assert svc.is_stuck() is True

    def test_delegate_not_stuck_with_detector(self):
        delegate = MagicMock()
        delegate.stuck_service.is_stuck.return_value = False
        ctrl = MagicMock()
        ctrl.delegate = delegate
        ctrl.headless_mode = False
        svc = StuckDetectionService(ctrl)
        # No detector, delegate not stuck
        assert svc.is_stuck() is False


# ── initialize ───────────────────────────────────────────────────────

class TestInitialize:
    def test_creates_detector(self):
        ctrl = MagicMock()
        ctrl.delegate = None
        ctrl.headless_mode = False
        svc = StuckDetectionService(ctrl)
        assert svc._detector is None
        state = MagicMock()
        state.history = []
        svc.initialize(state)
        assert svc._detector is not None
