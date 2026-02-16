"""Unit tests for backend.core.rollback.rollback_manager — checkpoint/rollback system."""

from __future__ import annotations

import json
import time

import pytest

from backend.core.rollback.rollback_manager import Checkpoint, RollbackManager


# ---------------------------------------------------------------------------
# Checkpoint dataclass
# ---------------------------------------------------------------------------


class TestCheckpoint:
    def test_to_dict(self):
        cp = Checkpoint(
            id="cp1",
            timestamp=1000.0,
            description="test",
            checkpoint_type="manual",
            workspace_path="/tmp/ws",
        )
        d = cp.to_dict()
        assert d["id"] == "cp1"
        assert d["description"] == "test"
        assert d["git_commit_sha"] is None
        assert d["file_snapshots"] == {}

    def test_from_dict(self):
        d = {
            "id": "cp1",
            "timestamp": 1000.0,
            "description": "test",
            "checkpoint_type": "auto",
            "workspace_path": "/ws",
            "metadata": {"k": "v"},
            "git_commit_sha": "abc123",
            "file_snapshots": {"a.py": "saved"},
        }
        cp = Checkpoint.from_dict(d)
        assert cp.id == "cp1"
        assert cp.git_commit_sha == "abc123"
        assert cp.file_snapshots == {"a.py": "saved"}

    def test_roundtrip(self):
        cp = Checkpoint(
            id="cp2", timestamp=2000.0, description="round",
            checkpoint_type="before_risky", workspace_path="/ws",
            metadata={"x": 1}, git_commit_sha="sha1",
            file_snapshots={"b.py": "saved"},
        )
        d = cp.to_dict()
        cp2 = Checkpoint.from_dict(d)
        assert cp2.id == cp.id
        assert cp2.metadata == cp.metadata


# ---------------------------------------------------------------------------
# RollbackManager (using tmp_path for isolation)
# ---------------------------------------------------------------------------


class TestRollbackManager:
    @pytest.fixture()
    def workspace(self, tmp_path):
        ws = tmp_path / "workspace"
        ws.mkdir()
        # Add a sample file
        (ws / "hello.py").write_text("print('hello')")
        return ws

    def test_init_creates_dirs(self, workspace):
        rm = RollbackManager(str(workspace))
        assert rm.checkpoints_dir.exists()
        assert rm.max_checkpoints == 20

    def test_create_checkpoint(self, workspace):
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint("test cp")
        assert cp_id.startswith("cp_")
        assert len(rm.checkpoints) == 1
        assert rm.checkpoints[0].description == "test cp"

    def test_create_checkpoint_saves_manifest(self, workspace):
        rm = RollbackManager(str(workspace))
        rm.create_checkpoint("test")
        manifest = rm.checkpoints_dir / "manifest.json"
        assert manifest.exists()
        data = json.loads(manifest.read_text())
        assert len(data["checkpoints"]) == 1

    def test_list_checkpoints(self, workspace):
        rm = RollbackManager(str(workspace))
        rm.create_checkpoint("first")
        rm.create_checkpoint("second")
        cps = rm.list_checkpoints()
        assert len(cps) == 2
        # Should be sorted by timestamp descending
        assert cps[0]["description"] == "second"

    def test_get_checkpoint(self, workspace):
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint("find me")
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        assert cp.description == "find me"

    def test_get_checkpoint_not_found(self, workspace):
        rm = RollbackManager(str(workspace))
        assert rm.get_checkpoint("nonexistent") is None

    def test_get_latest_checkpoint(self, workspace):
        rm = RollbackManager(str(workspace))
        rm.create_checkpoint("old")
        time.sleep(0.01)
        rm.create_checkpoint("new")
        latest = rm.get_latest_checkpoint()
        assert latest is not None
        assert latest.description == "new"

    def test_get_latest_empty(self, workspace):
        rm = RollbackManager(str(workspace))
        assert rm.get_latest_checkpoint() is None

    def test_delete_checkpoint(self, workspace):
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint("to delete")
        assert rm.delete_checkpoint(cp_id) is True
        assert len(rm.checkpoints) == 0

    def test_delete_checkpoint_not_found(self, workspace):
        rm = RollbackManager(str(workspace))
        assert rm.delete_checkpoint("nonexistent") is False

    def test_file_snapshot_created(self, workspace):
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint("snapshot")
        snapshot_dir = rm.checkpoints_dir / cp_id
        assert snapshot_dir.exists()
        assert (snapshot_dir / "hello.py").exists()

    def test_file_based_rollback(self, workspace):
        rm = RollbackManager(str(workspace))
        # Create checkpoint
        cp_id = rm.create_checkpoint("before change")
        # Modify workspace
        (workspace / "hello.py").write_text("print('changed')")
        (workspace / "new_file.py").write_text("new content")
        # Rollback
        success = rm.rollback_to(cp_id)
        assert success is True
        assert (workspace / "hello.py").read_text() == "print('hello')"
        assert not (workspace / "new_file.py").exists()

    def test_rollback_nonexistent(self, workspace):
        rm = RollbackManager(str(workspace))
        assert rm.rollback_to("nonexistent") is False

    def test_auto_cleanup(self, workspace):
        rm = RollbackManager(str(workspace), max_checkpoints=3, auto_cleanup=True)
        for i in range(5):
            rm.create_checkpoint(f"cp-{i}")
        assert len(rm.checkpoints) <= 3

    def test_checkpoint_type(self, workspace):
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint("risky", checkpoint_type="before_risky")
        cp = rm.get_checkpoint(cp_id)
        assert cp.checkpoint_type == "before_risky"

    def test_checkpoint_metadata(self, workspace):
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint("meta", metadata={"action": "delete"})
        cp = rm.get_checkpoint(cp_id)
        assert cp.metadata == {"action": "delete"}

    def test_load_checkpoints_from_manifest(self, workspace):
        rm1 = RollbackManager(str(workspace))
        rm1.create_checkpoint("persist")
        # Create a new manager — should load from manifest
        rm2 = RollbackManager(str(workspace))
        assert len(rm2.checkpoints) == 1
        assert rm2.checkpoints[0].description == "persist"
