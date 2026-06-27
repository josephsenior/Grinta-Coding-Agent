"""Tests for manifest-based workspace checkpoint helpers."""

from __future__ import annotations

import json

from backend.execution.rollback.workspace_checkpoint import (
    restore_checkpoint,
    save_checkpoint,
)


class TestWorkspaceCheckpoint:
    def test_save_checkpoint_writes_manifest_and_files(self, tmp_path):
        workspace = tmp_path / 'workspace'
        workspace.mkdir()
        (workspace / 'app.py').write_text("print('hello')", encoding='utf-8')
        (workspace / '.git').mkdir()
        (workspace / '.git' / 'config').write_text('ignored', encoding='utf-8')

        checkpoint_dir = tmp_path / 'checkpoint'
        manifest = save_checkpoint(
            workspace,
            checkpoint_dir,
            label='before-change',
            metadata={'source': 'test'},
        )

        assert manifest.label == 'before-change'
        assert manifest.metadata == {'source': 'test'}
        assert [entry.path for entry in manifest.files] == ['app.py']

        manifest_path = checkpoint_dir / 'manifest.json'
        saved_manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        assert saved_manifest['label'] == 'before-change'
        assert saved_manifest['files'][0]['path'] == 'app.py'
        assert (checkpoint_dir / 'files' / 'app.py').read_text(encoding='utf-8') == (
            "print('hello')"
        )

    def test_save_checkpoint_skips_venv_and_git(self, tmp_path):
        workspace = tmp_path / 'workspace'
        workspace.mkdir()
        (workspace / 'app.py').write_text("print('hello')", encoding='utf-8')
        (workspace / '.venv').mkdir()
        (workspace / '.venv' / 'lib.py').write_text('big', encoding='utf-8')
        (workspace / '.git').mkdir()
        (workspace / '.git' / 'config').write_text('ignored', encoding='utf-8')

        checkpoint_dir = tmp_path / 'checkpoint'
        manifest = save_checkpoint(workspace, checkpoint_dir, label='lean')

        assert [entry.path for entry in manifest.files] == ['app.py']

    def test_restore_checkpoint_restores_files_and_quarantines_extras(self, tmp_path):
        workspace = tmp_path / 'workspace'
        workspace.mkdir()
        (workspace / 'app.py').write_text("print('hello')", encoding='utf-8')
        (workspace / 'dir').mkdir()
        (workspace / 'dir' / 'keep.txt').write_text('keep', encoding='utf-8')

        checkpoint_dir = tmp_path / 'checkpoint'
        save_checkpoint(workspace, checkpoint_dir, label='base')

        (workspace / 'app.py').write_text("print('changed')", encoding='utf-8')
        (workspace / 'dir' / 'keep.txt').unlink()
        (workspace / 'dir').rmdir()
        (workspace / 'extra.txt').write_text('extra', encoding='utf-8')

        quarantine_dir = restore_checkpoint(workspace, checkpoint_dir)

        assert quarantine_dir is not None
        assert (workspace / 'app.py').read_text(encoding='utf-8') == "print('hello')"
        assert (workspace / 'dir' / 'keep.txt').read_text(encoding='utf-8') == 'keep'
        assert not (workspace / 'extra.txt').exists()
        assert (quarantine_dir / 'extra.txt').read_text(encoding='utf-8') == 'extra'
