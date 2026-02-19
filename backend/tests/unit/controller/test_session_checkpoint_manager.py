"""Tests for backend.controller.state.session_checkpoint_manager."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from backend.controller.state.session_checkpoint_manager import SessionCheckpointManager


# ===================================================================
# Helpers
# ===================================================================


def _make_file_store():
    fs = MagicMock()
    fs.write = MagicMock()
    fs.read = MagicMock()
    fs.delete = MagicMock()
    fs.list = MagicMock(return_value=[])
    return fs


def _make_state(json_str: str = '{"key": "value"}'):
    state = MagicMock()
    state._to_json_str.return_value = json_str
    return state


# ===================================================================
# save_checkpoint
# ===================================================================


class TestSaveCheckpoint:
    def test_basic_save(self):
        fs = _make_file_store()
        mgr = SessionCheckpointManager(sid="s1", file_store=fs)
        state = _make_state()
        mgr.save_checkpoint("after_research", state)
        fs.write.assert_called_once()
        path, data = fs.write.call_args[0]
        assert "after_research" in path
        assert path.endswith(".json")
        assert data == '{"key": "value"}'

    def test_name_sanitization(self):
        fs = _make_file_store()
        mgr = SessionCheckpointManager(sid="s1", file_store=fs)
        state = _make_state()
        mgr.save_checkpoint("../../etc/passwd", state)
        path = fs.write.call_args[0][0]
        # Path traversal chars should be stripped
        assert ".." not in path
        assert "/" not in path.split("checkpoints/")[-1].replace(".json", "").replace(
            "etcpasswd", ""
        )

    def test_empty_name_after_sanitize_raises(self):
        fs = _make_file_store()
        mgr = SessionCheckpointManager(sid="s1", file_store=fs)
        state = _make_state()
        with pytest.raises(ValueError, match="Invalid checkpoint name"):
            mgr.save_checkpoint("!!!", state)

    def test_fallback_when_no_to_json_str(self):
        fs = _make_file_store()
        mgr = SessionCheckpointManager(sid="s1", file_store=fs)
        state = MagicMock(spec=[])  # No _to_json_str attribute
        state.__dict__ = {"x": 1, "y": "two"}
        mgr.save_checkpoint("cp1", state)
        written = fs.write.call_args[0][1]
        data = json.loads(written)
        assert data["x"] == 1

    def test_file_store_error_propagates(self):
        fs = _make_file_store()
        fs.write.side_effect = OSError("disk full")
        mgr = SessionCheckpointManager(sid="s1", file_store=fs)
        state = _make_state()
        with pytest.raises(OSError):
            mgr.save_checkpoint("cp1", state)


# ===================================================================
# list_checkpoints
# ===================================================================


class TestListCheckpoints:
    def test_lists_json_files(self):
        fs = _make_file_store()
        fs.list.return_value = [
            "after_research.json",
            "before_deploy.json",
            "notes.txt",
        ]
        mgr = SessionCheckpointManager(sid="s1", file_store=fs)
        names = mgr.list_checkpoints()
        assert names == ["after_research", "before_deploy"]

    def test_empty_when_no_directory(self):
        fs = _make_file_store()
        fs.list.side_effect = FileNotFoundError
        mgr = SessionCheckpointManager(sid="s1", file_store=fs)
        assert mgr.list_checkpoints() == []


# ===================================================================
# restore_checkpoint
# ===================================================================


class TestRestoreCheckpoint:
    def test_restore_success(self):
        fs = _make_file_store()
        fs.read.return_value = '{"state_data": true}'
        mgr = SessionCheckpointManager(sid="s1", file_store=fs)
        with patch("backend.controller.state.state.State") as MockState:
            mock_state = MagicMock()
            MockState._from_raw.return_value = mock_state
            result = mgr.restore_checkpoint("cp1")
            assert result is mock_state

    def test_restore_not_found(self):
        fs = _make_file_store()
        fs.read.side_effect = FileNotFoundError
        mgr = SessionCheckpointManager(sid="s1", file_store=fs)
        result = mgr.restore_checkpoint("nonexistent")
        assert result is None

    def test_restore_corrupt_data(self):
        fs = _make_file_store()
        fs.read.return_value = "not valid json"
        mgr = SessionCheckpointManager(sid="s1", file_store=fs)
        with patch("backend.controller.state.state.State") as MockState:
            MockState._from_raw.side_effect = json.JSONDecodeError("err", "doc", 0)
            result = mgr.restore_checkpoint("corrupt")
            assert result is None

    def test_restore_sanitizes_name(self):
        fs = _make_file_store()
        fs.read.return_value = '{"x": 1}'
        mgr = SessionCheckpointManager(sid="s1", file_store=fs)
        with patch("backend.controller.state.state.State") as MockState:
            MockState._from_raw.return_value = MagicMock()
            mgr.restore_checkpoint("../../../etc/shadow")
            path = fs.read.call_args[0][0]
            assert ".." not in path


# ===================================================================
# delete_checkpoint
# ===================================================================


class TestDeleteCheckpoint:
    def test_delete_success(self):
        fs = _make_file_store()
        mgr = SessionCheckpointManager(sid="s1", file_store=fs)
        mgr.delete_checkpoint("old_cp")
        fs.delete.assert_called_once()
        path = fs.delete.call_args[0][0]
        assert "old_cp.json" in path

    def test_delete_error_logged(self):
        fs = _make_file_store()
        fs.delete.side_effect = OSError("permission denied")
        mgr = SessionCheckpointManager(sid="s1", file_store=fs)
        # Should not raise
        mgr.delete_checkpoint("old_cp")

    def test_delete_sanitizes_name(self):
        fs = _make_file_store()
        mgr = SessionCheckpointManager(sid="s1", file_store=fs)
        mgr.delete_checkpoint("../../bad")
        path = fs.delete.call_args[0][0]
        assert ".." not in path
