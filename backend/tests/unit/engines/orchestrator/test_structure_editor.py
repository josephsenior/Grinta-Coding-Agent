"""Comprehensive tests for backend.engines.orchestrator.tools.structure_editor."""

from __future__ import annotations

import os
import textwrap

import pytest

from backend.engines.orchestrator.tools.structure_editor import (
    EditorConfig,
    StructureEditor,
)
from backend.utils.treesitter_editor import (
    TREE_SITTER_AVAILABLE,
)

pytestmark = pytest.mark.skipif(
    not TREE_SITTER_AVAILABLE, reason="tree-sitter not installed"
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def editor():
    return StructureEditor()


@pytest.fixture
def editor_no_validate():
    cfg = EditorConfig(
        validate_syntax=False, clean_whitespace=False, backup_enabled=False
    )
    return StructureEditor(config=cfg)


@pytest.fixture
def py_file(tmp_path):
    content = textwrap.dedent("""\
        def greet(name):
            return f"Hello, {name}!"


        def add(a, b):
            return a + b


        class Calculator:
            def multiply(self, x, y):
                return x * y

            def divide(self, x, y):
                if y == 0:
                    raise ValueError("Division by zero")
                return x / y
    """)
    f = tmp_path / "sample.py"
    f.write_text(content, encoding="utf-8")
    return str(f)


@pytest.fixture
def js_file(tmp_path):
    content = textwrap.dedent("""\
        function hello(name) {
            return `Hello, ${name}!`;
        }
    """)
    f = tmp_path / "app.js"
    f.write_text(content, encoding="utf-8")
    return str(f)


# ---------------------------------------------------------------------------
# EditorConfig
# ---------------------------------------------------------------------------


class TestEditorConfig:
    def test_defaults(self):
        cfg = EditorConfig()
        assert cfg.auto_indent is True
        assert cfg.validate_syntax is True
        assert cfg.clean_whitespace is True
        assert cfg.backup_enabled is True
        assert cfg.dry_run_first is False

    def test_custom_config(self):
        cfg = EditorConfig(
            auto_indent=False, validate_syntax=False, backup_enabled=False
        )
        assert cfg.auto_indent is False
        assert cfg.validate_syntax is False
        assert cfg.backup_enabled is False


# ---------------------------------------------------------------------------
# StructureEditor initialization
# ---------------------------------------------------------------------------


class TestInit:
    def test_default_config(self, editor):
        assert isinstance(editor.config, EditorConfig)

    def test_custom_config(self):
        cfg = EditorConfig(auto_indent=False)
        ed = StructureEditor(config=cfg)
        assert ed.config.auto_indent is False

    def test_backends_initialized(self, editor):
        assert editor.universal is not None
        assert editor.whitespace is not None
        assert editor.refactor is not None
        assert editor.errors is not None

    def test_undo_history_empty(self, editor):
        assert editor._undo_history == {}


# ---------------------------------------------------------------------------
# create_file
# ---------------------------------------------------------------------------


class TestCreateFile:
    def test_creates_new_file(self, editor, tmp_path):
        path = str(tmp_path / "new.py")
        result = editor.create_file(path, "x = 1\n")
        assert result.success is True
        assert os.path.exists(path)
        assert open(path, encoding="utf-8").read() == "x = 1\n"

    def test_fails_if_file_exists(self, editor, py_file):
        result = editor.create_file(py_file, "overwrite")
        assert result.success is False
        assert "already exists" in result.message.lower()

    def test_creates_parent_directories(self, editor, tmp_path):
        path = str(tmp_path / "nested" / "deep" / "file.py")
        result = editor.create_file(path, "# new file")
        assert result.success is True
        assert os.path.exists(path)

    def test_reports_lines_changed(self, editor, tmp_path):
        path = str(tmp_path / "lines.py")
        content = "a = 1\nb = 2\nc = 3\n"
        result = editor.create_file(path, content)
        assert result.success is True
        # lines_changed = content.count("\n") + 1
        assert result.lines_changed == content.count("\n") + 1

    def test_modified_code_in_result(self, editor, tmp_path):
        path = str(tmp_path / "code.py")
        content = "print('hello')\n"
        result = editor.create_file(path, content)
        assert result.modified_code == content


# ---------------------------------------------------------------------------
# view_file
# ---------------------------------------------------------------------------


class TestViewFile:
    def test_view_full_file(self, editor, py_file):
        result = editor.view_file(py_file)
        assert result.success is True
        assert "greet" in result.message

    def test_view_with_line_range(self, editor, py_file):
        result = editor.view_file(py_file, line_range=[1, 2])
        assert result.success is True
        # First two lines are visible
        assert "greet" in result.message

    def test_view_nonexistent_file(self, editor):
        result = editor.view_file("/no/such/file.py")
        assert result.success is False
        assert "not found" in result.message.lower()

    def test_view_directory(self, editor, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "file.py").write_text("x = 1")
        result = editor.view_file(str(tmp_path))
        assert result.success is True

    def test_view_with_inverted_range(self, editor, py_file):
        # start > end should fail gracefully
        result = editor.view_file(py_file, line_range=[10, 1])
        # After clamping, start > end returns failure
        assert result.success is False

    def test_view_line_numbers_in_output(self, editor, py_file):
        result = editor.view_file(py_file)
        assert result.success is True
        # Line numbers should be present as integers
        assert "1" in result.message


# ---------------------------------------------------------------------------
# insert_code
# ---------------------------------------------------------------------------


class TestInsertCode:
    def test_insert_at_beginning(self, editor_no_validate, tmp_path):
        f = tmp_path / "insert.py"
        f.write_text("b = 2\n")
        result = editor_no_validate.insert_code(str(f), 0, "a = 1")
        assert result.success is True
        content = f.read_text()
        assert "a = 1" in content

    def test_insert_after_first_line(self, editor_no_validate, tmp_path):
        f = tmp_path / "insert2.py"
        f.write_text("a = 1\nc = 3\n")
        result = editor_no_validate.insert_code(str(f), 1, "b = 2")
        assert result.success is True

    def test_insert_into_nonexistent_file(self, editor_no_validate):
        result = editor_no_validate.insert_code("/no/file.py", 1, "x = 1")
        assert result.success is False


# ---------------------------------------------------------------------------
# undo_last_edit
# ---------------------------------------------------------------------------


class TestUndoLastEdit:
    def test_undo_after_edit(self, editor, py_file):
        original = open(py_file, encoding="utf-8").read()
        # Make an edit that records undo history
        editor.replace_code_range(py_file, 1, 1, "# replaced\n")
        result = editor.undo_last_edit(py_file)
        assert result.success is True
        restored = open(py_file, encoding="utf-8").read()
        assert restored == original

    def test_undo_no_history_fails(self, editor, tmp_path):
        f = tmp_path / "noundo.py"
        f.write_text("x = 1\n")
        result = editor.undo_last_edit(str(f))
        assert result.success is False
        assert "no undo history" in result.message.lower()

    def test_undo_write_error(self, editor, tmp_path):
        f = tmp_path / "canundo.py"
        f.write_text("x = 1\n")
        # Manually push some history
        editor._undo_history[str(f)] = [("h", "original = True\n")]
        result = editor.undo_last_edit(str(f))
        assert result.success is True


# ---------------------------------------------------------------------------
# edit_function
# ---------------------------------------------------------------------------


class TestEditFunction:
    def test_edit_known_function(self, editor, py_file):
        result = editor.edit_function(py_file, "greet", '    return "Hi!"')
        assert result.success is True
        content = open(py_file, encoding="utf-8").read()
        assert "Hi!" in content

    def test_edit_unknown_function(self, editor, py_file):
        result = editor.edit_function(py_file, "nonexistent_fn", "    pass")
        assert result.success is False

    def test_edit_function_unknown_language(self, editor, tmp_path):
        f = tmp_path / "file.zzz"
        f.write_text("content")
        result = editor.edit_function(str(f), "func", "body")
        assert result.success is False
        assert (
            "detect" in result.message.lower() or "language" in result.message.lower()
        )


# ---------------------------------------------------------------------------
# rename_symbol
# ---------------------------------------------------------------------------


class TestRenameSymbol:
    def test_rename_function(self, editor, py_file):
        result = editor.rename_symbol(py_file, "greet", "welcome")
        assert result.success is True
        content = open(py_file, encoding="utf-8").read()
        assert "def welcome" in content

    def test_rename_nonexistent(self, editor, py_file):
        result = editor.rename_symbol(py_file, "no_such", "new_name")
        assert result.success is False


# ---------------------------------------------------------------------------
# find_symbol
# ---------------------------------------------------------------------------


class TestFindSymbol:
    def test_find_existing_function(self, editor, py_file):
        loc = editor.find_symbol(py_file, "greet")
        assert loc is not None
        assert loc.symbol_name == "greet"

    def test_find_nonexistent_returns_none(self, editor, py_file):
        loc = editor.find_symbol(py_file, "nonexistent_xyz")
        assert loc is None

    def test_find_with_type_filter(self, editor, py_file):
        loc = editor.find_symbol(py_file, "Calculator", symbol_type="class")
        assert loc is not None


# ---------------------------------------------------------------------------
# replace_code_range
# ---------------------------------------------------------------------------


class TestReplaceCodeRange:
    def test_replace_single_line(self, editor_no_validate, tmp_path):
        f = tmp_path / "rep.py"
        f.write_text("a = 1\nb = 2\nc = 3\n")
        result = editor_no_validate.replace_code_range(str(f), 2, 2, "b = 99")
        assert result.success is True
        content = f.read_text()
        assert "b = 99" in content

    def test_replace_invalid_range(self, editor_no_validate, tmp_path):
        f = tmp_path / "inv.py"
        f.write_text("a = 1\n")
        result = editor_no_validate.replace_code_range(str(f), 5, 10, "x")
        assert result.success is False
        assert "invalid" in result.message.lower()

    def test_replace_nonexistent_file(self, editor_no_validate):
        result = editor_no_validate.replace_code_range("/no/file.py", 1, 1, "x")
        assert result.success is False

    def test_replace_preserves_undo_history(self, editor, tmp_path):
        f = tmp_path / "undo_test.py"
        f.write_text("x = 1\ny = 2\nz = 3\n")
        editor.replace_code_range(str(f), 1, 1, "x = 99")
        assert str(f) in editor._undo_history


# ---------------------------------------------------------------------------
# begin_refactoring / commit / rollback
# ---------------------------------------------------------------------------


class TestRefactoring:
    def test_begin_returns_transaction(self, editor):
        from backend.engines.orchestrator.tools.atomic_refactor import (
            RefactorTransaction,
        )

        txn = editor.begin_refactoring()
        assert isinstance(txn, RefactorTransaction)

    def test_commit_empty_transaction(self, editor):
        txn = editor.begin_refactoring()
        result = editor.commit_refactoring(txn)
        # Empty transaction succeeds trivially
        assert result.success is True

    def test_rollback_returns_result(self, editor):
        txn = editor.begin_refactoring()
        result = editor.rollback_refactoring(txn)
        assert hasattr(result, "success")


# ---------------------------------------------------------------------------
# get_supported_languages
# ---------------------------------------------------------------------------


class TestGetSupportedLanguages:
    def test_returns_list(self, editor):
        langs = editor.get_supported_languages()
        assert isinstance(langs, list)
        assert "python" in langs

    def test_delegates_to_universal(self, editor):
        assert (
            editor.get_supported_languages()
            == editor.universal.get_supported_languages()
        )


# ---------------------------------------------------------------------------
# normalize_file_indent
# ---------------------------------------------------------------------------


class TestNormalizeFileIndent:
    def test_normalize_python_file(self, editor, py_file):
        result = editor.normalize_file_indent(py_file)
        assert result.success is True

    def test_normalize_with_spaces_target(self, editor, py_file):
        result = editor.normalize_file_indent(
            py_file, target_style="spaces", target_size=4
        )
        assert result.success is True

    def test_normalize_with_tabs_target(self, editor, py_file):
        result = editor.normalize_file_indent(py_file, target_style="tabs")
        assert result.success is True

    def test_normalize_nonexistent_file(self, editor):
        result = editor.normalize_file_indent("/no/file.py")
        assert result.success is False

    def test_normalize_returns_original_code(self, editor, py_file):
        result = editor.normalize_file_indent(py_file)
        assert result.success is True
        assert result.original_code is not None


# ---------------------------------------------------------------------------
# clear_caches
# ---------------------------------------------------------------------------


class TestClearCaches:
    def test_clears_without_error(self, editor, py_file):
        editor.view_file(py_file)  # may populate caches
        editor.clear_caches()  # should not raise

    def test_clear_empty_caches_safe(self, editor):
        editor.clear_caches()


# ---------------------------------------------------------------------------
# _determine_view_range
# ---------------------------------------------------------------------------


class TestDetermineViewRange:
    def test_no_range_returns_full(self, editor):
        start, end = editor._determine_view_range(None, 20)
        assert start == 1
        assert end == 20

    def test_single_element_range(self, editor):
        start, end = editor._determine_view_range([5], 20)
        assert start == 5
        assert end == 20

    def test_two_element_range(self, editor):
        start, end = editor._determine_view_range([3, 8], 20)
        assert start == 3
        assert end == 8

    def test_minus_one_end_means_total(self, editor):
        start, end = editor._determine_view_range([2, -1], 20)
        # -1 is treated as "not specified", so end = total_lines
        assert end == 20

    def test_clamping_below_one(self, editor):
        start, end = editor._determine_view_range([-5, 30], 20)
        assert start == 1  # clamped to 1
        assert end == 20  # clamped to total_lines


# ---------------------------------------------------------------------------
# _format_view_output
# ---------------------------------------------------------------------------


class TestFormatViewOutput:
    def test_includes_line_numbers(self, editor):
        lines = ["alpha\n", "beta\n", "gamma\n"]
        output = editor._format_view_output(lines, 1, 3)
        assert "1" in output
        assert "3" in output
        assert "alpha" in output
        assert "gamma" in output

    def test_partial_range(self, editor):
        lines = ["a\n", "b\n", "c\n", "d\n"]
        output = editor._format_view_output(lines, 2, 3)
        assert "b" in output
        assert "c" in output
        assert "a" not in output


# ---------------------------------------------------------------------------
# _get_available_symbols
# ---------------------------------------------------------------------------


class TestGetAvailableSymbols:
    def test_returns_list_for_python_file(self, editor, py_file):
        symbols = editor._get_available_symbols(py_file)
        assert isinstance(symbols, list)
        assert "greet" in symbols
        assert "add" in symbols

    def test_filtered_by_function_type(self, editor, py_file):
        symbols = editor._get_available_symbols(py_file, "function")
        assert "greet" in symbols

    def test_filtered_by_class_type(self, editor, py_file):
        symbols = editor._get_available_symbols(py_file, "class")
        assert "Calculator" in symbols

    def test_nonexistent_file_returns_empty(self, editor):
        symbols = editor._get_available_symbols("/no/file.py")
        assert symbols == []


# ---------------------------------------------------------------------------
# _check_blast_radius
# ---------------------------------------------------------------------------

from unittest.mock import patch, MagicMock
from backend.engines.orchestrator.tools.structure_editor import EditResult


class TestBlastRadiusHook:
    @patch("backend.engines.orchestrator.tools.structure_editor.get_lsp_client")
    def test_blast_radius_exceeds_threshold(self, mock_get_lsp_client, editor, py_file):
        mock_client = MagicMock()
        mock_get_lsp_client.return_value = mock_client
        mock_result = MagicMock()
        mock_result.locations = [MagicMock()] * 15  # 15 references
        mock_client.query.return_value = mock_result
        # Mock find_symbol so we reach the LSP query path
        editor.universal.find_symbol = MagicMock(return_value=MagicMock(line_start=1))

        result = EditResult(success=True, message="Success")
        editor._check_blast_radius(py_file, "greet", result, threshold=10)

        assert "BLAST RADIUS EXCEEDS" in result.message
        assert "15 other locations" in result.message

    @patch("backend.engines.orchestrator.tools.structure_editor.get_lsp_client")
    def test_blast_radius_under_threshold(self, mock_get_lsp_client, editor, py_file):
        mock_client = MagicMock()
        mock_get_lsp_client.return_value = mock_client
        mock_result = MagicMock()
        mock_result.locations = [MagicMock()] * 5  # 5 references
        mock_client.query.return_value = mock_result
        editor.universal.find_symbol = MagicMock(return_value=MagicMock(line_start=1))

        result = EditResult(success=True, message="Success")
        editor._check_blast_radius(py_file, "greet", result, threshold=10)

        assert "BLAST RADIUS EXCEEDS" not in result.message

    @patch("backend.engines.orchestrator.tools.structure_editor.get_lsp_client")
    def test_blast_radius_from_code_snippet(self, mock_get_lsp_client, editor, py_file):
        mock_client = MagicMock()
        mock_get_lsp_client.return_value = mock_client
        mock_result = MagicMock()
        mock_result.locations = [MagicMock()] * 12  # 12 references
        mock_client.query.return_value = mock_result
        editor.universal.find_symbol = MagicMock(return_value=MagicMock(line_start=1))

        result = EditResult(success=True, message="Replaced code successfully")
        snippet = "def add(a, b):\n    return a + b"
        editor._check_blast_radius_from_code(py_file, snippet, result, threshold=10)

        assert "BLAST RADIUS EXCEEDS" in result.message
        assert "add" in result.message
