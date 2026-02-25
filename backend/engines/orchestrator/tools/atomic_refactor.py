"""Atomic Multi-File Refactoring - Transaction-Based Safe Edits.

Enables coordinated changes across multiple files with automatic rollback on failure.
All changes succeed together or fail together - no partial corrupted state.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from backend.core.logger import forge_logger as logger


@dataclass
class FileEdit:
    """A single file edit operation."""

    file_path: str
    operation: str  # "modify", "create", "delete", "rename"
    original_content: str | None = None
    new_content: str | None = None
    new_path: str | None = None  # For renames


RefactorEdit = FileEdit


@dataclass
class RefactorTransaction:
    """A transaction containing multiple file edits.

    All edits are applied atomically - either all succeed or all are rolled back.
    """

    transaction_id: str
    edits: list[FileEdit] = field(default_factory=list)
    backup_dir: str | None = None
    committed: bool = False
    rolled_back: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class RefactorResult:
    """Result of a refactoring operation."""

    success: bool
    message: str
    files_modified: int
    transaction_id: str
    errors: list[str] = field(default_factory=list)


class AtomicRefactor:
    """Atomic multi-file refactoring engine.

    Features:
    - Transaction-based editing (all or nothing)
    - Automatic backup and rollback
    - Validation before commit
    - Dry-run mode
    - Detailed error reporting

    Usage:
        refactor = AtomicRefactor()
        transaction = refactor.begin_transaction()

        transaction.add_edit("file1.py", new_content="...")
        transaction.add_edit("file2.py", new_content="...")

        result = refactor.commit(transaction, validate=True)
        if not result.success:
            refactor.rollback(transaction)
    """

    def __init__(self, backup_root: str | None = None):
        """Initialize atomic refactoring engine.

        Args:
            backup_root: Root directory for backups (uses temp if None)

        """
        self.backup_root = backup_root or tempfile.gettempdir()
        self.active_transactions: dict[str, RefactorTransaction] = {}
        self._transaction_counter = 0

    def begin_transaction(self) -> RefactorTransaction:
        """Begin a new refactoring transaction.

        Returns:
            RefactorTransaction instance

        """
        self._transaction_counter += 1
        transaction_id = f"refactor_{self._transaction_counter}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

        # Create backup directory
        backup_dir = os.path.join(self.backup_root, f"backup_{transaction_id}")
        os.makedirs(backup_dir, exist_ok=True)

        transaction = RefactorTransaction(
            transaction_id=transaction_id, backup_dir=backup_dir
        )

        self.active_transactions[transaction_id] = transaction
        logger.info("📦 Started transaction: %s", transaction_id)

        return transaction

    def add_file_edit(
        self,
        transaction: RefactorTransaction,
        file_path: str,
        new_content: str,
        operation: str = "modify",
    ) -> None:
        """Add a file edit to the transaction.

        Args:
            transaction: Transaction to add edit to
            file_path: Path to the file
            new_content: New file content
            operation: Edit operation ("modify", "create", "delete")

        """
        if transaction.committed or transaction.rolled_back:
            raise ValueError(
                f"Transaction {transaction.transaction_id} is already finalized"
            )

        # Read original content for rollback
        original_content = None
        if os.path.exists(file_path) and operation != "create":
            try:
                with open(file_path, encoding="utf-8") as f:
                    original_content = f.read()
            except Exception as e:
                logger.warning("Could not read %s for backup: %s", file_path, e)

        edit = FileEdit(
            file_path=file_path,
            operation=operation,
            original_content=original_content,
            new_content=new_content,
        )

        transaction.edits.append(edit)
        logger.debug(
            "Added %s edit for %s to transaction %s",
            operation,
            file_path,
            transaction.transaction_id,
        )

    def add_rename(
        self, transaction: RefactorTransaction, old_path: str, new_path: str
    ) -> None:
        """Add a file rename to the transaction.

        Args:
            transaction: Transaction to add rename to
            old_path: Current file path
            new_path: New file path

        """
        if transaction.committed or transaction.rolled_back:
            raise ValueError(
                f"Transaction {transaction.transaction_id} is already finalized"
            )

        # Read original content
        original_content = None
        if os.path.exists(old_path):
            try:
                with open(old_path, encoding="utf-8") as f:
                    original_content = f.read()
            except Exception as e:
                logger.warning("Could not read %s for backup: %s", old_path, e)

        edit = FileEdit(
            file_path=old_path,
            operation="rename",
            original_content=original_content,
            new_path=new_path,
        )

        transaction.edits.append(edit)
        logger.debug(
            "Added rename %s → %s to transaction %s",
            old_path,
            new_path,
            transaction.transaction_id,
        )

    def _check_transaction_state(
        self, transaction: RefactorTransaction
    ) -> RefactorResult | None:
        """Check if transaction is in valid state for committing.

        Args:
            transaction: Transaction to check

        Returns:
            RefactorResult if invalid state, None if valid

        """
        if transaction.committed:
            return RefactorResult(
                success=False,
                message="Transaction already committed",
                files_modified=0,
                transaction_id=transaction.transaction_id,
                errors=["Transaction already committed"],
            )

        if transaction.rolled_back:
            return RefactorResult(
                success=False,
                message="Transaction already rolled back",
                files_modified=0,
                transaction_id=transaction.transaction_id,
                errors=["Transaction already rolled back"],
            )

        return None

    def _create_backups(self, transaction: RefactorTransaction) -> None:
        """Create backups for all files in transaction.

        Uses the full relative path within the backup directory to avoid
        collisions when two edited files share the same basename
        (e.g. ``pkg_a/utils.py`` and ``pkg_b/utils.py``).

        Args:
            transaction: Transaction containing edits

        """
        logger.info(
            "💾 Creating backups for transaction %s", transaction.transaction_id
        )
        for edit in transaction.edits:
            if edit.original_content and transaction.backup_dir:
                # Preserve directory structure to avoid basename collisions
                safe_rel = os.path.relpath(edit.file_path).replace("..", "__parent__")
                backup_path = os.path.join(transaction.backup_dir, safe_rel)
                os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                try:
                    with open(backup_path, "w", encoding="utf-8") as f:
                        f.write(edit.original_content)
                except Exception as e:
                    logger.warning(
                        "Failed to create backup for %s: %s", edit.file_path, e
                    )

    def _apply_modify_or_create(
        self, edit: RefactorEdit, validate: bool, validator: Callable | None
    ) -> None:
        """Apply modify or create operation.

        Args:
            edit: Edit to apply
            validate: Whether to validate
            validator: Validation function

        """
        os.makedirs(os.path.dirname(edit.file_path), exist_ok=True)

        with open(edit.file_path, "w", encoding="utf-8") as f:
            f.write(edit.new_content or "")

        # Validation is now done separately in _apply_all_edits
        # This allows proper rollback if validation fails
        if validate and validator:
            if not validator(edit.file_path, edit.new_content or ""):
                raise ValueError(f"Validation failed for {edit.file_path}")

    def _apply_delete(self, edit: RefactorEdit) -> None:
        """Apply delete operation.

        Args:
            edit: Edit to apply

        """
        if os.path.exists(edit.file_path):
            os.remove(edit.file_path)

    def _apply_rename(self, edit: RefactorEdit) -> None:
        """Apply rename operation.

        Args:
            edit: Edit to apply

        """
        if os.path.exists(edit.file_path) and edit.new_path:
            os.makedirs(os.path.dirname(edit.new_path), exist_ok=True)
            shutil.move(edit.file_path, edit.new_path)

    def _apply_single_edit(
        self,
        edit: RefactorEdit,
        validate: bool,
        validator: Callable[[str, str], bool] | None,
    ) -> None:
        """Apply a single edit operation.

        Args:
            edit: Edit to apply
            validate: Whether to validate after edit
            validator: Optional validation function

        Raises:
            ValueError: If validation fails

        """
        if edit.operation in ("modify", "create"):
            self._apply_modify_or_create(edit, validate, validator)
        elif edit.operation == "delete":
            self._apply_delete(edit)
        elif edit.operation == "rename":
            self._apply_rename(edit)

    def _write_edit_content(self, edit: RefactorEdit) -> None:
        """Write file content for modify/create."""
        os.makedirs(os.path.dirname(edit.file_path), exist_ok=True)
        with open(edit.file_path, "w", encoding="utf-8") as f:
            f.write(edit.new_content or "")

    def _apply_modify_create_impl(self, edit: RefactorEdit) -> None:
        """Apply modify/create: write content to file."""
        self._write_edit_content(edit)

    def _apply_delete_impl(self, edit: RefactorEdit) -> None:
        """Apply delete: remove file if exists."""
        if os.path.exists(edit.file_path):
            os.remove(edit.file_path)

    def _apply_rename_impl(self, edit: RefactorEdit) -> None:
        """Apply rename: move file to new path."""
        if edit.new_path and os.path.exists(edit.file_path):
            os.makedirs(os.path.dirname(edit.new_path), exist_ok=True)
            shutil.move(edit.file_path, edit.new_path)

    def _apply_single_edit(
        self,
        edit: RefactorEdit,
        validate: bool,
        validator: Callable[[str, str], bool] | None,
    ) -> None:
        """Execute one edit (modify/create/delete/rename). Raises on failure."""
        if edit.operation in ("modify", "create"):
            self._apply_modify_create_impl(edit)
        elif edit.operation == "delete":
            self._apply_delete_impl(edit)
        elif edit.operation == "rename":
            self._apply_rename_impl(edit)

        if validate and validator and edit.operation in ("modify", "create"):
            if not validator(edit.file_path, edit.new_content or ""):
                raise ValueError(f"Validation failed for {edit.file_path}")

    def _apply_all_edits(
        self,
        transaction: RefactorTransaction,
        validate: bool,
        validator: Callable[[str, str], bool] | None,
    ) -> tuple[list, list[str]]:
        """Apply all edits in transaction.

        Args:
            transaction: Transaction containing edits
            validate: Whether to validate
            validator: Validation function

        Returns:
            Tuple of (applied_edits, errors)

        """
        applied_edits = []
        errors = []
        total = len(transaction.edits)

        logger.info("✏️  Applying %s edits...", total)
        for i, edit in enumerate(transaction.edits):
            try:
                self._apply_single_edit(edit, validate, validator)
                applied_edits.append(edit)
            except Exception as e:
                error_msg = (
                    f"Failed to apply edit {i + 1}/{total} "
                    f"({edit.operation} {edit.file_path}): {e}"
                )
                errors.append(error_msg)
                logger.error(error_msg)
                logger.warning("⚠️  Rolling back %s edits due to failure", len(applied_edits))
                self._rollback_edits(applied_edits, transaction)
                break

        return applied_edits, errors

    def commit(
        self,
        transaction: RefactorTransaction,
        validate: bool = True,
        validator: Callable[[str, str], bool] | None = None,
    ) -> RefactorResult:
        """Commit the transaction (apply all edits).

        Args:
            transaction: Transaction to commit
            validate: Whether to validate files after editing
            validator: Optional custom validator function(file_path, content) -> bool

        Returns:
            RefactorResult with success status

        """
        # Check transaction state
        state_error = self._check_transaction_state(transaction)
        if state_error:
            return state_error

        applied_edits: list[RefactorEdit] = []
        errors: list[str] = []

        try:
            # Phase 1: Create backups
            self._create_backups(transaction)

            # Phase 2: Apply edits
            applied_edits, errors = self._apply_all_edits(
                transaction, validate, validator
            )

            # Check if all edits succeeded
            if errors:
                return RefactorResult(
                    success=False,
                    message=f"Transaction failed and was rolled back: {errors[0]}",
                    files_modified=0,
                    transaction_id=transaction.transaction_id,
                    errors=errors,
                )

            # Success!
            transaction.committed = True
            logger.info(
                "✅ Transaction %s committed successfully (%s files)",
                transaction.transaction_id,
                len(applied_edits),
            )

            return RefactorResult(
                success=True,
                message=f"Successfully applied {len(applied_edits)} edits",
                files_modified=len(applied_edits),
                transaction_id=transaction.transaction_id,
            )

        except Exception as e:
            error_msg = f"Unexpected error during commit: {e}"
            logger.error(error_msg)

            # Attempt rollback
            self._rollback_edits(applied_edits, transaction)

            return RefactorResult(
                success=False,
                message=f"Transaction failed: {e}",
                files_modified=0,
                transaction_id=transaction.transaction_id,
                errors=errors,
            )

    def rollback(self, transaction: RefactorTransaction) -> RefactorResult:
        """Rollback a transaction (restore original state).

        Args:
            transaction: Transaction to rollback

        Returns:
            RefactorResult with rollback status

        """
        if transaction.rolled_back:
            return RefactorResult(
                success=False,
                message="Transaction already rolled back",
                files_modified=0,
                transaction_id=transaction.transaction_id,
                errors=["Already rolled back"],
            )

        logger.info("🔄 Rolling back transaction %s", transaction.transaction_id)

        try:
            self._rollback_edits(transaction.edits, transaction)
            transaction.rolled_back = True

            return RefactorResult(
                success=True,
                message=f"Rolled back {len(transaction.edits)} edits",
                files_modified=len(transaction.edits),
                transaction_id=transaction.transaction_id,
            )

        except Exception as e:
            logger.error("Rollback failed: %s", e)
            return RefactorResult(
                success=False,
                message=f"Rollback failed: {e}",
                files_modified=0,
                transaction_id=transaction.transaction_id,
                errors=[str(e)],
            )

    def _rollback_modify_edit(self, edit: FileEdit) -> None:
        """Rollback a MODIFY edit.

        Args:
            edit: Edit to rollback

        """
        if edit.original_content is not None:
            with open(edit.file_path, "w", encoding="utf-8") as f:
                f.write(edit.original_content)
            logger.debug("Restored %s", edit.file_path)

    def _rollback_create_edit(self, edit: FileEdit) -> None:
        """Rollback a CREATE edit.

        Args:
            edit: Edit to rollback

        """
        if os.path.exists(edit.file_path):
            os.remove(edit.file_path)
            logger.debug("Removed created file %s", edit.file_path)

    def _rollback_delete_edit(
        self, edit: FileEdit, transaction: RefactorTransaction
    ) -> None:
        """Rollback a DELETE edit.

        Args:
            edit: Edit to rollback
            transaction: Transaction context

        """
        if edit.original_content and transaction.backup_dir:
            with open(edit.file_path, "w", encoding="utf-8") as f:
                f.write(edit.original_content)
            logger.debug("Restored deleted file %s", edit.file_path)

    def _rollback_rename_edit(self, edit: FileEdit) -> None:
        """Rollback a RENAME edit.

        Args:
            edit: Edit to rollback

        """
        if edit.new_path and os.path.exists(edit.new_path):
            shutil.move(edit.new_path, edit.file_path)
            logger.debug("Reversed rename %s → %s", edit.new_path, edit.file_path)

    def _rollback_single_edit(
        self, edit: FileEdit, transaction: RefactorTransaction
    ) -> None:
        """Rollback a single edit.

        Args:
            edit: Edit to rollback
            transaction: Transaction context

        """
        if edit.operation == "modify":
            self._rollback_modify_edit(edit)
        elif edit.operation == "create":
            self._rollback_create_edit(edit)
        elif edit.operation == "delete":
            self._rollback_delete_edit(edit, transaction)
        elif edit.operation == "rename":
            self._rollback_rename_edit(edit)

    def _rollback_edits(
        self, edits: list[FileEdit], transaction: RefactorTransaction
    ) -> None:
        """Rollback a list of edits."""
        for edit in reversed(edits):
            try:
                self._rollback_single_edit(edit, transaction)
            except Exception as e:
                logger.error("Failed to rollback edit for %s: %s", edit.file_path, e)

    def dry_run(self, transaction: RefactorTransaction) -> RefactorResult:
        """Simulate transaction without actually applying edits.

        Args:
            transaction: Transaction to simulate

        Returns:
            RefactorResult with dry-run status

        """
        errors = []

        # Check if files exist and are writable
        for edit in transaction.edits:
            if edit.operation in ("modify", "delete", "rename"):
                if not os.path.exists(edit.file_path):
                    errors.append(f"File does not exist: {edit.file_path}")
                elif not os.access(edit.file_path, os.W_OK):
                    errors.append(f"File is not writable: {edit.file_path}")

            if edit.operation == "create":
                if os.path.exists(edit.file_path):
                    errors.append(f"File already exists: {edit.file_path}")

                # Check if directory is writable
                dir_path = os.path.dirname(edit.file_path)
                if dir_path and not os.access(dir_path, os.W_OK):
                    errors.append(f"Directory is not writable: {dir_path}")

        if errors:
            return RefactorResult(
                success=False,
                message="Dry-run found issues",
                files_modified=0,
                transaction_id=transaction.transaction_id,
                errors=errors,
            )

        return RefactorResult(
            success=True,
            message=f"Dry-run passed: {len(transaction.edits)} edits would be applied",
            files_modified=len(transaction.edits),
            transaction_id=transaction.transaction_id,
        )

    def cleanup_transaction(self, transaction: RefactorTransaction) -> None:
        """Clean up transaction resources (backups).

        Args:
            transaction: Transaction to clean up

        """
        if transaction.backup_dir and os.path.exists(transaction.backup_dir):
            try:
                shutil.rmtree(transaction.backup_dir)
                logger.debug("Cleaned up backup directory: %s", transaction.backup_dir)
            except Exception as e:
                logger.warning("Failed to clean up backup directory: %s", e)

        self.active_transactions.pop(transaction.transaction_id, None)

    def get_active_transactions(self) -> list[RefactorTransaction]:
        """Get list of active transactions."""
        return list(self.active_transactions.values())
