"""Tests for StuckDetectionService."""

import unittest
from unittest.mock import MagicMock, Mock, patch

from backend.controller.services.stuck_detection_service import StuckDetectionService


class TestStuckDetectionService(unittest.TestCase):
    """Test StuckDetectionService stuck detection logic."""

    def setUp(self):
        """Create mock controller for testing."""
        self.mock_controller = MagicMock()
        self.mock_controller.headless_mode = False
        self.service = StuckDetectionService(self.mock_controller)

    def test_initialization(self):
        """Test service initializes with no detector."""
        self.assertEqual(self.service._controller, self.mock_controller)
        self.assertIsNone(self.service._detector)

    @patch('backend.controller.services.stuck_detection_service.StuckDetector')
    def test_initialize_creates_detector(self, mock_detector_class):
        """Test initialize() creates StuckDetector for state."""
        mock_state = MagicMock()
        mock_detector = MagicMock()
        mock_detector_class.return_value = mock_detector
        
        self.service.initialize(mock_state)
        
        mock_detector_class.assert_called_once_with(mock_state)
        self.assertEqual(self.service._detector, mock_detector)

    def test_is_stuck_no_detector(self):
        """Test is_stuck() returns False when detector not initialized."""
        result = self.service.is_stuck()
        
        self.assertFalse(result)

    @patch('backend.controller.services.stuck_detection_service.StuckDetector')
    def test_is_stuck_with_detector_not_stuck(self, mock_detector_class):
        """Test is_stuck() returns False when detector says not stuck."""
        mock_state = MagicMock()
        mock_detector = MagicMock()
        mock_detector.is_stuck.return_value = False
        mock_detector_class.return_value = mock_detector
        
        self.service.initialize(mock_state)
        result = self.service.is_stuck()
        
        self.assertFalse(result)
        mock_detector.is_stuck.assert_called_once_with(False)  # headless_mode=False

    @patch('backend.controller.services.stuck_detection_service.StuckDetector')
    def test_is_stuck_with_detector_stuck(self, mock_detector_class):
        """Test is_stuck() returns True when detector says stuck."""
        mock_state = MagicMock()
        mock_detector = MagicMock()
        mock_detector.is_stuck.return_value = True
        mock_detector_class.return_value = mock_detector
        
        self.service.initialize(mock_state)
        result = self.service.is_stuck()
        
        self.assertTrue(result)
        mock_detector.is_stuck.assert_called_once_with(False)

    @patch('backend.controller.services.stuck_detection_service.StuckDetector')
    def test_is_stuck_headless_mode(self, mock_detector_class):
        """Test is_stuck() passes headless_mode to detector."""
        self.mock_controller.headless_mode = True
        mock_state = MagicMock()
        mock_detector = MagicMock()
        mock_detector.is_stuck.return_value = False
        mock_detector_class.return_value = mock_detector
        
        self.service.initialize(mock_state)
        self.service.is_stuck()
        
        mock_detector.is_stuck.assert_called_once_with(True)  # headless_mode=True

    def test_is_stuck_with_delegate_stuck(self):
        """Test is_stuck() checks delegate first and returns True if delegate stuck."""
        # Set up delegate with stuck_service
        mock_delegate = MagicMock()
        mock_delegate_stuck_service = MagicMock()
        mock_delegate_stuck_service.is_stuck.return_value = True
        mock_delegate.stuck_service = mock_delegate_stuck_service
        
        self.mock_controller.delegate = mock_delegate
        
        result = self.service.is_stuck()
        
        self.assertTrue(result)
        mock_delegate_stuck_service.is_stuck.assert_called_once()

    @patch('backend.controller.services.stuck_detection_service.StuckDetector')
    def test_is_stuck_with_delegate_not_stuck_checks_own_detector(self, mock_detector_class):
        """Test is_stuck() checks own detector when delegate not stuck."""
        # Set up delegate not stuck
        mock_delegate = MagicMock()
        mock_delegate_stuck_service = MagicMock()
        mock_delegate_stuck_service.is_stuck.return_value = False
        mock_delegate.stuck_service = mock_delegate_stuck_service
        
        self.mock_controller.delegate = mock_delegate
        
        # Set up own detector as stuck
        mock_state = MagicMock()
        mock_detector = MagicMock()
        mock_detector.is_stuck.return_value = True
        mock_detector_class.return_value = mock_detector
        
        self.service.initialize(mock_state)
        result = self.service.is_stuck()
        
        # Should check both
        mock_delegate_stuck_service.is_stuck.assert_called_once()
        mock_detector.is_stuck.assert_called_once()
        self.assertTrue(result)

    def test_is_stuck_with_delegate_no_stuck_service(self):
        """Test is_stuck() handles delegate without stuck_service."""
        mock_delegate = MagicMock(spec=[])  # No stuck_service attribute
        self.mock_controller.delegate = mock_delegate
        
        result = self.service.is_stuck()
        
        # Should not raise exception, should return False (no detector)
        self.assertFalse(result)

    def test_is_stuck_no_delegate(self):
        """Test is_stuck() handles missing delegate."""
        self.mock_controller.delegate = None
        
        result = self.service.is_stuck()
        
        # Should not raise exception
        self.assertFalse(result)

    @patch('backend.controller.services.stuck_detection_service.StuckDetector')
    def test_is_stuck_detector_returns_non_bool(self, mock_detector_class):
        """Test is_stuck() handles detector returning non-bool value."""
        mock_state = MagicMock()
        mock_detector = MagicMock()
        mock_detector.is_stuck.return_value = None  # Non-bool
        mock_detector_class.return_value = mock_detector
        
        self.service.initialize(mock_state)
        result = self.service.is_stuck()
        
        # Should convert to bool
        self.assertFalse(result)

    @patch('backend.controller.services.stuck_detection_service.StuckDetector')
    def test_is_stuck_detector_returns_truthy_value(self, mock_detector_class):
        """Test is_stuck() converts truthy values to True."""
        mock_state = MagicMock()
        mock_detector = MagicMock()
        mock_detector.is_stuck.return_value = "stuck"  # Truthy non-bool
        mock_detector_class.return_value = mock_detector
        
        self.service.initialize(mock_state)
        result = self.service.is_stuck()
        
        self.assertTrue(result)

    @patch('backend.controller.services.stuck_detection_service.StuckDetector')
    def test_multiple_initialize_calls(self, mock_detector_class):
        """Test multiple initialize() calls replace detector."""
        mock_state1 = MagicMock()
        mock_state2 = MagicMock()
        
        mock_detector1 = MagicMock()
        mock_detector2 = MagicMock()
        
        mock_detector_class.side_effect = [mock_detector1, mock_detector2]
        
        self.service.initialize(mock_state1)
        self.assertEqual(self.service._detector, mock_detector1)
        
        self.service.initialize(mock_state2)
        self.assertEqual(self.service._detector, mock_detector2)
        
        self.assertEqual(mock_detector_class.call_count, 2)


if __name__ == '__main__':
    unittest.main()
