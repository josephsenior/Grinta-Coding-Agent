"""Tests for stale-read prevention in FileVerificationGuard."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.engines.orchestrator.file_verification_guard import FileVerificationGuard


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_edit_action(path: str) -> MagicMock:
    """Create a mock file edit action."""
    action = MagicMock()
    action.path = path
    action.action = "edit"
    type(action).__name__ = "FileEditAction"
    return action


# ---------------------------------------------------------------------------
# is_stale_read
# ---------------------------------------------------------------------------


class TestIsStaleRead:
    def setup_method(self):
        self.g = FileVerificationGuard()

    def test_never_read_file_is_stale(self):
        """A file that was never read should be considered stale."""
        assert self.g.is_stale_read("main.py", current_turn=5) is True

    def test_recently_read_file_not_stale(self):
        """A file read on the current turn should not be stale."""
        self.g.record_file_read("main.py", turn=5)
        assert self.g.is_stale_read("main.py", current_turn=5) is False

    def test_read_within_threshold_not_stale(self):
        """A file read within the threshold should not be stale."""
        self.g.record_file_read("main.py", turn=3)
        # default threshold is 5, so turn 8 is within threshold
        assert self.g.is_stale_read("main.py", current_turn=8) is False

    def test_read_beyond_threshold_is_stale(self):
        """A file read more than threshold turns ago should be stale."""
        self.g.record_file_read("main.py", turn=1)
        # default threshold is 5, so turn 7 exceeds threshold
        assert self.g.is_stale_read("main.py", current_turn=7) is True

    def test_modified_after_read_is_stale(self):
        """A file modified after the last read should be stale."""
        self.g.record_file_read("main.py", turn=3)
        self.g.record_file_modification("main.py", turn=5)
        assert self.g.is_stale_read("main.py", current_turn=5) is True

    def test_read_after_modification_not_stale(self):
        """A file re-read after modification should not be stale."""
        self.g.record_file_modification("main.py", turn=3)
        self.g.record_file_read("main.py", turn=5)
        assert self.g.is_stale_read("main.py", current_turn=5) is False

    def test_modification_without_read_is_stale(self):
        """A modified-but-never-read file should be stale."""
        self.g.record_file_modification("main.py", turn=2)
        assert self.g.is_stale_read("main.py", current_turn=3) is True


# ---------------------------------------------------------------------------
# record_file_read / record_file_modification
# ---------------------------------------------------------------------------


class TestRecordTracking:
    def setup_method(self):
        self.g = FileVerificationGuard()

    def test_read_updates_tracking(self):
        self.g.record_file_read("a.py", turn=3)
        assert self.g._file_read_turns["a.py"] == 3

    def test_read_overwrites_earlier(self):
        self.g.record_file_read("a.py", turn=1)
        self.g.record_file_read("a.py", turn=5)
        assert self.g._file_read_turns["a.py"] == 5

    def test_modification_updates_tracking(self):
        self.g.record_file_modification("b.py", turn=4)
        assert self.g._file_modified_turns["b.py"] == 4

    def test_reset_clears_tracking(self):
        self.g.record_file_read("a.py", turn=1)
        self.g.record_file_modification("b.py", turn=2)
        self.g.reset()
        assert len(self.g._file_read_turns) == 0
        assert len(self.g._file_modified_turns) == 0


# ---------------------------------------------------------------------------
# inject_verification_commands with stale-read prevention
# ---------------------------------------------------------------------------


class TestStaleReadInjection:
    def setup_method(self):
        self.g = FileVerificationGuard()

    def test_stale_file_gets_read_injected_before_edit(self):
        """Editing a never-read file should inject a read before the edit."""
        action = _make_edit_action("/src/main.py")
        with patch.object(
            self.g, "_create_verification_command", return_value=MagicMock()
        ):
            result = self.g.inject_verification_commands([action], turn=5)
        # Should have: stale-read action + original action + verification
        assert len(result) >= 2
        # First action should be the stale-read (it has "STALE-READ" in thought)
        first = result[0]
        assert "STALE-READ" in getattr(first, "thought", "")

    def test_recently_read_file_no_extra_read(self):
        """Editing a recently-read file should NOT inject an extra read."""
        self.g.record_file_read("/src/main.py", turn=4)
        action = _make_edit_action("/src/main.py")
        with patch.object(
            self.g, "_create_verification_command", return_value=MagicMock()
        ):
            result = self.g.inject_verification_commands([action], turn=5)
        # Should only have: original action + verification (no stale-read)
        # Check that no action has "STALE-READ" in its thought
        stale_reads = [a for a in result if "STALE-READ" in getattr(a, "thought", "")]
        assert len(stale_reads) == 0

    def test_stale_reads_prevented_stat_incremented(self):
        """Stale-read prevention should increment the stat counter."""
        action = _make_edit_action("/src/new.py")
        with patch.object(
            self.g, "_create_verification_command", return_value=MagicMock()
        ):
            self.g.inject_verification_commands([action], turn=3)
        assert self.g.stats["stale_reads_prevented"] >= 1


# ---------------------------------------------------------------------------
# get_stats includes tracking info
# ---------------------------------------------------------------------------


class TestStaleReadStats:
    def test_stats_include_tracked_reads(self):
        g = FileVerificationGuard()
        g.record_file_read("a.py", turn=1)
        g.record_file_read("b.py", turn=2)
        stats = g.get_stats()
        assert stats["tracked_reads"] == 2

    def test_stats_include_tracked_modifications(self):
        g = FileVerificationGuard()
        g.record_file_modification("c.py", turn=3)
        stats = g.get_stats()
        assert stats["tracked_modifications"] == 1

    def test_stale_reads_prevented_in_stats(self):
        g = FileVerificationGuard()
        stats = g.get_stats()
        assert "stale_reads_prevented" in stats
