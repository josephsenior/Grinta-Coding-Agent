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
            id="cp2",
            timestamp=2000.0,
            description="round",
            checkpoint_type="before_risky",
            workspace_path="/ws",
            metadata={"x": 1},
            git_commit_sha="sha1",
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
        assert not rm.checkpoints

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
        assert cp is not None
        assert cp.checkpoint_type == "before_risky"

    def test_checkpoint_metadata(self, workspace):
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint("meta", metadata={"action": "delete"})
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        assert cp.metadata == {"action": "delete"}

    def test_load_checkpoints_from_manifest(self, workspace):
        rm1 = RollbackManager(str(workspace))
        rm1.create_checkpoint("persist")
        # Create a new manager — should load from manifest
        rm2 = RollbackManager(str(workspace))
        assert len(rm2.checkpoints) == 1
        assert rm2.checkpoints[0].description == "persist"

    def test_load_checkpoints_manifest_corruption(self, workspace, monkeypatch):
        """Test graceful handling of corrupted manifest file."""
        rm = RollbackManager(str(workspace))
        rm.create_checkpoint("test")

        # Corrupt manifest by writing invalid JSON
        manifest = rm.checkpoints_dir / "manifest.json"
        manifest.write_text("invalid json {[}]")

        # Create new manager — should handle corrupted manifest gracefully
        rm2 = RollbackManager(str(workspace))
        # Should have empty checkpoints list due to graceful error handling
        assert not rm2.checkpoints

    def test_git_available_check_failure(self, workspace, monkeypatch):
        """Test when git command fails."""

        def mock_subprocess_run(*args, **kwargs):
            class Result:
                returncode = 1
                stderr = "not a git repo"
                stdout = ""

            return Result()

        monkeypatch.setattr("subprocess.run", mock_subprocess_run)
        rm = RollbackManager(str(workspace))
        assert rm.vcs_available is False

    def test_git_available_check_exception(self, workspace, monkeypatch):
        """Test when git command raises exception."""

        def mock_subprocess_run(*args, **kwargs):
            raise RuntimeError("git not found")

        monkeypatch.setattr("subprocess.run", mock_subprocess_run)
        rm = RollbackManager(str(workspace))
        assert rm.vcs_available is False

    def test_create_checkpoint_with_git_snapshot(self, workspace, monkeypatch):
        """Test checkpoint creation when git is available."""

        def mock_subprocess_run(cmd, *args, **kwargs):
            class Result:
                returncode = 0
                stdout = "abc123def456\n"
                stderr = ""

            # For git rev-parse --git-dir
            if "rev-parse" in cmd and "--git-dir" in cmd:
                return Result()
            # For git add
            if "add" in cmd:
                result = Result()
                result.returncode = 0
                return result
            # For git commit
            if "commit" in cmd:
                result = Result()
                result.returncode = 0
                return result
            # For git rev-parse HEAD
            if "rev-parse" in cmd and "HEAD" in cmd:
                result = Result()
                result.returncode = 0
                result.stdout = "abc123def456\n"
                return result
            return Result()

        monkeypatch.setattr("subprocess.run", mock_subprocess_run)
        rm = RollbackManager(str(workspace))
        assert rm.vcs_available is True

        cp_id = rm.create_checkpoint("with git")
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        assert cp.git_commit_sha == "abc123def456"

    def test_create_checkpoint_git_disabled(self, workspace, monkeypatch):
        """Test checkpoint creation with use_git=False."""

        def mock_subprocess_run(cmd, *args, **kwargs):
            class Result:
                returncode = 0
                stdout = "abc123\n"
                stderr = ""

            if "rev-parse" in cmd and "--git-dir" in cmd:
                return Result()
            return Result()

        monkeypatch.setattr("subprocess.run", mock_subprocess_run)
        rm = RollbackManager(str(workspace))
        assert rm.vcs_available is True

        # Create with use_git=False
        cp_id = rm.create_checkpoint("no git", use_git=False)
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        assert cp.git_commit_sha is None

    def test_create_git_snapshot_fails(self, workspace, monkeypatch):
        """Test git snapshot creation failure."""

        def mock_subprocess_run(cmd, *args, **kwargs):
            class Result:
                returncode = 0
                stdout = "abc123\n"
                stderr = ""

            if "rev-parse" in cmd and "--git-dir" in cmd:
                return Result()

            # Fail the commit
            if "commit" in cmd:
                result = Result()
                result.returncode = 1
                result.stderr = "nothing to commit"
                return result

            return Result()

        monkeypatch.setattr("subprocess.run", mock_subprocess_run)
        rm = RollbackManager(str(workspace))
        assert rm.vcs_available is True

        cp_id = rm.create_checkpoint("failed git")
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        # git_commit_sha should be None when commit fails
        assert cp.git_commit_sha is None

    def test_create_git_snapshot_sha_read_fails(self, workspace, monkeypatch):
        """Test when git commit succeeds but reading SHA fails."""

        def mock_subprocess_run(cmd, *args, **kwargs):
            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            if "rev-parse" in cmd and "--git-dir" in cmd:
                return Result()

            # Commit succeeds
            if "commit" in cmd:
                result = Result()
                result.returncode = 0
                return result

            # But reading HEAD SHA fails
            if "rev-parse" in cmd and "HEAD" in cmd:
                result = Result()
                result.returncode = 1
                result.stderr = "failed"
                return result

            return Result()

        monkeypatch.setattr("subprocess.run", mock_subprocess_run)
        rm = RollbackManager(str(workspace))

        cp_id = rm.create_checkpoint("sha read fail")
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        assert cp.git_commit_sha is None

    def test_create_git_snapshot_exception(self, workspace, monkeypatch):
        """Test git snapshot exception handling."""

        def mock_subprocess_run(cmd, *args, **kwargs):
            if "rev-parse" in cmd and "--git-dir" in cmd:

                class Result:
                    returncode = 0

                return Result()
            raise RuntimeError("git subprocess error")

        monkeypatch.setattr("subprocess.run", mock_subprocess_run)
        rm = RollbackManager(str(workspace))
        assert rm.vcs_available is True

        # Should not crash, git snapshot should return None
        cp_id = rm.create_checkpoint("git exception")
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        assert cp.git_commit_sha is None

    def test_file_snapshot_exception(self, workspace):
        """Test file snapshot exception handling - creation succeeds despite errors."""
        # Even if file iteration has errors, checkpoint creation should succeed
        # with file snapshots being empty/partial
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint("may have file snapshot errors")
        assert cp_id.startswith("cp_")
        # Checkpoint should still be created and saved
        assert rm.get_checkpoint(cp_id) is not None

    def test_save_checkpoints_exception(self, workspace, monkeypatch):
        """Test exception handling when saving manifest."""
        rm = RollbackManager(str(workspace))

        # Make checkpoints_dir read-only to trigger write error
        import stat

        original_mode = rm.checkpoints_dir.stat().st_mode

        try:
            # Make directory read-only
            rm.checkpoints_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)

            # This should handle the exception gracefully
            # (but may still add checkpoint to list)
            cp_id = rm.create_checkpoint("save error")
            assert cp_id.startswith("cp_")
        finally:
            # Restore permissions
            rm.checkpoints_dir.chmod(original_mode)

    def test_cleanup_old_checkpoints_limits(self, workspace):
        """Test cleanup enforces max_checkpoints limit."""
        rm = RollbackManager(str(workspace), max_checkpoints=5, auto_cleanup=True)

        # Create 10 checkpoints
        for i in range(10):
            rm.create_checkpoint(f"cp-{i}")

        # Should only have 5
        assert len(rm.checkpoints) == 5

        # Oldest checkpoints should be deleted
        descriptions = [cp.description for cp in rm.checkpoints]
        assert "cp-0" not in descriptions
        assert "cp-1" not in descriptions
        assert "cp-9" in descriptions

    def test_cleanup_partial(self, workspace):
        """Test cleanup when under limit."""
        rm = RollbackManager(str(workspace), max_checkpoints=10, auto_cleanup=True)

        for i in range(5):
            rm.create_checkpoint(f"cp-{i}")

        # Should keep all 5
        assert len(rm.checkpoints) == 5

    def test_git_rollback_success(self, workspace, monkeypatch):
        """Test successful git-based rollback."""

        def mock_subprocess_run(cmd, *args, **kwargs):
            class Result:
                returncode = 0
                stdout = "abc123\n"
                stderr = ""

            if "rev-parse" in cmd and "--git-dir" in cmd:
                return Result()
            if "commit" in cmd:
                return Result()
            if "reset" in cmd and "hard" in cmd:
                return Result()
            if "rev-parse" in cmd:
                return Result()
            return Result()

        monkeypatch.setattr("subprocess.run", mock_subprocess_run)
        rm = RollbackManager(str(workspace))

        cp_id = rm.create_checkpoint("before")
        success = rm.rollback_to(cp_id)
        assert success is True

    def test_git_rollback_failure_fallback_to_file(self, workspace):
        """Test that file rollback is used when git rollback fails."""
        rm = RollbackManager(str(workspace))

        cp_id = rm.create_checkpoint("before")
        assert rm.get_checkpoint(cp_id) is not None

        # Manually create scenario where git_commit_sha is None (no git)
        # by creating a checkpoint without git available
        checkpoint = rm.get_checkpoint(cp_id)
        assert checkpoint is not None
        checkpoint.git_commit_sha = None  # Simulate failed git snapshot

        # Modify workspace
        (workspace / "new.txt").write_text("new")

        # Should use file-based rollback
        success = rm.rollback_to(cp_id)
        assert success is True
        # File-based rollback should have restored original state
        assert not (workspace / "new.txt").exists()

    def test_git_rollback_without_sha(self, workspace, monkeypatch):
        """Test git rollback when commit sha is None."""

        def mock_subprocess_run(cmd, *args, **kwargs):
            class Result:
                returncode = 0
                stdout = ""
                stderr = ""

            if "rev-parse" in cmd and "--git-dir" in cmd:
                return Result()
            # Commit fails, so git_commit_sha will be None
            if "commit" in cmd:
                result = Result()
                result.returncode = 1
                return result

            return Result()

        monkeypatch.setattr("subprocess.run", mock_subprocess_run)
        rm = RollbackManager(str(workspace))

        cp_id = rm.create_checkpoint("no sha")
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        assert cp.git_commit_sha is None

        # Should fall back to file-based rollback
        (workspace / "test.txt").write_text("modified")
        success = rm.rollback_to(cp_id)
        assert success is True

    def test_rollback_git_not_available(self, workspace, monkeypatch):
        """Test rollback when vcs_available is False."""

        def mock_subprocess_run(cmd, *args, **kwargs):
            class Result:
                returncode = 1

            if "rev-parse" in cmd and "--git-dir" in cmd:
                return Result()
            return Result()

        monkeypatch.setattr("subprocess.run", mock_subprocess_run)
        rm = RollbackManager(str(workspace))
        assert rm.vcs_available is False

        cp_id = rm.create_checkpoint("no git available")
        (workspace / "file.txt").write_text("modified")

        success = rm.rollback_to(cp_id)
        assert success is True
        assert not (workspace / "file.txt").exists()

    def test_file_based_rollback_missing_snapshot(self, workspace):
        """Test file-based rollback when snapshot dir is missing."""
        rm = RollbackManager(str(workspace))

        # Manually create a fake checkpoint without creating snapshot
        from backend.core.rollback.rollback_manager import Checkpoint

        fake_cp = Checkpoint(
            id="fake_cp",
            timestamp=1000.0,
            description="fake",
            checkpoint_type="manual",
            workspace_path=str(workspace),
            file_snapshots={},
            git_commit_sha=None,
        )
        rm.checkpoints.append(fake_cp)

        success = rm.rollback_to("fake_cp")
        assert success is False

    def test_restore_snapshot_with_nested_dirs(self, workspace):
        """Test snapshot restoration with nested directory structure."""
        # Create nested files
        nested = workspace / "src" / "lib"
        nested.mkdir(parents=True)
        (nested / "util.py").write_text("def util(): pass")
        (workspace / "main.py").write_text("import util")

        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint("nested")

        # Remove files
        (nested / "util.py").unlink()
        (workspace / "main.py").unlink()

        success = rm.rollback_to(cp_id)
        assert success is True
        assert (nested / "util.py").exists()
        assert (workspace / "main.py").read_text() == "import util"

    def test_clear_workspace_preserves_forge_and_git(self, workspace):
        """Test that clear_workspace preserves .Forge and .git dirs."""
        # Create special directories
        workspace.joinpath(".Forge").mkdir()
        workspace.joinpath(".Forge", "important.txt").write_text("keep")
        workspace.joinpath(".git").mkdir()
        workspace.joinpath(".git", "HEAD").write_text("git data")

        # Create regular files
        workspace.joinpath("deleteme.txt").write_text("delete")
        workspace.joinpath("subdir").mkdir()
        workspace.joinpath("subdir", "deleteme.py").write_text("delete")

        rm = RollbackManager(str(workspace))
        rm._clear_workspace()

        # Special dirs should exist
        assert workspace.joinpath(".Forge").exists()
        assert workspace.joinpath(".Forge", "important.txt").exists()
        assert workspace.joinpath(".git").exists()
        assert workspace.joinpath(".git", "HEAD").exists()

        # Regular files should be deleted
        assert not workspace.joinpath("deleteme.txt").exists()
        assert not workspace.joinpath("subdir").exists()

    def test_custom_checkpoints_dir(self, workspace):
        """Test using custom checkpoints directory."""
        custom_dir = workspace / "custom" / "checkpoints"
        rm = RollbackManager(str(workspace), checkpoints_dir=str(custom_dir))

        assert rm.checkpoints_dir == custom_dir
        assert custom_dir.exists()

        cp_id = rm.create_checkpoint("custom dir test")
        assert (custom_dir / cp_id).exists()

    def test_find_checkpoint_not_found(self, workspace):
        """Test _find_checkpoint with nonexistent ID."""
        rm = RollbackManager(str(workspace))
        result = rm._find_checkpoint("nonexistent")
        assert result is None

    def test_checkpoint_id_uniqueness(self, workspace):
        """Test that generated checkpoint IDs are unique."""
        rm = RollbackManager(str(workspace))

        ids = []
        for _ in range(10):
            cp_id = rm._generate_checkpoint_id()
            ids.append(cp_id)

        # All IDs should be unique
        assert len(ids) == len(set(ids))

        # All should have correct prefix
        assert all(cp_id.startswith("cp_") for cp_id in ids)
