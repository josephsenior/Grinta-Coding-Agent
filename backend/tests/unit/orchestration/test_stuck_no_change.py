"""Tests for StuckDetector._extract_observation_outcome — no_change fix.

When FileEditObservation has old_content == new_content (silent re-create),
the stuck detector should classify this as 'no_change' so it can detect
the agent is stuck in a recreation loop.
"""

import unittest
from unittest.mock import MagicMock

from backend.orchestration.stuck import StuckDetector
from backend.ledger.observation.error import ErrorObservation
from backend.ledger.observation.files import FileEditObservation
from backend.ledger.observation.observation import Observation


class TestExtractObservationOutcome(unittest.TestCase):
    """Test _extract_observation_outcome classifies observations correctly."""

    def setUp(self):
        mock_state = MagicMock()
        mock_state.history = []
        self.detector = StuckDetector(mock_state)

    def test_error_observation(self):
        obs = ErrorObservation(content="something failed")
        result = self.detector._extract_observation_outcome(obs)
        self.assertEqual(result, "error")

    def test_file_edit_same_content_returns_no_change(self):
        """Re-creation: old_content == new_content → 'no_change'."""
        obs = MagicMock(spec=FileEditObservation)
        obs.__class__ = FileEditObservation  # type: ignore[assignment]
        obs.content = "File created successfully"
        obs.old_content = "export default function Page() {}"
        obs.new_content = "export default function Page() {}"
        result = self.detector._extract_observation_outcome(obs)
        self.assertEqual(result, "no_change")

    def test_file_edit_different_content_returns_unknown(self):
        """Genuine edit: old != new → 'unknown' (not no_change)."""
        obs = MagicMock(spec=FileEditObservation)
        obs.__class__ = FileEditObservation  # type: ignore[assignment]
        obs.content = "File created successfully"
        obs.old_content = "old version"
        obs.new_content = "new version"
        result = self.detector._extract_observation_outcome(obs)
        self.assertEqual(result, "unknown")

    def test_file_edit_none_old_content(self):
        """New file creation: old_content is None → 'unknown'."""
        obs = MagicMock(spec=FileEditObservation)
        obs.__class__ = FileEditObservation  # type: ignore[assignment]
        obs.content = "File created successfully"
        obs.old_content = None
        obs.new_content = "new file content"
        result = self.detector._extract_observation_outcome(obs)
        self.assertEqual(result, "unknown")

    def test_skipped_content_returns_no_change(self):
        """SKIPPED: prefix in content → 'no_change'."""
        obs = MagicMock(spec=Observation)
        obs.content = "SKIPPED: file already exists"
        result = self.detector._extract_observation_outcome(obs)
        self.assertEqual(result, "no_change")

    def test_already_exists_prose_is_not_semantic_signal(self):
        """Free-form 'already exists' text is not used for stuck scoring (too many false positives)."""
        obs = MagicMock(spec=Observation)
        obs.content = "Error: file already exists at /workspace/src/page.tsx"
        result = self.detector._extract_observation_outcome(obs)
        self.assertEqual(result, "unknown")

    def test_empty_content_returns_unknown(self):
        """Empty/normal observation → 'unknown'."""
        obs = MagicMock(spec=Observation)
        obs.content = ""
        result = self.detector._extract_observation_outcome(obs)
        self.assertEqual(result, "unknown")


if __name__ == "__main__":
    unittest.main()
