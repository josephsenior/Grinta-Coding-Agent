"""Unit tests for Python and Tree-sitter syntax error formatting."""

from __future__ import annotations

from backend.utils.treesitter._tse_errors import (
    _extract_node_text,
    _find_first_missing_node,
    _format_expected_line,
    _format_found_lines,
    _format_python_ast_syntax_error,
    _format_source_lines,
    _format_treesitter_error_block,
    _what_to_try_for_expected_token,
    _what_to_try_line_python,
)


class MockNode:
    """Mock Node object mimicking Tree-sitter Node behavior."""

    def __init__(
        self,
        type_name: str = 'ERROR',
        is_missing: bool = False,
        start_point: tuple[int, int] = (0, 0),
        start_byte: int | None = 0,
        end_byte: int | None = 0,
        children: list[MockNode] | None = None,
    ) -> None:
        self.type = type_name
        self.is_missing = is_missing
        self.start_point = start_point
        self.start_byte = start_byte
        self.end_byte = end_byte
        self.children = children or []


def test_format_python_ast_syntax_error_valid() -> None:
    # Valid Python should return None
    assert _format_python_ast_syntax_error('x = 1 + 2\n', 'test.py') is None


def test_format_python_ast_syntax_error_invalid() -> None:
    code = 'def foo(\n'
    res = _format_python_ast_syntax_error(code, 'test.py')
    assert res is not None
    assert 'Python syntax error at test.py' in res
    assert 'Parser message:' in res
    assert 'def foo(' in res
    assert '^' in res


def test_what_to_try_line_python() -> None:
    assert 'add the missing closing delimiter' in _what_to_try_line_python(
        'unexpected EOF while parsing'
    )
    assert 'fix indentation' in _what_to_try_line_python('unexpected indent')
    assert 'unmatched parentheses' in _what_to_try_line_python('invalid syntax (')
    assert 'follow the parser message' in _what_to_try_line_python(
        'some other syntax error'
    )


def test_find_first_missing_node() -> None:
    # Tree: root -> child1 (not missing), child2 (missing)
    child1 = MockNode(type_name='identifier', is_missing=False)
    child2 = MockNode(type_name=';', is_missing=True)
    root = MockNode(type_name='ERROR', children=[child1, child2])

    assert _find_first_missing_node(root) is child2

    # If nothing is missing
    root_ok = MockNode(type_name='ERROR', children=[child1])
    assert _find_first_missing_node(root_ok) is None


def test_what_to_try_for_expected_token() -> None:
    # No expected token
    assert 'compare this spot' in _what_to_try_for_expected_token(None, 'python')

    # Token too long
    assert 'expected a specific token' in _what_to_try_for_expected_token(
        'a' * 35, 'python'
    )

    # Closing brackets
    assert 'insert `)` to close' in _what_to_try_for_expected_token(')', 'python')

    # Delimiters
    assert 'insert `;` if a delimiter' in _what_to_try_for_expected_token(';', 'python')

    # Colon
    assert 'add `:` if a block' in _what_to_try_for_expected_token(':', 'python')

    # Quotes
    assert 'close or fix the string' in _what_to_try_for_expected_token('"', 'python')

    # Other tokens
    assert 'expected `def`' in _what_to_try_for_expected_token('def', 'python')


def test_extract_node_text() -> None:
    code = 'hello world emoji 🚀 test'
    # Valid byte indices
    assert _extract_node_text(code, 0, 5) == 'hello'

    # Out of bounds or None bytes
    assert _extract_node_text(code, None, 5) == ''
    assert _extract_node_text(code, 0, None) == ''
    assert _extract_node_text(code, -1, 5) == ''
    assert _extract_node_text(code, 0, 1000) == ''


def test_format_expected_line() -> None:
    assert _format_expected_line(';') == 'Expected: `;` (grammar token)'
    assert (
        _format_expected_line(None)
        == 'Expected: (not inferred — parser landed on an ERROR node)'
    )


def test_format_found_lines() -> None:
    # Under 120 chars
    node = MockNode()
    assert _format_found_lines(node, 'abc') == ["Found: 'abc'"]

    # Over 120 chars
    long_txt = 'x' * 130
    res = _format_found_lines(node, long_txt)
    # The truncated text preview is capped at 120, plus "Found: '" (8) and repr closing quotes/ellipsis.
    assert len(res[0]) <= 135
    assert '...' in res[0]

    # Empty text, unexpected token
    err_node = MockNode(type_name='ERROR', is_missing=False)
    assert 'unexpected token(s)' in _format_found_lines(err_node, '')[0]


def test_format_source_lines() -> None:
    lines = ['first line', 'second line', 'third line']
    # Valid row
    assert _format_source_lines(lines, 1, 3) == ['  second line', '     ^']

    # Invalid row
    assert _format_source_lines(lines, 5, 0) == []


def test_format_treesitter_error_block() -> None:
    code = 'x = \n'
    lines = code.splitlines()

    missing_node = MockNode(
        type_name='identifier',
        is_missing=True,
        start_point=(0, 4),
        start_byte=4,
        end_byte=4,
    )
    root = MockNode(
        type_name='ERROR',
        start_point=(0, 4),
        start_byte=4,
        end_byte=4,
        children=[missing_node],
    )

    parts = _format_treesitter_error_block(root, 'main.py', code, lines, 'python')

    joined = '\n'.join(parts)
    assert 'Syntax error at main.py:1:5' in joined
    assert 'Expected: `identifier`' in joined
    assert '  x = ' in joined
    assert 'What to try: the grammar expected `identifier`' in joined
