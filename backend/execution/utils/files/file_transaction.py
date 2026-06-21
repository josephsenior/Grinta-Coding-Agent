"""File transaction manager for atomic multi-file operations.

Provides rollback support for file operations to prevent partial state
when multi-file operations fail mid-way.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from backend.core.logging.logger import app_logger as logger
from backend.core.os_capabilities import OS_CAPS
from backend.utils.async_helpers.async_utils import call_sync_from_async

if TYPE_CHECKING:
    from backend.execution.server.base import Runtime


_FILE_LOCKS: dict[str, threading.RLock] = {}
_FILE_LOCKS_GUARD = threading.Lock()


def _lock_key(file_path: str) -> str:
    try:
        return str(Path(file_path).resolve())
    except OSError:
        return os.path.abspath(file_path)


def _file_lock_for_path(file_path: str) -> threading.RLock:
    key = _lock_key(file_path)
    with _FILE_LOCKS_GUARD:
        lock = _FILE_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _FILE_LOCKS[key] = lock
        return lock


def _atomic_write_text(file_path: str, content: str) -> None:
    parent = os.path.dirname(os.path.abspath(file_path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    fd: int | None = None
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(
            prefix=f'.{os.path.basename(file_path)}.',
            suffix='.tmp',
            dir=parent or None,
            text=True,
        )
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            fd = None
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, file_path)
        _fsync_parent_dir(parent)
        tmp_path = None
    finally:
        if fd is not None:
            os.close(fd)
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                logger.warning('Failed to remove transaction temp file: %s', tmp_path)


def _fsync_parent_dir(parent: str) -> None:
    if OS_CAPS.is_windows or not parent:
        return
    with contextlib.suppress(OSError, AttributeError):
        dir_fd = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


class FileOperationType(Enum):
    """Type of file operation in a transaction."""

    WRITE = 'write'
    EDIT = 'edit'
    DELETE = 'delete'


@dataclass
class FileOperation:
    """Represents a single file operation in a transaction."""

    operation_type: FileOperationType
    file_path: str
    new_content: str | None = None
    old_content: str | None = None
    existed_before: bool = False


@dataclass
class FileTransaction:
    """Transaction manager for atomic file operations.

    Usage:
        async with FileTransaction(runtime) as txn:
            await txn.write_file("/workspace/file1.txt", "content1")
            await txn.write_file("/workspace/file2.txt", "content2")
            # If any operation fails, all changes are rolled back
    """

    runtime: Runtime
    operations: list[FileOperation] = field(default_factory=list)
    backup_dir: str | None = None
    committed: bool = False

    async def __aenter__(self) -> FileTransaction:
        """Enter transaction context."""
        # Create temporary backup directory
        self.backup_dir = tempfile.mkdtemp(prefix='app_txn_')
        logger.info('Started file transaction with backup dir: %s', self.backup_dir)
        return self

    async def __aexit__(self, exc_type, exc_value, traceback) -> None:
        """Exit transaction context, committing or rolling back."""
        if exc_type is not None:
            # Exception occurred - rollback all changes
            logger.error(
                'File transaction failed: %s, rolling back %s operations',
                exc_value,
                len(self.operations),
            )
            await self.rollback()
        elif not self.committed:
            # No exception, but commit wasn't called explicitly - auto-commit
            logger.info(
                'Auto-committing file transaction with %s operations',
                len(self.operations),
            )
            self.committed = True

        # Cleanup backup directory
        if self.backup_dir and os.path.exists(self.backup_dir):  # noqa: ASYNC240
            try:
                await call_sync_from_async(shutil.rmtree, self.backup_dir)
                logger.debug('Cleaned up transaction backup dir: %s', self.backup_dir)
            except Exception as e:
                logger.warning('Failed to cleanup transaction backup: %s', e)

    async def write_file(self, file_path: str, content: str) -> None:
        """Write a file within the transaction.

        Args:
            file_path: Absolute path to the file
            content: File content to write

        """
        await call_sync_from_async(self._write_file_sync, file_path, content)

    def _write_file_sync(self, file_path: str, content: str) -> None:
        """Synchronous write implementation guarded by a per-file lock."""
        with _file_lock_for_path(file_path):
            self._write_file_locked(file_path, content)

    def _write_file_locked(self, file_path: str, content: str) -> None:
        # Check if file exists and backup current content
        existed_before = os.path.exists(file_path)
        old_content = None

        if existed_before:
            try:
                with open(file_path, encoding='utf-8') as f:
                    old_content = f.read()

                # Create backup
                if self.backup_dir:
                    backup_path = os.path.join(
                        self.backup_dir, os.path.basename(file_path)
                    )
                    _atomic_write_text(backup_path, old_content)
            except Exception as e:
                logger.warning('Failed to backup file %s: %s', file_path, e)

        # Record operation
        operation = FileOperation(
            operation_type=FileOperationType.WRITE,
            file_path=file_path,
            new_content=content,
            old_content=old_content,
            existed_before=existed_before,
        )
        self.operations.append(operation)

        # Execute write
        try:
            _atomic_write_text(file_path, content)
            logger.debug('Wrote file in transaction: %s', file_path)
        except Exception as e:
            logger.error('Failed to write file %s: %s', file_path, e)
            raise

    async def edit_file(self, file_path: str, new_content: str) -> None:
        """Edit an existing file within the transaction.

        Args:
            file_path: Absolute path to the file
            new_content: New file content

        """
        await call_sync_from_async(self._edit_file_sync, file_path, new_content)

    def _edit_file_sync(self, file_path: str, new_content: str) -> None:
        """Synchronous edit implementation guarded by a per-file lock."""
        with _file_lock_for_path(file_path):
            self._edit_file_locked(file_path, new_content)

    def _edit_file_locked(self, file_path: str, new_content: str) -> None:
        if not os.path.exists(file_path):
            raise FileNotFoundError(f'Cannot edit non-existent file: {file_path}')

        # Backup current content
        try:
            with open(file_path, encoding='utf-8') as f:
                old_content = f.read()

            # Create backup
            if self.backup_dir:
                backup_path = os.path.join(self.backup_dir, os.path.basename(file_path))
                _atomic_write_text(backup_path, old_content)
        except Exception as e:
            logger.error('Failed to backup file for edit %s: %s', file_path, e)
            raise

        # Record operation
        operation = FileOperation(
            operation_type=FileOperationType.EDIT,
            file_path=file_path,
            new_content=new_content,
            old_content=old_content,
            existed_before=True,
        )
        self.operations.append(operation)

        # Execute edit
        try:
            _atomic_write_text(file_path, new_content)
            logger.debug('Edited file in transaction: %s', file_path)
        except Exception as e:
            logger.error('Failed to edit file %s: %s', file_path, e)
            raise

    async def delete_file(self, file_path: str) -> None:
        """Delete a file within the transaction.

        Args:
            file_path: Absolute path to the file

        """
        await call_sync_from_async(self._delete_file_sync, file_path)

    def _delete_file_sync(self, file_path: str) -> None:
        """Synchronous delete implementation guarded by a per-file lock."""
        with _file_lock_for_path(file_path):
            self._delete_file_locked(file_path)

    def _delete_file_locked(self, file_path: str) -> None:
        if not os.path.exists(file_path):
            logger.warning('Cannot delete non-existent file: %s', file_path)
            return

        # Backup current content before deletion
        old_content = None
        try:
            with open(file_path, encoding='utf-8') as f:
                old_content = f.read()

            # Create backup
            if self.backup_dir:
                backup_path = os.path.join(self.backup_dir, os.path.basename(file_path))
                _atomic_write_text(backup_path, old_content)
        except Exception as e:
            logger.warning('Failed to backup file for deletion %s: %s', file_path, e)

        # Record operation
        operation = FileOperation(
            operation_type=FileOperationType.DELETE,
            file_path=file_path,
            old_content=old_content,
            existed_before=True,
        )
        self.operations.append(operation)

        # Execute deletion
        try:
            os.remove(file_path)
            logger.debug('Deleted file in transaction: %s', file_path)
        except Exception as e:
            logger.error('Failed to delete file %s: %s', file_path, e)
            raise

    async def commit(self) -> None:
        """Explicitly commit the transaction.

        This is optional - transactions auto-commit on success.
        """
        self.committed = True
        logger.info(
            'Committed file transaction with %s operations', len(self.operations)
        )

    def _rollback_write_operation(self, operation) -> None:
        """Rollback a WRITE operation.

        Args:
            operation: File operation to rollback

        """
        with _file_lock_for_path(operation.file_path):
            if operation.existed_before and operation.old_content is not None:
                _atomic_write_text(operation.file_path, operation.old_content)
                logger.debug('Restored original content: %s', operation.file_path)
            elif os.path.exists(operation.file_path):
                os.remove(operation.file_path)
                logger.debug('Deleted newly created file: %s', operation.file_path)

    def _rollback_edit_operation(self, operation) -> None:
        """Rollback an EDIT operation.

        Args:
            operation: File operation to rollback

        """
        with _file_lock_for_path(operation.file_path):
            if operation.old_content is not None:
                _atomic_write_text(operation.file_path, operation.old_content)
                logger.debug('Restored edited file: %s', operation.file_path)

    def _rollback_delete_operation(self, operation) -> None:
        """Rollback a DELETE operation.

        Args:
            operation: File operation to rollback

        """
        with _file_lock_for_path(operation.file_path):
            if operation.old_content is not None:
                _atomic_write_text(operation.file_path, operation.old_content)
                logger.debug('Restored deleted file: %s', operation.file_path)

    async def rollback(self) -> None:
        """Rollback all file operations in reverse order."""
        logger.warning('Rolling back %s file operations', len(self.operations))

        await call_sync_from_async(self._rollback_sync)

    def _rollback_sync(self) -> None:
        for operation in reversed(self.operations):
            try:
                if operation.operation_type == FileOperationType.WRITE:
                    self._rollback_write_operation(operation)
                elif operation.operation_type == FileOperationType.EDIT:
                    self._rollback_edit_operation(operation)
                elif operation.operation_type == FileOperationType.DELETE:
                    self._rollback_delete_operation(operation)
            except Exception as e:
                logger.error(
                    'Failed to rollback operation %s on %s: %s',
                    operation.operation_type,
                    operation.file_path,
                    e,
                )

        logger.info('Rollback completed for %s operations', len(self.operations))


# Example usage in agent code:
#
# async with FileTransaction(runtime) as txn:
#     await txn.write_file("/workspace/Component.tsx", tsx_content)
#     await txn.write_file("/workspace/Component.test.tsx", test_content)
#     await txn.write_file("/workspace/Component.css", css_content)
#     # If any write fails, all 3 files are rolled back
