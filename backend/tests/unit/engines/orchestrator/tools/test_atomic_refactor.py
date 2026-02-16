"""Tests for backend/engines/orchestrator/tools/atomic_refactor.py."""

import os
import shutil
import tempfile
import pytest

from backend.engines.orchestrator.tools.atomic_refactor import (
    FileEdit,
    RefactorEdit,
    RefactorTransaction,
    RefactorResult,
    AtomicRefactor,
)


class TestFileEdit:
    """Test FileEdit dataclass."""

    def test_create_modify_edit(self):
        """Test creating a modify edit."""
        edit = FileEdit(
            file_path="/tmp/test.py",
            operation="modify",
            original_content="old",
            new_content="new",
        )

        assert edit.file_path == "/tmp/test.py"
        assert edit.operation == "modify"
        assert edit.original_content == "old"
        assert edit.new_content == "new"
        assert edit.new_path is None

    def test_create_rename_edit(self):
        """Test creating a rename edit."""
        edit = FileEdit(
            file_path="/tmp/old.py",
            operation="rename",
            original_content="content",
            new_path="/tmp/new.py",
        )

        assert edit.operation == "rename"
        assert edit.new_path == "/tmp/new.py"

    def test_refactor_edit_alias(self):
        """Test that RefactorEdit is an alias for FileEdit."""
        assert RefactorEdit is FileEdit


class TestRefactorTransaction:
    """Test RefactorTransaction dataclass."""

    def test_create_transaction(self):
        """Test creating a transaction."""
        txn = RefactorTransaction(transaction_id="test_123")

        assert txn.transaction_id == "test_123"
        assert txn.edits == []
        assert txn.backup_dir is None
        assert txn.committed is False
        assert txn.rolled_back is False
        assert isinstance(txn.timestamp, str)

    def test_transaction_with_edits(self):
        """Test transaction with edits."""
        edit = FileEdit(file_path="/tmp/test.py", operation="modify")
        txn = RefactorTransaction(
            transaction_id="test_123",
            edits=[edit],
            backup_dir="/tmp/backup",
        )

        assert len(txn.edits) == 1
        assert txn.backup_dir == "/tmp/backup"


class TestRefactorResult:
    """Test RefactorResult dataclass."""

    def test_success_result(self):
        """Test creating a success result."""
        result = RefactorResult(
            success=True,
            message="All good",
            files_modified=3,
            transaction_id="txn_123",
        )

        assert result.success is True
        assert result.message == "All good"
        assert result.files_modified == 3
        assert result.errors == []

    def test_failure_result_with_errors(self):
        """Test creating a failure result with errors."""
        result = RefactorResult(
            success=False,
            message="Failed",
            files_modified=0,
            transaction_id="txn_123",
            errors=["Error 1", "Error 2"],
        )

        assert result.success is False
        assert len(result.errors) == 2


class TestAtomicRefactor:
    """Test AtomicRefactor class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.refactor = AtomicRefactor(backup_root=self.temp_dir)

    def teardown_method(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            shutil.rmtree(self.temp_dir)

    def test_initialization(self):
        """Test AtomicRefactor initialization."""
        refactor = AtomicRefactor()
        assert refactor.backup_root == tempfile.gettempdir()
        assert refactor.active_transactions == {}
        assert refactor._transaction_counter == 0

    def test_initialization_with_custom_backup_root(self):
        """Test initialization with custom backup root."""
        custom_root = "/custom/backup"
        refactor = AtomicRefactor(backup_root=custom_root)
        assert refactor.backup_root == custom_root

    def test_begin_transaction(self):
        """Test beginning a transaction."""
        txn = self.refactor.begin_transaction()

        assert txn.transaction_id.startswith("refactor_1_")
        assert txn.backup_dir is not None
        assert os.path.exists(txn.backup_dir)
        assert txn in self.refactor.active_transactions.values()

    def test_multiple_transactions_increment_counter(self):
        """Test that multiple transactions increment counter."""
        txn1 = self.refactor.begin_transaction()
        txn2 = self.refactor.begin_transaction()

        assert txn1.transaction_id.startswith("refactor_1_")
        assert txn2.transaction_id.startswith("refactor_2_")
        assert len(self.refactor.active_transactions) == 2

    def test_add_file_edit_modify(self):
        """Test adding a modify edit to a transaction."""
        # Create a test file
        test_file = os.path.join(self.temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("original content")

        txn = self.refactor.begin_transaction()
        self.refactor.add_file_edit(txn, test_file, "new content", operation="modify")

        assert len(txn.edits) == 1
        edit = txn.edits[0]
        assert edit.file_path == test_file
        assert edit.operation == "modify"
        assert edit.original_content == "original content"
        assert edit.new_content == "new content"

    def test_add_file_edit_create(self):
        """Test adding a create edit."""
        test_file = os.path.join(self.temp_dir, "new_file.txt")
        txn = self.refactor.begin_transaction()
        self.refactor.add_file_edit(txn, test_file, "content", operation="create")

        assert len(txn.edits) == 1
        edit = txn.edits[0]
        assert edit.operation == "create"
        assert edit.original_content is None

    def test_add_file_edit_to_finalized_transaction_raises(self):
        """Test that adding edit to finalized transaction raises error."""
        txn = self.refactor.begin_transaction()
        txn.committed = True

        with pytest.raises(ValueError, match="already finalized"):
            self.refactor.add_file_edit(txn, "/tmp/test.txt", "content")

    def test_add_rename(self):
        """Test adding a rename operation."""
        old_path = os.path.join(self.temp_dir, "old.txt")
        new_path = os.path.join(self.temp_dir, "new.txt")

        with open(old_path, "w") as f:
            f.write("content")

        txn = self.refactor.begin_transaction()
        self.refactor.add_rename(txn, old_path, new_path)

        assert len(txn.edits) == 1
        edit = txn.edits[0]
        assert edit.operation == "rename"
        assert edit.file_path == old_path
        assert edit.new_path == new_path
        assert edit.original_content == "content"

    def test_commit_modify_operation(self):
        """Test committing a modify operation."""
        test_file = os.path.join(self.temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("original")

        txn = self.refactor.begin_transaction()
        self.refactor.add_file_edit(txn, test_file, "modified", operation="modify")
        result = self.refactor.commit(txn, validate=False)

        assert result.success is True
        assert result.files_modified == 1
        assert txn.committed is True

        with open(test_file) as f:
            assert f.read() == "modified"

    def test_commit_create_operation(self):
        """Test committing a create operation."""
        test_file = os.path.join(self.temp_dir, "created.txt")
        txn = self.refactor.begin_transaction()
        self.refactor.add_file_edit(txn, test_file, "new file", operation="create")
        result = self.refactor.commit(txn, validate=False)

        assert result.success is True
        assert os.path.exists(test_file)
        with open(test_file) as f:
            assert f.read() == "new file"

    def test_commit_delete_operation(self):
        """Test committing a delete operation."""
        test_file = os.path.join(self.temp_dir, "to_delete.txt")
        with open(test_file, "w") as f:
            f.write("delete me")

        txn = self.refactor.begin_transaction()
        # Manually add delete edit
        txn.edits.append(FileEdit(
            file_path=test_file,
            operation="delete",
            original_content="delete me",
        ))
        result = self.refactor.commit(txn, validate=False)

        assert result.success is True
        assert not os.path.exists(test_file)

    def test_commit_rename_operation(self):
        """Test committing a rename operation."""
        old_path = os.path.join(self.temp_dir, "old.txt")
        new_path = os.path.join(self.temp_dir, "new.txt")

        with open(old_path, "w") as f:
            f.write("content")

        txn = self.refactor.begin_transaction()
        self.refactor.add_rename(txn, old_path, new_path)
        result = self.refactor.commit(txn, validate=False)

        assert result.success is True
        assert not os.path.exists(old_path)
        assert os.path.exists(new_path)

    def test_commit_with_validation_success(self):
        """Test commit with validation that passes."""
        test_file = os.path.join(self.temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("original")

        def validator(filepath, content):
            return len(content) > 0

        txn = self.refactor.begin_transaction()
        self.refactor.add_file_edit(txn, test_file, "valid", operation="modify")
        result = self.refactor.commit(txn, validate=True, validator=validator)

        assert result.success is True

    def test_commit_with_validation_failure_rolls_back(self):
        """Test that validation failure triggers rollback."""
        test_file = os.path.join(self.temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("original")

        def failing_validator(filepath, content):
            return False  # Always fail

        txn = self.refactor.begin_transaction()
        self.refactor.add_file_edit(txn, test_file, "invalid", operation="modify")
        result = self.refactor.commit(txn, validate=True, validator=failing_validator)

        assert result.success is False
        # Check that file was rolled back
        with open(test_file) as f:
            assert f.read() == "original"

    def test_commit_already_committed_transaction(self):
        """Test committing an already committed transaction."""
        txn = self.refactor.begin_transaction()
        txn.committed = True

        result = self.refactor.commit(txn)

        assert result.success is False
        assert "already committed" in result.message.lower()

    def test_commit_rolled_back_transaction(self):
        """Test committing an already rolled back transaction."""
        txn = self.refactor.begin_transaction()
        txn.rolled_back = True

        result = self.refactor.commit(txn)

        assert result.success is False
        assert "already rolled back" in result.message.lower()

    def test_rollback_transaction(self):
        """Test rolling back a transaction."""
        test_file = os.path.join(self.temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("original")

        txn = self.refactor.begin_transaction()
        self.refactor.add_file_edit(txn, test_file, "modified", operation="modify")

        # Commit then rollback
        self.refactor.commit(txn, validate=False)
        result = self.refactor.rollback(txn)

        assert result.success is True
        assert txn.rolled_back is True
        # File should be restored
        with open(test_file) as f:
            assert f.read() == "original"

    def test_rollback_modify_edit(self):
        """Test rollback restores original content."""
        test_file = os.path.join(self.temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("original")

        txn = self.refactor.begin_transaction()
        self.refactor.add_file_edit(txn, test_file, "modified", operation="modify")
        self.refactor.commit(txn, validate=False)

        # Manually trigger rollback
        self.refactor._rollback_edits(txn.edits, txn)

        with open(test_file) as f:
            assert f.read() == "original"

    def test_rollback_create_edit_removes_file(self):
        """Test that rollback removes created files."""
        test_file = os.path.join(self.temp_dir, "created.txt")
        txn = self.refactor.begin_transaction()
        self.refactor.add_file_edit(txn, test_file, "content", operation="create")
        self.refactor.commit(txn, validate=False)

        # Rollback should remove the file
        self.refactor._rollback_edits(txn.edits, txn)

        assert not os.path.exists(test_file)

    def test_rollback_rename_reverses_operation(self):
        """Test that rollback reverses rename."""
        old_path = os.path.join(self.temp_dir, "old.txt")
        new_path = os.path.join(self.temp_dir, "new.txt")

        with open(old_path, "w") as f:
            f.write("content")

        txn = self.refactor.begin_transaction()
        self.refactor.add_rename(txn, old_path, new_path)
        self.refactor.commit(txn, validate=False)

        # Rollback should restore old name
        self.refactor._rollback_edits(txn.edits, txn)

        assert os.path.exists(old_path)
        assert not os.path.exists(new_path)

    def test_dry_run_success(self):
        """Test dry-run with valid operations."""
        test_file = os.path.join(self.temp_dir, "test.txt")
        with open(test_file, "w") as f:
            f.write("original")

        txn = self.refactor.begin_transaction()
        self.refactor.add_file_edit(txn, test_file, "new", operation="modify")
        result = self.refactor.dry_run(txn)

        assert result.success is True
        assert result.files_modified == 1
        # File should not be modified
        with open(test_file) as f:
            assert f.read() == "original"

    def test_dry_run_detects_missing_file(self):
        """Test dry-run detects missing files for modify."""
        txn = self.refactor.begin_transaction()
        self.refactor.add_file_edit(
            txn,
            "/nonexistent/file.txt",
            "content",
            operation="modify",
        )
        result = self.refactor.dry_run(txn)

        assert result.success is False
        assert len(result.errors) > 0
        assert "does not exist" in result.errors[0]

    def test_dry_run_detects_existing_file_for_create(self):
        """Test dry-run detects existing files for create operation."""
        test_file = os.path.join(self.temp_dir, "exists.txt")
        with open(test_file, "w") as f:
            f.write("exists")

        txn = self.refactor.begin_transaction()
        self.refactor.add_file_edit(txn, test_file, "new", operation="create")
        result = self.refactor.dry_run(txn)

        assert result.success is False
        assert "already exists" in result.errors[0]

    def test_cleanup_transaction(self):
        """Test cleaning up transaction resources."""
        txn = self.refactor.begin_transaction()
        backup_dir = txn.backup_dir

        self.refactor.cleanup_transaction(txn)

        assert not os.path.exists(backup_dir)
        assert txn.transaction_id not in self.refactor.active_transactions

    def test_get_active_transactions(self):
        """Test getting active transactions."""
        txn1 = self.refactor.begin_transaction()
        txn2 = self.refactor.begin_transaction()

        active = self.refactor.get_active_transactions()

        assert len(active) == 2
        assert txn1 in active
        assert txn2 in active

    def test_multiple_edits_in_transaction(self):
        """Test committing transaction with multiple edits."""
        file1 = os.path.join(self.temp_dir, "file1.txt")
        file2 = os.path.join(self.temp_dir, "file2.txt")

        with open(file1, "w") as f:
            f.write("content1")
        with open(file2, "w") as f:
            f.write("content2")

        txn = self.refactor.begin_transaction()
        self.refactor.add_file_edit(txn, file1, "modified1", operation="modify")
        self.refactor.add_file_edit(txn, file2, "modified2", operation="modify")
        result = self.refactor.commit(txn, validate=False)

        assert result.success is True
        assert result.files_modified == 2

        with open(file1) as f:
            assert f.read() == "modified1"
        with open(file2) as f:
            assert f.read() == "modified2"

    def test_commit_failure_in_middle_rolls_back_all(self):
        """Test that failure in middle of transaction rolls back all edits."""
        file1 = os.path.join(self.temp_dir, "file1.txt")

        with open(file1, "w") as f:
            f.write("original1")

        def failing_validator(filepath, content):
            # Fail on second file but not first
            return "file1" in filepath

        txn = self.refactor.begin_transaction()
        self.refactor.add_file_edit(txn, file1, "modified1", operation="modify")
        # This edit will pass write but fail validation
        file2 = os.path.join(self.temp_dir, "file2.txt")
        self.refactor.add_file_edit(txn, file2, "modified2", operation="create")

        result = self.refactor.commit(txn, validate=True, validator=failing_validator)

        assert result.success is False
        assert len(result.errors) > 0
        # First file should be rolled back
        with open(file1) as f:
            assert f.read() == "original1"
        # Second file should not exist (was rolled back)
        assert not os.path.exists(file2)
