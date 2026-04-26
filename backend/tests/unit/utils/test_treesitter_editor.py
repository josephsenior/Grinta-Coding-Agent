"""Comprehensive tests for backend.utils.treesitter_editor."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from backend.utils.treesitter_editor import (
    LANGUAGE_EXTENSIONS,
    TREE_SITTER_AVAILABLE,
    EditResult,
    SymbolLocation,
    TreeSitterEditor,
)

# All tests require tree-sitter to be available
pytestmark = pytest.mark.skipif(
    not TREE_SITTER_AVAILABLE, reason='tree-sitter not installed'
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def editor() -> TreeSitterEditor:
    return TreeSitterEditor()


@pytest.fixture
def py_file(tmp_path: Path) -> str:
    """Create a simple Python file for testing."""
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
    f = tmp_path / 'sample.py'
    f.write_text(content, encoding='utf-8')
    return str(f)


@pytest.fixture
def js_file(tmp_path: Path) -> str:
    """Create a simple JavaScript file for testing."""
    content = textwrap.dedent("""\
        function hello(name) {
            return `Hello, ${name}!`;
        }

        function add(a, b) {
            return a + b;
        }
    """)
    f = tmp_path / 'sample.js'
    f.write_text(content, encoding='utf-8')
    return str(f)


# ---------------------------------------------------------------------------
# EditResult dataclass
# ---------------------------------------------------------------------------


class TestEditResult:
    def test_success_defaults(self) -> None:
        r = EditResult(success=True, message='ok')
        assert r.success is True
        assert r.message == 'ok'
        assert r.modified_code is None
        assert r.lines_changed == 0
        assert r.syntax_valid is True
        assert r.original_code is None

    def test_failure_result(self) -> None:
        r = EditResult(success=False, message='failed', syntax_valid=False)
        assert r.success is False
        assert r.syntax_valid is False

    def test_full_result(self) -> None:
        r = EditResult(
            success=True,
            message='done',
            modified_code='x = 1',
            lines_changed=3,
            original_code='x = 0',
        )
        assert r.modified_code == 'x = 1'
        assert r.lines_changed == 3
        assert r.original_code == 'x = 0'


# ---------------------------------------------------------------------------
# SymbolLocation dataclass
# ---------------------------------------------------------------------------


class TestSymbolLocation:
    def test_basic_location(self) -> None:
        loc = SymbolLocation(
            file_path='a.py',
            line_start=1,
            line_end=3,
            byte_start=0,
            byte_end=50,
            node_type='function_definition',
            symbol_name='greet',
        )
        assert loc.file_path == 'a.py'
        assert loc.line_start == 1
        assert loc.line_end == 3
        assert loc.symbol_name == 'greet'
        assert loc.parent_name is None

    def test_method_location_with_parent(self) -> None:
        loc = SymbolLocation(
            file_path='b.py',
            line_start=5,
            line_end=7,
            byte_start=100,
            byte_end=200,
            node_type='function_definition',
            symbol_name='multiply',
            parent_name='Calculator',
        )
        assert loc.parent_name == 'Calculator'


# ---------------------------------------------------------------------------
# LANGUAGE_EXTENSIONS mapping
# ---------------------------------------------------------------------------


class TestLanguageExtensions:
    def test_python_extension(self) -> None:
        assert LANGUAGE_EXTENSIONS['.py'] == 'python'

    def test_javascript_extension(self) -> None:
        assert LANGUAGE_EXTENSIONS['.js'] == 'javascript'

    def test_typescript_extension(self) -> None:
        assert LANGUAGE_EXTENSIONS['.ts'] == 'typescript'

    def test_go_extension(self) -> None:
        assert LANGUAGE_EXTENSIONS['.go'] == 'go'

    def test_rust_extension(self) -> None:
        assert LANGUAGE_EXTENSIONS['.rs'] == 'rust'

    def test_java_extension(self) -> None:
        assert LANGUAGE_EXTENSIONS['.java'] == 'java'

    def test_yaml_extension(self) -> None:
        assert LANGUAGE_EXTENSIONS['.yml'] == 'yaml'
        assert LANGUAGE_EXTENSIONS['.yaml'] == 'yaml'

    def test_json_extension(self) -> None:
        assert LANGUAGE_EXTENSIONS['.json'] == 'json'

    def test_cpp_extensions(self) -> None:
        assert LANGUAGE_EXTENSIONS['.cpp'] == 'cpp'
        assert LANGUAGE_EXTENSIONS['.cc'] == 'cpp'
        assert LANGUAGE_EXTENSIONS['.cxx'] == 'cpp'

    def test_c_extension(self) -> None:
        assert LANGUAGE_EXTENSIONS['.c'] == 'c'
        assert LANGUAGE_EXTENSIONS['.h'] == 'c'

    def test_tsx_extension(self) -> None:
        assert LANGUAGE_EXTENSIONS['.tsx'] == 'tsx'

    def test_bash_extensions(self) -> None:
        assert LANGUAGE_EXTENSIONS['.sh'] == 'bash'
        assert LANGUAGE_EXTENSIONS['.bash'] == 'bash'

    def test_sql_extension(self) -> None:
        assert LANGUAGE_EXTENSIONS['.sql'] == 'sql'

    def test_markdown_extension(self) -> None:
        assert LANGUAGE_EXTENSIONS['.md'] == 'markdown'

    def test_has_many_extensions(self) -> None:
        # At least 40+ languages
        assert len(LANGUAGE_EXTENSIONS) >= 40


# ---------------------------------------------------------------------------
# TreeSitterEditor initialization
# ---------------------------------------------------------------------------


class TestEditorInit:
    def test_creates_instance(self, editor: TreeSitterEditor) -> None:
        assert isinstance(editor, TreeSitterEditor)

    def test_parsers_start_empty(self, editor: TreeSitterEditor) -> None:
        assert editor.parsers == {}

    def test_caches_start_empty(self, editor: TreeSitterEditor) -> None:
        assert editor.tree_cache == {}
        assert editor.file_cache == {}


# ---------------------------------------------------------------------------
# detect_language
# ---------------------------------------------------------------------------


class TestDetectLanguage:
    def test_python_file(self, editor: TreeSitterEditor) -> None:
        assert editor.detect_language('script.py') == 'python'

    def test_javascript_file(self, editor: TreeSitterEditor) -> None:
        assert editor.detect_language('app.js') == 'javascript'

    def test_typescript_file(self, editor: TreeSitterEditor) -> None:
        assert editor.detect_language('main.ts') == 'typescript'

    def test_go_file(self, editor: TreeSitterEditor) -> None:
        assert editor.detect_language('main.go') == 'go'

    def test_rust_file(self, editor: TreeSitterEditor) -> None:
        assert editor.detect_language('lib.rs') == 'rust'

    def test_yaml_file(self, editor: TreeSitterEditor) -> None:
        assert editor.detect_language('config.yaml') == 'yaml'
        assert editor.detect_language('config.yml') == 'yaml'

    def test_unknown_extension_returns_none(self, editor: TreeSitterEditor) -> None:
        assert editor.detect_language('file.xyz_unknown') is None

    def test_no_extension_returns_none(self, editor: TreeSitterEditor) -> None:
        assert editor.detect_language('Makefile') is None

    def test_case_insensitive_extension(self, editor: TreeSitterEditor) -> None:
        # Extensions are lowercased before lookup
        result = editor.detect_language('Script.PY')
        # lowercase via Path().suffix.lower()
        assert result == 'python'

    def test_path_with_directory(self, editor: TreeSitterEditor) -> None:
        assert editor.detect_language('/some/path/module.js') == 'javascript'


# ---------------------------------------------------------------------------
# get_supported_languages
# ---------------------------------------------------------------------------


class TestGetSupportedLanguages:
    def test_returns_list(self, editor: TreeSitterEditor) -> None:
        langs = editor.get_supported_languages()
        assert isinstance(langs, list)

    def test_contains_python(self, editor: TreeSitterEditor) -> None:
        assert 'python' in editor.get_supported_languages()

    def test_contains_javascript(self, editor: TreeSitterEditor) -> None:
        assert 'javascript' in editor.get_supported_languages()

    def test_contains_many_languages(self, editor: TreeSitterEditor) -> None:
        assert len(editor.get_supported_languages()) >= 15

    def test_no_duplicates(self, editor: TreeSitterEditor) -> None:
        langs = editor.get_supported_languages()
        assert len(langs) == len(set(langs))


# ---------------------------------------------------------------------------
# get_parser
# ---------------------------------------------------------------------------


class TestGetParser:
    def test_python_parser(self, editor: TreeSitterEditor) -> None:
        parser = editor.get_parser('python')
        assert parser is not None

    def test_javascript_parser(self, editor: TreeSitterEditor) -> None:
        parser = editor.get_parser('javascript')
        assert parser is not None

    def test_cached_parser(self, editor: TreeSitterEditor) -> None:
        parser1 = editor.get_parser('python')
        parser2 = editor.get_parser('python')
        assert parser1 is parser2

    def test_unknown_language_returns_none(self, editor: TreeSitterEditor) -> None:
        result = editor.get_parser('nonexistent_lang_xyz')
        assert result is None


# ---------------------------------------------------------------------------
# parse_file
# ---------------------------------------------------------------------------


class TestParseFile:
    def test_parse_python_file(self, editor: TreeSitterEditor, py_file: str) -> None:
        result = editor.parse_file(py_file)
        assert result is not None
        _tree, file_bytes, language = result
        assert language == 'python'
        assert isinstance(file_bytes, bytes)
        assert b'def greet' in file_bytes

    def test_parse_javascript_file(self, editor: TreeSitterEditor, js_file: str) -> None:
        result = editor.parse_file(js_file)
        assert result is not None
        _tree, _file_bytes, language = result
        assert language == 'javascript'

    def test_parse_unknown_extension_returns_none(self, editor: TreeSitterEditor, tmp_path: Path) -> None:
        f = tmp_path / 'file.zzz'
        f.write_text('content')
        assert editor.parse_file(str(f)) is None

    def test_parse_nonexistent_file_returns_none(self, editor: TreeSitterEditor) -> None:
        assert editor.parse_file('/nonexistent/path/file.py') is None

    def test_parse_uses_cache(self, editor: TreeSitterEditor, py_file: str) -> None:
        result1 = editor.parse_file(py_file, use_cache=True)
        result2 = editor.parse_file(py_file, use_cache=True)
        assert result1 is not None and result2 is not None
        tree1, _, _ = result1
        tree2, _, _ = result2
        assert tree1 is tree2  # same cached object

    def test_parse_no_cache_returns_fresh(self, editor: TreeSitterEditor, py_file: str) -> None:
        result1 = editor.parse_file(py_file, use_cache=False)
        result2 = editor.parse_file(py_file, use_cache=False)
        # Both should succeed even without cache
        assert result1 is not None
        assert result2 is not None


# ---------------------------------------------------------------------------
# find_symbol
# ---------------------------------------------------------------------------


class TestFindSymbol:
    def test_find_function(self, editor: TreeSitterEditor, py_file: str) -> None:
        loc = editor.find_symbol(py_file, 'greet')
        assert loc is not None
        assert loc.symbol_name == 'greet'
        assert loc.line_start >= 1

    def test_find_class(self, editor: TreeSitterEditor, py_file: str) -> None:
        loc = editor.find_symbol(py_file, 'Calculator')
        assert loc is not None
        assert loc.symbol_name == 'Calculator'

    def test_find_method_dot_notation(self, editor: TreeSitterEditor, py_file: str) -> None:
        loc = editor.find_symbol(py_file, 'Calculator.multiply')
        assert loc is not None
        assert loc.symbol_name == 'multiply'
        assert loc.parent_name == 'Calculator'

    def test_find_nonexistent_symbol_returns_none(self, editor: TreeSitterEditor, py_file: str) -> None:
        assert editor.find_symbol(py_file, 'nonexistent_xyz') is None

    def test_find_with_function_type_filter(self, editor: TreeSitterEditor, py_file: str) -> None:
        loc = editor.find_symbol(py_file, 'greet', symbol_type='function')
        assert loc is not None

    def test_find_with_class_type_filter(self, editor: TreeSitterEditor, py_file: str) -> None:
        loc = editor.find_symbol(py_file, 'Calculator', symbol_type='class')
        assert loc is not None

    def test_find_function_with_wrong_type_returns_none(self, editor: TreeSitterEditor, py_file: str) -> None:
        # greet is a function, not a class
        loc = editor.find_symbol(py_file, 'greet', symbol_type='class')
        assert loc is None

    def test_find_in_nonexistent_file_returns_none(self, editor: TreeSitterEditor) -> None:
        assert editor.find_symbol('/nonexistent.py', 'func') is None


# ---------------------------------------------------------------------------
# edit_function
# ---------------------------------------------------------------------------


class TestEditFunction:
    def test_edit_existing_function(self, editor: TreeSitterEditor, py_file: str) -> None:
        result = editor.edit_function(py_file, 'greet', '    return f"Hi, {name}!"')
        assert result.success is True
        assert 'greet' in result.message
        # Verify changes were written
        content = open(py_file, encoding='utf-8').read()
        assert 'Hi, ' in content

    def test_edit_nonexistent_function(self, editor: TreeSitterEditor, py_file: str) -> None:
        result = editor.edit_function(py_file, 'nonexistent_func', '    pass')
        assert result.success is False
        assert 'not found' in result.message.lower()

    def test_edit_function_in_nonexistent_file(self, editor: TreeSitterEditor) -> None:
        result = editor.edit_function('/no/such/file.py', 'func', '    pass')
        assert result.success is False

    def test_edit_clears_cache(self, editor: TreeSitterEditor, py_file: str) -> None:
        editor.parse_file(py_file)  # populate cache
        assert py_file in editor.tree_cache
        editor.edit_function(py_file, 'greet', '    return "hello"')
        assert py_file not in editor.tree_cache

    def test_edit_preserves_other_functions(self, editor: TreeSitterEditor, py_file: str) -> None:
        editor.edit_function(py_file, 'greet', '    return "modified"')
        content = open(py_file, encoding='utf-8').read()
        # add function should still exist
        assert 'def add' in content

    def test_edit_function_unknown_extension(self, editor: TreeSitterEditor, tmp_path: Path) -> None:
        f = tmp_path / 'file.zzz'
        f.write_text('content')
        result = editor.edit_function(str(f), 'func', 'body')
        assert result.success is False


# ---------------------------------------------------------------------------
# rename_symbol
# ---------------------------------------------------------------------------


class TestRenameSymbol:
    def test_rename_function(self, editor: TreeSitterEditor, py_file: str) -> None:
        result = editor.rename_symbol(py_file, 'greet', 'welcome')
        assert result.success is True
        content = open(py_file, encoding='utf-8').read()
        assert 'def welcome' in content
        assert 'def greet' not in content

    def test_rename_nonexistent_symbol(self, editor: TreeSitterEditor, py_file: str) -> None:
        result = editor.rename_symbol(py_file, 'no_such_sym', 'new_name')
        assert result.success is False
        assert 'not found' in result.message.lower()

    def test_rename_in_nonexistent_file(self, editor: TreeSitterEditor) -> None:
        result = editor.rename_symbol('/no/file.py', 'old', 'new')
        assert result.success is False

    def test_rename_clears_cache(self, editor: TreeSitterEditor, py_file: str) -> None:
        editor.parse_file(py_file)
        editor.rename_symbol(py_file, 'add', 'sum_values')
        assert py_file not in editor.tree_cache

    def test_rename_returns_occurrence_count(self, editor: TreeSitterEditor, py_file: str) -> None:
        result = editor.rename_symbol(py_file, 'greet', 'helloo')
        assert result.success is True
        # lines_changed is the count of occurrences
        assert result.lines_changed >= 1


# ---------------------------------------------------------------------------
# validate_syntax (public)
# ---------------------------------------------------------------------------


class TestValidateSyntax:
    def test_valid_python(self, editor: TreeSitterEditor) -> None:
        code = 'def foo():\n    return 1\n'
        is_valid, _msg = editor.validate_syntax(code, 'f.py', 'python')
        assert is_valid is True

    def test_invalid_python(self, editor: TreeSitterEditor) -> None:
        code = 'def foo(\n    return 1\n'  # syntax error
        is_valid, msg = editor.validate_syntax(code, 'f.py', 'python')
        assert is_valid is False
        assert 'Python syntax error' in msg
        assert 'Parser message:' in msg
        assert 'What to try:' in msg

    def test_no_parser_for_unknown_language(self, editor: TreeSitterEditor) -> None:
        code = 'some code'
        is_valid, _msg = editor.validate_syntax(code, 'f.zzz', 'unknown_xyz')
        # no parser => validation skipped, returns True
        assert is_valid is True


# ---------------------------------------------------------------------------
# _has_syntax_errors (internal)
# ---------------------------------------------------------------------------


class TestHasSyntaxErrors:
    def test_valid_tree_no_errors(self, editor: TreeSitterEditor, py_file: str) -> None:
        result = editor.parse_file(py_file)
        assert result is not None
        tree, _, _ = result
        assert editor._has_syntax_errors(tree.root_node) is False  # type: ignore


# ---------------------------------------------------------------------------
# clear_cache
# ---------------------------------------------------------------------------


class TestClearCache:
    def test_clears_tree_and_file_cache(self, editor: TreeSitterEditor, py_file: str) -> None:
        editor.parse_file(py_file)
        assert editor.tree_cache
        assert editor.file_cache
        editor.clear_cache()
        assert editor.tree_cache == {}
        assert editor.file_cache == {}

    def test_clear_empty_cache_is_safe(self, editor: TreeSitterEditor) -> None:
        editor.clear_cache()  # Should not raise


# ---------------------------------------------------------------------------
# _find_all_symbol_occurrences (internal)
# ---------------------------------------------------------------------------


class TestFindAllSymbolOccurrences:
    def test_finds_multiple_occurrences(self, editor: TreeSitterEditor, py_file: str) -> None:
        result = editor.parse_file(py_file)
        assert result is not None
        tree, file_bytes, _ = result
        occurrences = editor._find_all_symbol_occurrences(  # type: ignore
            tree, file_bytes, 'greet', 'python'
        )
        # "greet" appears in def statement
        assert occurrences

    def test_no_occurrences_returns_empty(self, editor: TreeSitterEditor, py_file: str) -> None:
        result = editor.parse_file(py_file)
        assert result is not None
        tree, file_bytes, _ = result
        occurrences = editor._find_all_symbol_occurrences(  # type: ignore
            tree, file_bytes, 'no_such_name_xyz', 'python'
        )
        assert occurrences == []


# ---------------------------------------------------------------------------
# Additional coverage tests
# ---------------------------------------------------------------------------


class TestCoverageGaps:
    def test_get_name_node_recursion(self, editor: TreeSitterEditor, tmp_path: Path) -> None:
        """Test recursive name node extraction (e.g. in C)."""
        content = 'int foo() { return 1; }'
        f = tmp_path / 'test.c'
        f.write_text(content, encoding='utf-8')
        # In C, function name is inside a function_declarator
        loc = editor.find_symbol(str(f), 'foo')
        assert loc is not None
        assert loc.symbol_name == 'foo'

    def test_edit_function_syntax_error(self, editor: TreeSitterEditor, py_file: str) -> None:
        """Test edit_function when result has syntax error."""
        # Providing invalid python code
        result = editor.edit_function(py_file, 'greet', '    def invalid syntax:')
        assert result.success is False
        assert 'Syntax error' in result.message
        assert result.syntax_valid is False

    def test_rename_symbol_syntax_error(self, editor: TreeSitterEditor, py_file: str) -> None:
        """Test rename_symbol when result has syntax error (e.g. renaming to invalid identifier)."""
        # Renaming to something that breaks syntax
        result = editor.rename_symbol(py_file, 'greet', '123invalid')
        assert result.success is False
        assert 'Rename created syntax error' in result.message or not result.success

    def test_validate_syntax_exception(self, editor: TreeSitterEditor) -> None:
        """Test _validate_syntax when an exception occurs during parsing."""
        import pytest

        with pytest.MonkeyPatch.context() as mp:
            # Mock get_parser to raise an exception (non-Python path calls get_parser).
            def raise_exc(lang: str) -> None:
                raise RuntimeError('test exception')

            mp.setattr(editor, 'get_parser', raise_exc)
            is_valid, msg = editor.validate_syntax('const x =', 'f.js', 'javascript')
            # Should skip validation and return True on exception
            assert is_valid is True
            assert 'Validation skipped' in msg

    def test_find_method_in_class_node_not_found(self, editor: TreeSitterEditor, py_file: str) -> None:
        """Test method search when method doesn't exist in class."""
        loc = editor.find_symbol(py_file, 'Calculator.nonexistent')
        assert loc is None

    def test_find_method_in_nonexistent_class(self, editor: TreeSitterEditor, py_file: str) -> None:
        """Test method search when class doesn't exist."""
        loc = editor.find_symbol(py_file, 'NonexistentClass.method')
        assert loc is None

    def test_search_tree_for_symbol_not_found(self, editor: TreeSitterEditor, py_file: str) -> None:
        """Test generic symbol search when not found."""
        # Using internal method to ensure we hit the return None
        result = editor.parse_file(py_file)
        assert result is not None
        tree, file_bytes, lang = result
        loc = editor._search_tree_for_symbol(  # type: ignore
            tree, file_bytes, 'notfound', py_file, lang
        )
        assert loc is None

    def test_get_function_body_node_not_found(self, editor: TreeSitterEditor, py_file: str) -> None:
        """Test body extraction when no body is found."""
        # This is hard to trigger with valid code, but we can mock or use weird edge case
        result = editor.parse_file(py_file)
        assert result is not None
        tree, _, lang = result
        # Find a node that isn't a function but try to get its body
        node = tree.root_node
        body = editor._get_function_body_node(node, lang)  # type: ignore
        assert body is None

    def test_get_parser_none_pack(self, editor: TreeSitterEditor) -> None:
        """Test get_parser when language pack is missing."""
        import backend.utils.treesitter_editor as tse

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tse, '_get_language', None)
            assert editor.get_parser('python') is None

    def test_parse_file_no_language(self, editor: TreeSitterEditor, tmp_path: Path) -> None:
        """Test parse_file when language detection fails."""
        f = tmp_path / 'no_ext'
        f.write_text('content', encoding='utf-8')
        assert editor.parse_file(str(f)) is None

    def test_find_symbol_invalid_dot_notation(self, editor: TreeSitterEditor, py_file: str) -> None:
        """Test find_symbol with deep dot notation (unsupported)."""
        # Only Class.method (2 parts) is supported
        assert editor.find_symbol(py_file, 'A.B.C') is None

    def test_edit_function_parse_failure(self, editor: TreeSitterEditor, py_file: str) -> None:
        """Test edit_function when parsing fails."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(editor, 'parse_file', lambda *args, **kwargs: None)  # type: ignore
            result = editor.edit_function(py_file, 'func', 'body')
            assert result.success is False

    def test_rename_symbol_parse_failure(self, editor: TreeSitterEditor, py_file: str) -> None:
        """Test rename_symbol when parsing fails."""
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(editor, 'parse_file', lambda *args, **kwargs: None)  # type: ignore
            result = editor.rename_symbol(py_file, 'old', 'new')
            assert result.success is False

    def test_find_function_node_default_types(self, editor: TreeSitterEditor, py_file: str) -> None:
        """Test _find_function_node with an unknown language."""
        result = editor.parse_file(py_file)
        assert result is not None
        tree, file_bytes, _ = result
        # "unknown" language uses default ["function_definition", "function_declaration"]
        node = editor._find_function_node(tree, file_bytes, 'greet', 'unknown')  # type: ignore
        assert node is not None
        assert node.type == 'function_definition'
