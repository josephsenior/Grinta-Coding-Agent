"""Syntax-error rendering helpers for Python and tree-sitter.

Two flavours of error message are produced:

- Python: ``compile(..., "exec")`` is used because it catches interpreter-phase
  errors that ``ast.parse`` would silently ignore (top-level ``return``,
  duplicate arguments, ``await`` outside async).
- Tree-sitter: walks the parsed tree collecting ``ERROR``/``MISSING`` nodes and
  renders a friendly one-line hint per occurrence.

The renderers are pure module functions so ``validate_syntax`` (instance
method) and ``syntax_check.py`` (external caller) can both reuse them.
"""

from __future__ import annotations

from typing import Any


def _format_python_ast_syntax_error(code: str, file_path: str) -> str | None:
    """If ``code`` is invalid Python, return a rich message; otherwise ``None``.

    ``compile(..., "exec")`` catches the full interpreter syntax phase, including
    errors that ``ast.parse`` accepts (for example ``return`` outside a function,
    duplicate arguments, or ``await`` outside async code).
    """
    try:
        compile(code, file_path, 'exec')
    except SyntaxError as e:
        return _render_python_syntax_error(e, code, file_path)
    return None


def _render_python_syntax_error(e: SyntaxError, code: str, file_path: str) -> str:
    lineno = e.lineno or 1
    offset = e.offset or 0
    msg = (e.msg or 'invalid syntax').strip()
    lines = code.splitlines()
    parts: list[str] = [
        f'Python syntax error at {file_path}: line {lineno}:{offset}',
        f'Parser message: {msg}',
    ]
    if e.lineno and 1 <= e.lineno <= len(lines):
        line = lines[e.lineno - 1]
        parts.append(f'  {line}')
        if e.offset is not None and e.offset >= 1:
            col = e.offset - 1
            parts.append(f'  {" " * col}^')
    parts.append(_what_to_try_line_python(msg))
    return '\n'.join(parts)


def _what_to_try_line_python(msg: str) -> str:
    lower = msg.lower()
    if 'unexpected eof' in lower or 'end of file' in lower:
        return 'What to try: add the missing closing delimiter (`)`, `]`, `}`, or finish the string/block).'
    if 'indent' in lower:
        return 'What to try: fix indentation so blocks align with `def`, `class`, `if`, etc.'
    if 'invalid syntax' in lower and '(' in msg:
        return 'What to try: check unmatched parentheses, brackets, or a missing `:` before a block.'
    return 'What to try: follow the parser message above (often a missing `,`, `:`, `)`, or quote).'


def _find_first_missing_node(node: Any) -> Any | None:
    """Return the first MISSING node in a subtree (depth-first)."""
    if getattr(node, 'is_missing', False):
        return node
    for child in getattr(node, 'children', []) or []:
        found = _find_first_missing_node(child)
        if found is not None:
            return found
    return None


def _what_to_try_for_expected_token(expected: str | None, language: str) -> str:
    """One-line hint for agents when a MISSING node's type names an expected token."""
    if not expected:
        return (
            'What to try: compare this spot with a valid example of the surrounding construct '
            f'({language}).'
        )
    exp = expected.strip()
    if len(exp) > 32:
        return 'What to try: the grammar expected a specific token here; narrow the edit and re-parse.'
    if exp in {')', ']', '}', '>'}:
        return f'What to try: insert `{exp}` to close an unmatched opening bracket.'
    if exp in {';', ','}:
        return f'What to try: insert `{exp}` if a delimiter is required between parts here.'
    if exp == ':':
        return 'What to try: add `:` if a block or type annotation requires it.'
    if exp in {'"', "'", '`'}:
        return 'What to try: close or fix the string / template literal.'
    return f'What to try: the grammar expected `{exp}` at this position; add or move tokens accordingly.'


def _format_treesitter_error_block(
    node: Any,
    file_path: str,
    code: str,
    lines: list[str],
    language: str,
) -> list[str]:
    """Build human- and agent-friendly lines for one ERROR or MISSING node."""
    start_point = getattr(node, 'start_point', (0, 0))
    start_row, start_col = start_point[0], start_point[1]
    start_byte = getattr(node, 'start_byte', None)
    end_byte = getattr(node, 'end_byte', None)

    node_text = _extract_node_text(code, start_byte, end_byte)
    if not isinstance(start_col, int) or start_col < 0:
        start_col = 0

    missing = (
        node if getattr(node, 'is_missing', False) else _find_first_missing_node(node)
    )
    expected = getattr(missing, 'type', None) or None

    parts: list[str] = [
        f'Syntax error at {file_path}:{start_row + 1}:{start_col + 1}',
    ]
    parts.append(_format_expected_line(expected))
    parts.extend(_format_found_lines(node, node_text))
    parts.extend(_format_source_lines(lines, start_row, start_col))
    parts.append(_what_to_try_for_expected_token(expected, language))
    return parts


def _extract_node_text(code: str, start_byte: int | None, end_byte: int | None) -> str:
    if start_byte is None or end_byte is None:
        return ''
    b = code.encode('utf-8')
    if 0 <= start_byte < end_byte <= len(b):
        return b[start_byte:end_byte].decode('utf-8', errors='replace')
    return ''


def _format_expected_line(expected: str | None) -> str:
    if expected:
        return f'Expected: `{expected}` (grammar token)'
    return 'Expected: (not inferred — parser landed on an ERROR node)'


def _format_found_lines(node: Any, node_text: str) -> list[str]:
    parts: list[str] = []
    if node_text:
        preview = node_text.replace('\n', '\\n')
        if len(preview) > 120:
            preview = preview[:117] + '...'
        parts.append(f'Found: {preview!r}')
    elif getattr(node, 'type', None) == 'ERROR' and not getattr(node, 'is_missing', False):
        parts.append('Found: unexpected token(s) at this position (see source line below).')
    return parts


def _format_source_lines(lines: list[str], start_row: int, start_col: int) -> list[str]:
    parts: list[str] = []
    if isinstance(start_row, int) and 0 <= start_row < len(lines):
        src_line = lines[start_row]
        parts.append(f'  {src_line}')
        parts.append(f'  {" " * start_col}^')
    return parts
