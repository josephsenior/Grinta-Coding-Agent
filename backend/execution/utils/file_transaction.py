"""File transaction manager for atomic multi-file operations.

Provides rollback support for file operations to prevent partial state
when multi-file operations fail mid-way.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from backend.core.logger import app_logger as logger

if TYPE_CHECKING:
    from backend.execution.base import Runtime


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
        if self.backup_dir and os.path.exists(self.backup_dir):
            try:
                shutil.rmtree(self.backup_dir)
                logger.debug('Cleaned up transaction backup dir: %s', self.backup_dir)
            except Exception as e:
                logger.warning('Failed to cleanup transaction backup: %s', e)

    async def write_file(self, file_path: str, content: str) -> None:
        """Write a file within the transaction.

        Args:
            file_path: Absolute path to the file
            content: File content to write

        """
        # Check if file exists and backup current content
        existed_before = os.path.exists(file_path)
        old_content = None

        if existed_before:
            try:
                with open(file_path, encoding='utf-8') as f:  # noqa: ASYNC230
                    old_content = f.read()

                # Create backup
                if self.backup_dir:
                    backup_path = os.path.join(
                        self.backup_dir, os.path.basename(file_path)
                    )
                    with open(backup_path, 'w', encoding='utf-8') as f:  # noqa: ASYNC230
                        f.write(old_content)
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
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'w', encoding='utf-8') as f:  # noqa: ASYNC230
                f.write(content)
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
        if not os.path.exists(file_path):
            raise FileNotFoundError(f'Cannot edit non-existent file: {file_path}')

        # Backup current content
        try:
            with open(file_path, encoding='utf-8') as f:  # noqa: ASYNC230
                old_content = f.read()

            # Create backup
            if self.backup_dir:
                backup_path = os.path.join(self.backup_dir, os.path.basename(file_path))
                with open(backup_path, 'w', encoding='utf-8') as f:  # noqa: ASYNC230
                    f.write(old_content)
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
            with open(file_path, 'w', encoding='utf-8') as f:  # noqa: ASYNC230
                f.write(new_content)
            logger.debug('Edited file in transaction: %s', file_path)
        except Exception as e:
            logger.error('Failed to edit file %s: %s', file_path, e)
            raise

    async def delete_file(self, file_path: str) -> None:
        """Delete a file within the transaction.

        Args:
            file_path: Absolute path to the file

        """
        if not os.path.exists(file_path):
            logger.warning('Cannot delete non-existent file: %s', file_path)
            return

        # Backup current content before deletion
        try:
            with open(file_path, encoding='utf-8') as f:  # noqa: ASYNC230
                old_content = f.read()

            # Create backup
            if self.backup_dir:
                backup_path = os.path.join(self.backup_dir, os.path.basename(file_path))
                with open(backup_path, 'w', encoding='utf-8') as f:  # noqa: ASYNC230
                    f.write(old_content)
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
        if operation.existed_before and operation.old_content is not None:
            with open(operation.file_path, 'w', encoding='utf-8') as f:
                f.write(operation.old_content)
            logger.debug('Restored original content: %s', operation.file_path)
        else:
            if os.path.exists(operation.file_path):
                os.remove(operation.file_path)
                logger.debug('Deleted newly created file: %s', operation.file_path)

    def _rollback_edit_operation(self, operation) -> None:
        """Rollback an EDIT operation.

        Args:
            operation: File operation to rollback

        """
        if operation.old_content is not None:
            with open(operation.file_path, 'w', encoding='utf-8') as f:
                f.write(operation.old_content)
            logger.debug('Restored edited file: %s', operation.file_path)

    def _rollback_delete_operation(self, operation) -> None:
        """Rollback a DELETE operation.

        Args:
            operation: File operation to rollback

        """
        if operation.old_content is not None:
            os.makedirs(os.path.dirname(operation.file_path), exist_ok=True)
            with open(operation.file_path, 'w', encoding='utf-8') as f:
                f.write(operation.old_content)
            logger.debug('Restored deleted file: %s', operation.file_path)

    async def rollback(self) -> None:
        """Rollback all file operations in reverse order."""
        logger.warning('Rolling back %s file operations', len(self.operations))

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
"""
async with FileTransaction(runtime) as txn:
    await txn.write_file("/workspace/Component.tsx", tsx_content)
    await txn.write_file("/workspace/Component.test.tsx", test_content)
    await txn.write_file("/workspace/Component.css", css_content)
    # If any write fails, all 3 files are rolled back
"""
