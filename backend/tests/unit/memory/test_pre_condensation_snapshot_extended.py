"""Tests for pre_condensation_snapshot covering attempted approaches extraction."""

from __future__ import annotations
import unittest
from backend.memory.pre_condensation_snapshot import extract_snapshot
from backend.events.action.commands import CmdRunAction
from backend.events.action.files import FileEditAction
from backend.events.observation.commands import CmdOutputObservation
from backend.events.observation.error import ErrorObservation
from backend.events.observation.files import FileEditObservation

class TestPreCondensationSnapshot(unittest.TestCase):
    def test_extract_snapshot_attempted_approaches(self):
        # Setup events
        events = [
            CmdRunAction(command="pip install flask"),
            CmdOutputObservation(content="Successfully installed", command="pip install flask", exit_code=0),

            FileEditAction(path="test.py", command="replace_text", old_str="old", new_str="new"),
            ErrorObservation(content="Match not found"),

            CmdRunAction(command="pytest"),
            CmdOutputObservation(content="FAILED tests/test_x.py", command="pytest", exit_code=1)
        ]

        # Run
        snapshot = extract_snapshot(events)

        # Verify
        approaches = snapshot["attempted_approaches"]
        assert len(approaches) == 3

        # Success command
        assert approaches[0]["type"] == "command"
        assert "pip install flask" in approaches[0]["detail"]
        assert approaches[0]["outcome"] == "SUCCESS"

        # Failed file edit
        assert approaches[1]["type"] == "file_edit"
        assert "test.py" in approaches[1]["detail"]
        assert "FAILED" in approaches[1]["outcome"]

        # Failed command
        assert approaches[2]["type"] == "command"
        assert "pytest" in approaches[2]["detail"]
        assert "FAILED (exit=1)" in approaches[2]["outcome"]

    def test_format_snapshot_for_injection(self):
        from backend.memory.pre_condensation_snapshot import format_snapshot_for_injection

        snapshot = {
            "events_condensed": 10,
            "files_touched": {"test.py": {"action": "edit"}},
            "attempted_approaches": [
                {"type": "command", "detail": "pytest", "outcome": "FAILED (exit=1): FAILED tests/test_x.py"}
            ]
        }

        formatted = format_snapshot_for_injection(snapshot)
        assert "<RESTORED_CONTEXT>" in formatted
        assert "Events condensed: 10" in formatted
        assert "test.py" in formatted
        assert "FAILED approaches" in formatted
        assert "pytest" in formatted

    def test_file_edit_observation_benign_error_word_is_success(self):
        """Diff/code mentioning 'error' must not mark the approach as FAILED."""
        events = [
            FileEditAction(path="app.py", command="replace_text", old_str="a", new_str="b"),
            FileEditObservation(
                content="+def handle_error():\n    pass\n",
                path="app.py",
            ),
        ]
        snapshot = extract_snapshot(events)
        approaches = snapshot["attempted_approaches"]
        assert len(approaches) == 1
        assert approaches[0]["outcome"] == "SUCCESS"

    def test_file_edit_observation_skipped_prefix_is_failure(self):
        events = [
            FileEditAction(path="x.py", command="create_file", old_str="", new_str=""),
            FileEditObservation(
                content="SKIPPED: file already exists",
                path="x.py",
            ),
        ]
        snapshot = extract_snapshot(events)
        assert snapshot["attempted_approaches"][0]["outcome"].startswith("FAILED")
