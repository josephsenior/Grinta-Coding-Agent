"""Shared syntax validation helpers for post-edit verification.

This module is intentionally small and dependency-light: callers can ask one
question ("does this whole file parse?") without knowing whether the answer
comes from a native compiler/parser or tree-sitter.
"""

from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass
from typing import Any, Literal

SyntaxStatus = Literal['passed', 'failed', 'skipped']


@dataclass(frozen=True)
class SyntaxCheckResult:
    """Structured result for a whole-file syntax check."""

    path: str
    status: SyntaxStatus
    language: str | None = None
    checker: str | None = None
    detail: str = ''
    line: int | None = None
    column: int | None = None

    @property
    def ok(self) -> bool:
        return self.status != 'failed'

    def as_legacy_tuple(self) -> tuple[bool, str] | None:
        """Return the historical ``(ok, detail)`` shape used by middleware."""
        if self.status == 'skipped':
            return None
        return (self.status == 'passed', self.detail)


def check_syntax(path: str, content: str | bytes | None = None) -> SyntaxCheckResult:
    """Validate a whole file using the strongest cheap checker available.

    Python uses ``compile`` so compiler-phase syntax errors such as top-level
    ``return`` are caught. JSON/TOML use native parsers. Everything else goes
    through tree-sitter when a parser is available.
    """
    try:
        from backend.utils.treesitter.treesitter_editor import (
            LANGUAGE_EXTENSIONS,
            TREE_SITTER_AVAILABLE,
            _get_parser,
        )
    except Exception as exc:
        return SyntaxCheckResult(
            path=path,
            status='skipped',
            detail=f'syntax checker unavailable: {exc}',
        )

    _, ext = os.path.splitext(path)
    ext = ext.lower()
    language = LANGUAGE_EXTENSIONS.get(ext)
    if not language:
        return SyntaxCheckResult(
            path=path,
            status='skipped',
            detail='no parser mapping for file extension',
        )

    raw = _content_to_bytes(path, content)
    if raw is None:
        return SyntaxCheckResult(
            path=path,
            status='skipped',
            language=language,
            detail='file content unavailable',
        )

    native = _native_syntax_check(path, ext, language, raw)
    if native is not None:
        return native

    if not TREE_SITTER_AVAILABLE or _get_parser is None:
        return SyntaxCheckResult(
            path=path,
            status='skipped',
            language=language,
            detail='tree-sitter unavailable',
        )

    try:
        parser = _get_parser(language)
    except Exception as exc:
        return SyntaxCheckResult(
            path=path,
            status='skipped',
            language=language,
            detail=f'tree-sitter parser unavailable: {exc}',
        )
    if not parser:
        return SyntaxCheckResult(
            path=path,
            status='skipped',
            language=language,
            detail='tree-sitter parser unavailable',
        )

    tree = parser.parse(raw)
    errors = collect_tree_sitter_syntax_errors(tree.root_node, raw, max_errors=5)
    if errors:
        detail = '; '.join(errors)
        line, column = _first_line_column(detail)
        return SyntaxCheckResult(
            path=path,
            status='failed',
            language=language,
            checker='tree-sitter',
            detail=detail,
            line=line,
            column=column,
        )

    return SyntaxCheckResult(
        path=path,
        status='passed',
        language=language,
        checker='tree-sitter',
    )


def collect_tree_sitter_syntax_errors(
    node: Any, source: bytes, max_errors: int = 5
) -> list[str]:
    """Walk a tree-sitter AST and collect ERROR/MISSING node descriptions."""
    errors: list[str] = []

    def _walk(n: Any) -> None:
        if len(errors) >= max_errors:
            return
        if n.type == 'ERROR' or n.is_missing:
            row = n.start_point[0] + 1
            col = n.start_point[1] + 1
            snippet = source[n.start_byte : n.end_byte].decode(
                'utf-8', errors='replace'
            )
            if len(snippet) > 60:
                snippet = snippet[:60] + '...'
            kind = 'missing node' if n.is_missing else 'syntax error'
            errors.append(f'line {row}:{col} {kind}: {snippet!r}')
            return
        for child in n.children:
            _walk(child)

    _walk(node)
    return errors


def _content_to_bytes(path: str, content: str | bytes | None) -> bytes | None:
    if isinstance(content, bytes):
        return content
    if isinstance(content, str):
        return content.encode('utf-8')
    try:
        with open(path, 'rb') as f:
            return f.read()
    except (OSError, IOError):
        return None


def _native_syntax_check(
    path: str, ext: str, language: str, raw: bytes
) -> SyntaxCheckResult | None:
    code = raw.decode('utf-8', errors='replace')
    if language == 'python':
        return _python_compile_check(path, code)
    if ext == '.json':
        return _json_check(path, language, code)
    if language == 'toml':
        return _toml_check(path, language, code)
    return None


def _python_compile_check(path: str, code: str) -> SyntaxCheckResult:
    try:
        compile(code, path, 'exec')
    except SyntaxError as exc:
        detail = _render_python_syntax_error(exc, code, path)
        return SyntaxCheckResult(
            path=path,
            status='failed',
            language='python',
            checker='python-compile',
            detail=detail,
            line=exc.lineno,
            column=exc.offset,
        )
    return SyntaxCheckResult(
        path=path,
        status='passed',
        language='python',
        checker='python-compile',
    )


def _json_check(path: str, language: str, code: str) -> SyntaxCheckResult:
    try:
        json.loads(code)
    except json.JSONDecodeError as exc:
        detail = (
            f'JSON syntax error at {path}: line {exc.lineno}:{exc.colno}: {exc.msg}'
        )
        return SyntaxCheckResult(
            path=path,
            status='failed',
            language=language,
            checker='json',
            detail=detail,
            line=exc.lineno,
            column=exc.colno,
        )
    return SyntaxCheckResult(
        path=path,
        status='passed',
        language=language,
        checker='json',
    )


def _toml_check(path: str, language: str, code: str) -> SyntaxCheckResult:
    try:
        tomllib.loads(code)
    except tomllib.TOMLDecodeError as exc:
        detail = f'TOML syntax error at {path}: {exc}'
        return SyntaxCheckResult(
            path=path,
            status='failed',
            language=language,
            checker='tomllib',
            detail=detail,
        )
    return SyntaxCheckResult(
        path=path,
        status='passed',
        language=language,
        checker='tomllib',
    )


def _render_python_syntax_error(exc: SyntaxError, code: str, path: str) -> str:
    try:
        from backend.utils.treesitter.treesitter_editor import _render_python_syntax_error

        return _render_python_syntax_error(exc, code, path)
    except Exception:
        lineno = exc.lineno or 1
        offset = exc.offset or 1
        return (
            f'Python syntax error at {path}: line {lineno}:{offset}: '
            f'{exc.msg or "invalid syntax"}'
        )


def _first_line_column(detail: str) -> tuple[int | None, int | None]:
    match = re.search(r'line\s+(\d+)(?::(\d+))?', detail)
    if not match:
        return None, None
    line = int(match.group(1))
    column = int(match.group(2)) if match.group(2) else None
    return line, column


__all__ = [
    'SyntaxCheckResult',
    'check_syntax',
    'collect_tree_sitter_syntax_errors',
]
