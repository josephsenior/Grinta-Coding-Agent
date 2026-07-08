"""Unit tests for backend.execution.rollback.rollback_manager -- checkpoint/rollback system."""

from __future__ import annotations

import json
import time

import pytest

pytest.importorskip('pygit2')  # skip entire module if pygit2 not installed

from backend.execution.rollback.rollback_manager import Checkpoint, RollbackManager  # noqa: E402
from backend.execution.rollback.shadow_repo import ShadowRepoError  # noqa: E402

# ---------------------------------------------------------------------------
# Checkpoint dataclass
# ---------------------------------------------------------------------------


class TestCheckpoint:
    def test_to_dict(self):
        cp = Checkpoint(
            id='cp1',
            timestamp=1000.0,
            description='test',
            checkpoint_type='manual',
            workspace_path='/tmp/ws',
        )
        d = cp.to_dict()
        assert d['id'] == 'cp1'
        assert d['description'] == 'test'
        assert d['git_commit_sha'] is None
        assert d['file_snapshots'] == {}

    def test_from_dict(self):
        d = {
            'id': 'cp1',
            'timestamp': 1000.0,
            'description': 'test',
            'checkpoint_type': 'auto',
            'workspace_path': '/ws',
            'metadata': {'k': 'v'},
            'git_commit_sha': 'abc123',
            'file_snapshots': {'a.py': 'saved'},
        }
        cp = Checkpoint.from_dict(d)
        assert cp.id == 'cp1'
        assert cp.git_commit_sha == 'abc123'
        assert cp.file_snapshots == {'a.py': 'saved'}

    def test_roundtrip(self):
        cp = Checkpoint(
            id='cp2',
            timestamp=2000.0,
            description='round',
            checkpoint_type='before_risky',
            workspace_path='/ws',
            metadata={'x': 1},
            git_commit_sha='sha1',
            file_snapshots={'b.py': 'saved'},
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
        ws = tmp_path / 'workspace'
        ws.mkdir()
        # Add a sample file
        (ws / 'hello.py').write_text("print('hello')")
        return ws

    def test_init_creates_dirs(self, workspace):
        rm = RollbackManager(str(workspace))
        assert rm.checkpoints_dir.exists()
        from backend.core.workspace_resolution import workspace_agent_state_dir

        assert (
            rm.checkpoints_dir
            == workspace_agent_state_dir(workspace) / 'rollback_checkpoints'
        )
        assert rm.max_checkpoints == 20

    def test_create_checkpoint(self, workspace):
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint('test cp')
        assert cp_id.startswith('cp_')
        assert len(rm.checkpoints) == 1
        assert rm.checkpoints[0].description == 'test cp'

    def test_create_checkpoint_saves_manifest(self, workspace):
        rm = RollbackManager(str(workspace))
        rm.create_checkpoint('test')
        manifest = rm.checkpoints_dir / 'manifest.json'
        assert manifest.exists()
        data = json.loads(manifest.read_text())
        assert len(data['checkpoints']) == 1

    def test_list_checkpoints(self, workspace):
        rm = RollbackManager(str(workspace))
        rm.create_checkpoint('first')
        rm.create_checkpoint('second')
        cps = rm.list_checkpoints()
        assert len(cps) == 2
        # Should be sorted by timestamp descending
        assert cps[0]['description'] == 'second'

    def test_get_checkpoint(self, workspace):
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint('find me')
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        assert cp.description == 'find me'

    def test_get_checkpoint_not_found(self, workspace):
        rm = RollbackManager(str(workspace))
        assert rm.get_checkpoint('nonexistent') is None

    def test_get_latest_checkpoint(self, workspace):
        rm = RollbackManager(str(workspace))
        rm.create_checkpoint('old')
        time.sleep(0.01)
        rm.create_checkpoint('new')
        latest = rm.get_latest_checkpoint()
        assert latest is not None
        assert latest.description == 'new'

    def test_get_latest_empty(self, workspace):
        rm = RollbackManager(str(workspace))
        assert rm.get_latest_checkpoint() is None

    def test_delete_checkpoint(self, workspace):
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint('to delete')
        assert rm.delete_checkpoint(cp_id) is True
        assert not rm.checkpoints

    def test_delete_checkpoint_not_found(self, workspace):
        rm = RollbackManager(str(workspace))
        assert rm.delete_checkpoint('nonexistent') is False

    def test_file_snapshot_created(self, workspace):
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint('snapshot')
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        # Shadow-repo backend: content is stored inside .grinta/shadow_repo,
        # not in a per-checkpoint subdirectory under checkpoints_dir.
        assert cp.git_commit_sha is not None
        assert len(cp.git_commit_sha) == 40

    def test_file_based_rollback(self, workspace):
        rm = RollbackManager(str(workspace))
        # Create checkpoint
        cp_id = rm.create_checkpoint('before change')
        # Modify workspace
        (workspace / 'hello.py').write_text("print('changed')")
        (workspace / 'new_file.py').write_text('new content')
        # Rollback
        success = rm.rollback_to(cp_id)
        assert success is True
        assert (workspace / 'hello.py').read_text() == "print('hello')"
        assert not (workspace / 'new_file.py').exists()

    def test_rollback_nonexistent(self, workspace):
        rm = RollbackManager(str(workspace))
        assert rm.rollback_to('nonexistent') is False

    def test_auto_cleanup(self, workspace):
        rm = RollbackManager(str(workspace), max_checkpoints=3, auto_cleanup=True)
        for i in range(5):
            rm.create_checkpoint(f'cp-{i}')
        assert len(rm.checkpoints) <= 3

    def test_checkpoint_type(self, workspace):
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint('risky', checkpoint_type='before_risky')
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        assert cp.checkpoint_type == 'before_risky'

    def test_phase_boundary_checkpoint_skips_file_snapshot(self, workspace):
        rm = RollbackManager(str(workspace))
        (workspace / 'app.py').write_text('print(1)', encoding='utf-8')
        cp_id = rm.create_checkpoint(
            'phase boundary: init_to_active',
            checkpoint_type='phase_boundary',
            use_git=False,
        )
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        assert cp.file_snapshots == {}
        assert not (rm.checkpoints_dir / cp_id / 'files').exists()

    def test_drvfs_workspace_skips_manual_file_snapshot(self, workspace):
        """With hard-dep shadow repo, WSL drvfs logic is removed; snapshot always runs."""
        rm = RollbackManager(str(workspace))
        (workspace / 'app.py').write_text('print(1)', encoding='utf-8')
        cp_id = rm.create_checkpoint('manual', use_git=False)
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        # Shadow repo always runs -- SHA must be present
        assert cp.git_commit_sha is not None

    def test_checkpoint_metadata(self, workspace):
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint('meta', metadata={'action': 'delete'})
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        assert cp.metadata == {'action': 'delete'}

    def test_load_checkpoints_from_manifest(self, workspace):
        rm1 = RollbackManager(str(workspace))
        rm1.create_checkpoint('persist')
        # Create a new manager — should load from manifest
        rm2 = RollbackManager(str(workspace))
        assert len(rm2.checkpoints) == 1
        assert rm2.checkpoints[0].description == 'persist'

    def test_load_checkpoints_manifest_corruption(self, workspace, monkeypatch):
        """Test graceful handling of corrupted manifest file."""
        rm = RollbackManager(str(workspace))
        rm.create_checkpoint('test')

        # Corrupt manifest by writing invalid JSON
        manifest = rm.checkpoints_dir / 'manifest.json'
        manifest.write_text('invalid json {[}]')

        # Create new manager — should handle corrupted manifest gracefully
        rm2 = RollbackManager(str(workspace))
        # Should have empty checkpoints list due to graceful error handling
        assert not rm2.checkpoints

    def test_shadow_repo_available(self, workspace):
        """vcs_available reflects shadow-repo availability (pygit2 in-process)."""
        rm = RollbackManager(str(workspace))
        # pygit2 was importable (we skip the whole module otherwise), so True.
        assert rm.vcs_available is True
        assert rm._shadow_repo is not None

    def test_shadow_repo_unavailable_raises(self, workspace, monkeypatch):
        """RollbackManager raises when ShadowRepo cannot be initialised (hard dep)."""
        def failing_init(*args, **kwargs):
            raise ImportError('pygit2 not available')

        monkeypatch.setattr(
            'backend.execution.rollback.rollback_manager.ShadowRepo', failing_init
        )
        with pytest.raises(ImportError):
            RollbackManager(str(workspace))

    def test_create_checkpoint_with_shadow_snapshot(self, workspace):
        """Checkpoint creation records a shadow SHA in git_commit_sha field."""
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint('with shadow')
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        assert cp.git_commit_sha is not None  # shadow SHA stored here
        assert len(cp.git_commit_sha) == 40

    def test_create_checkpoint_shadow_exception_graceful(self, workspace, monkeypatch):
        """Exceptions from shadow repo propagate (no silent fallback with hard dep)."""
        rm = RollbackManager(str(workspace))

        def boom(label=''):
            raise ShadowRepoError('simulated failure')

        monkeypatch.setattr(rm._shadow_repo, 'snapshot', boom)
        with pytest.raises(ShadowRepoError):
            rm.create_checkpoint('exception test')

    def test_file_snapshot_exception(self, workspace):
        """Test file snapshot exception handling - creation succeeds despite errors."""
        # Even if file iteration has errors, checkpoint creation should succeed
        # with file snapshots being empty/partial
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint('may have file snapshot errors')
        assert cp_id.startswith('cp_')
        # Checkpoint should still be created and saved
        assert rm.get_checkpoint(cp_id) is not None

    def test_save_checkpoints_exception(self, workspace, monkeypatch):
        """Test exception handling when saving manifest."""
        rm = RollbackManager(str(workspace))
        monkeypatch.setattr(
            'backend.execution.rollback.rollback_manager.json.dump',
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                PermissionError('simulated write failure')
            ),
        )

        # This should handle the exception gracefully
        # (but may still add checkpoint to list)
        cp_id = rm.create_checkpoint('save error')
        assert cp_id.startswith('cp_')

    def test_cleanup_old_checkpoints_limits(self, workspace):
        """Test cleanup enforces max_checkpoints limit."""
        rm = RollbackManager(str(workspace), max_checkpoints=5, auto_cleanup=True)

        # Create 10 checkpoints
        for i in range(10):
            rm.create_checkpoint(f'cp-{i}')

        # Should only have 5
        assert len(rm.checkpoints) == 5

        # Oldest checkpoints should be deleted
        descriptions = [cp.description for cp in rm.checkpoints]
        assert 'cp-0' not in descriptions
        assert 'cp-1' not in descriptions
        assert 'cp-9' in descriptions

    def test_cleanup_partial(self, workspace):
        """Test cleanup when under limit."""
        rm = RollbackManager(str(workspace), max_checkpoints=10, auto_cleanup=True)

        for i in range(5):
            rm.create_checkpoint(f'cp-{i}')

        # Should keep all 5
        assert len(rm.checkpoints) == 5

    def test_shadow_rollback_success(self, workspace):
        """Shadow-based rollback restores workspace correctly."""
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint('before')
        original_content = (workspace / 'hello.py').read_text()

        (workspace / 'hello.py').write_text('changed')
        success = rm.rollback_to(cp_id)

        assert success is True
        assert (workspace / 'hello.py').read_text() == original_content

    def test_shadow_rollback_fails_propagates(self, workspace, monkeypatch):
        """ShadowRepoError from restore propagates up through rollback_to."""
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint('before')

        def boom(sha, **kw):
            raise ShadowRepoError('simulated restore failure')

        monkeypatch.setattr(rm._shadow_repo, 'restore', boom)
        success = rm.rollback_to(cp_id)
        # The outer try/except in rollback_to catches it and returns False
        assert success is False

    def test_rollback_checkpoint_without_sha_returns_false(self, workspace):
        """Checkpoints with no SHA (phase-boundary) return False from rollback."""
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint('before')
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        cp.git_commit_sha = None  # simulate a phase-boundary checkpoint

        success = rm.rollback_to(cp_id)
        assert success is False

    def test_rollback_nonexistent_checkpoint(self, workspace):
        rm = RollbackManager(str(workspace))
        assert rm.rollback_to('nonexistent') is False

    def test_non_git_workspace_checkpoint_and_rollback(self, workspace):
        """Checkpoint + rollback must work on workspaces with no .git directory."""
        assert not (workspace / '.git').exists()
        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint('plain workspace')
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        assert cp.git_commit_sha is not None

        (workspace / 'hello.py').write_text('modified')
        success = rm.rollback_to(cp_id)
        assert success is True
        assert (workspace / 'hello.py').read_text() == "print('hello')"

    def test_restore_snapshot_with_nested_dirs(self, workspace):
        """Test snapshot restoration with nested directory structure."""
        # Create nested files
        nested = workspace / 'src' / 'lib'
        nested.mkdir(parents=True)
        (nested / 'util.py').write_text('def util(): pass')
        (workspace / 'main.py').write_text('import util')

        rm = RollbackManager(str(workspace))
        cp_id = rm.create_checkpoint('nested')

        # Remove files
        (nested / 'util.py').unlink()
        (workspace / 'main.py').unlink()

        success = rm.rollback_to(cp_id)
        assert success is True
        assert (nested / 'util.py').exists()
        assert (workspace / 'main.py').read_text() == 'import util'

    def test_clear_workspace_preserves_app_and_git(self, workspace):
        """Test that clear_workspace preserves .app and .git dirs."""
        # Create special directories
        workspace.joinpath('.grinta').mkdir()
        workspace.joinpath('.grinta', 'important.txt').write_text('keep')
        workspace.joinpath('.git').mkdir()
        workspace.joinpath('.git', 'HEAD').write_text('git data')

        # Create regular files
        workspace.joinpath('deleteme.txt').write_text('delete')
        workspace.joinpath('subdir').mkdir()
        workspace.joinpath('subdir', 'deleteme.py').write_text('delete')

        rm = RollbackManager(str(workspace))
        rm._clear_workspace()

        # Special dirs should exist
        assert workspace.joinpath('.grinta').exists()
        assert workspace.joinpath('.grinta', 'important.txt').exists()
        assert workspace.joinpath('.git').exists()
        assert workspace.joinpath('.git', 'HEAD').exists()

        # Regular files should be deleted
        assert not workspace.joinpath('deleteme.txt').exists()
        assert not workspace.joinpath('subdir').exists()

    def test_custom_checkpoints_dir(self, workspace):
        """Test using custom checkpoints directory."""
        custom_dir = workspace / 'custom' / 'checkpoints'
        rm = RollbackManager(str(workspace), checkpoints_dir=str(custom_dir))

        assert rm.checkpoints_dir == custom_dir
        assert custom_dir.exists()

        cp_id = rm.create_checkpoint('custom dir test')
        # Shadow backend: no per-checkpoint subdir; verify manifest was written.
        assert (custom_dir / 'manifest.json').exists()
        cp = rm.get_checkpoint(cp_id)
        assert cp is not None
        assert cp.git_commit_sha is not None

    def test_find_checkpoint_not_found(self, workspace):
        """Test _find_checkpoint with nonexistent ID."""
        rm = RollbackManager(str(workspace))
        result = rm._find_checkpoint('nonexistent')
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
        assert all(cp_id.startswith('cp_') for cp_id in ids)
