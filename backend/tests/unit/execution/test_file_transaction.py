"""Tests for backend.execution.utils.file_transaction — FileTransaction."""

from __future__ import annotations

import os
import tempfile

import pytest

from backend.execution.utils.file_transaction import (
    FileOperation,
    FileOperationType,
    FileTransaction,
)

# ===================================================================
# FileOperationType enum
# ===================================================================


class TestFileOperationType:
    def test_values(self):
        assert FileOperationType.WRITE.value == 'write'
        assert FileOperationType.EDIT.value == 'edit'
        assert FileOperationType.DELETE.value == 'delete'


# ===================================================================
# FileOperation dataclass
# ===================================================================


class TestFileOperation:
    def test_defaults(self):
        op = FileOperation(
            operation_type=FileOperationType.WRITE,
            file_path='/workspace/a.txt',
        )
        assert op.new_content is None
        assert op.old_content is None
        assert op.existed_before is False

    def test_full_construction(self):
        op = FileOperation(
            operation_type=FileOperationType.EDIT,
            file_path='/workspace/b.txt',
            new_content='new',
            old_content='old',
            existed_before=True,
        )
        assert op.new_content == 'new'
        assert op.old_content == 'old'
        assert op.existed_before is True


# ===================================================================
# FileTransaction — write / edit / delete / rollback
# ===================================================================


async def _raise_value_error(message: str) -> None:
    raise ValueError(message)


class TestFileTransaction:
    @pytest.fixture()
    def workspace(self, tmp_path):
        """Create a temp workspace directory."""
        return str(tmp_path)

    @pytest.mark.asyncio
    async def test_write_new_file(self, workspace):
        txn = FileTransaction(runtime=None)  # type: ignore[arg-type]
        txn.backup_dir = tempfile.mkdtemp()
        file_path = os.path.join(workspace, 'new.txt')

        await txn.write_file(file_path, 'hello world')

        assert os.path.exists(file_path)
        with open(file_path, encoding='utf-8') as f:
            assert f.read() == 'hello world'
        assert len(txn.operations) == 1
        assert txn.operations[0].existed_before is False

    @pytest.mark.asyncio
    async def test_write_existing_file_backups(self, workspace):
        file_path = os.path.join(workspace, 'existing.txt')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('original')

        txn = FileTransaction(runtime=None)  # type: ignore[arg-type]
        txn.backup_dir = tempfile.mkdtemp()

        await txn.write_file(file_path, 'updated')

        assert txn.operations[0].old_content == 'original'
        assert txn.operations[0].existed_before is True
        with open(file_path, encoding='utf-8') as f:
            assert f.read() == 'updated'

    @pytest.mark.asyncio
    async def test_edit_file(self, workspace):
        file_path = os.path.join(workspace, 'edit_me.txt')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('before')

        txn = FileTransaction(runtime=None)  # type: ignore[arg-type]
        txn.backup_dir = tempfile.mkdtemp()

        await txn.edit_file(file_path, 'after')

        with open(file_path, encoding='utf-8') as f:
            assert f.read() == 'after'
        assert txn.operations[0].operation_type == FileOperationType.EDIT

    @pytest.mark.asyncio
    async def test_edit_nonexistent_raises(self, workspace):
        txn = FileTransaction(runtime=None)  # type: ignore[arg-type]
        txn.backup_dir = tempfile.mkdtemp()

        with pytest.raises(FileNotFoundError):
            await txn.edit_file(os.path.join(workspace, 'no_such.txt'), 'x')

    @pytest.mark.asyncio
    async def test_delete_file(self, workspace):
        file_path = os.path.join(workspace, 'delete_me.txt')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('bye')

        txn = FileTransaction(runtime=None)  # type: ignore[arg-type]
        txn.backup_dir = tempfile.mkdtemp()

        await txn.delete_file(file_path)
        assert not os.path.exists(file_path)
        assert txn.operations[0].operation_type == FileOperationType.DELETE

    @pytest.mark.asyncio
    async def test_delete_nonexistent_is_noop(self, workspace):
        txn = FileTransaction(runtime=None)  # type: ignore[arg-type]
        txn.backup_dir = tempfile.mkdtemp()

        # Should not raise
        await txn.delete_file(os.path.join(workspace, 'ghost.txt'))
        assert not txn.operations

    @pytest.mark.asyncio
    async def test_rollback_write_new_file(self, workspace):
        file_path = os.path.join(workspace, 'rollback_new.txt')
        txn = FileTransaction(runtime=None)  # type: ignore[arg-type]
        txn.backup_dir = tempfile.mkdtemp()

        await txn.write_file(file_path, 'should be removed')
        assert os.path.exists(file_path)

        await txn.rollback()
        assert not os.path.exists(file_path)

    @pytest.mark.asyncio
    async def test_rollback_write_existing_file(self, workspace):
        file_path = os.path.join(workspace, 'rollback_existing.txt')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('original content')

        txn = FileTransaction(runtime=None)  # type: ignore[arg-type]
        txn.backup_dir = tempfile.mkdtemp()

        await txn.write_file(file_path, 'new content')
        await txn.rollback()

        with open(file_path, encoding='utf-8') as f:
            assert f.read() == 'original content'

    @pytest.mark.asyncio
    async def test_rollback_edit(self, workspace):
        file_path = os.path.join(workspace, 'rollback_edit.txt')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('before edit')

        txn = FileTransaction(runtime=None)  # type: ignore[arg-type]
        txn.backup_dir = tempfile.mkdtemp()

        await txn.edit_file(file_path, 'after edit')
        await txn.rollback()

        with open(file_path, encoding='utf-8') as f:
            assert f.read() == 'before edit'

    @pytest.mark.asyncio
    async def test_rollback_delete(self, workspace):
        file_path = os.path.join(workspace, 'rollback_delete.txt')
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write('resurrection')

        txn = FileTransaction(runtime=None)  # type: ignore[arg-type]
        txn.backup_dir = tempfile.mkdtemp()

        await txn.delete_file(file_path)
        assert not os.path.exists(file_path)

        await txn.rollback()
        assert os.path.exists(file_path)
        with open(file_path, encoding='utf-8') as f:
            assert f.read() == 'resurrection'

    @pytest.mark.asyncio
    async def test_commit(self, workspace):
        txn = FileTransaction(runtime=None)  # type: ignore[arg-type]
        txn.backup_dir = tempfile.mkdtemp()

        assert txn.committed is False
        await txn.commit()
        assert txn.committed is True

    @pytest.mark.asyncio
    async def test_context_manager_auto_commit(self, workspace):
        txn = FileTransaction(runtime=None)  # type: ignore[arg-type]
        txn.backup_dir = tempfile.mkdtemp()
        txn.operations = []

        async with txn:
            pass

        assert txn.committed is True

    @pytest.mark.asyncio
    async def test_context_manager_uses_app_transaction_prefix(self, workspace):
        txn = FileTransaction(runtime=None)  # type: ignore[arg-type]

        async with txn:
            assert txn.backup_dir is not None
            assert os.path.basename(txn.backup_dir).startswith('app_txn_')

    @pytest.mark.asyncio
    async def test_context_manager_rollback_on_exception(self, workspace):
        file_path = os.path.join(workspace, 'ctx_rollback.txt')

        txn = FileTransaction(runtime=None)  # type: ignore[arg-type]
        txn.backup_dir = tempfile.mkdtemp()

        with pytest.raises(ValueError, match='boom'):
            async with txn:
                await txn.write_file(file_path, 'temporary')
                await _raise_value_error('boom')
        # Should have been rolled back
        assert not os.path.exists(file_path)

    @pytest.mark.asyncio
    async def test_multiple_operations_rollback_in_reverse(self, workspace):
        f1 = os.path.join(workspace, 'multi1.txt')
        f2 = os.path.join(workspace, 'multi2.txt')

        txn = FileTransaction(runtime=None)  # type: ignore[arg-type]
        txn.backup_dir = tempfile.mkdtemp()

        await txn.write_file(f1, 'file1')
        await txn.write_file(f2, 'file2')

        assert os.path.exists(f1) and os.path.exists(f2)

        await txn.rollback()

        assert not os.path.exists(f1)
        assert not os.path.exists(f2)
