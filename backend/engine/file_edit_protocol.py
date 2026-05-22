"""Two-mode file editing protocol.

Normal Grinta tools remain provider-native JSON/function calls. File content is
captured only after ``start_file_edit`` opens an editor transaction, then the
runtime parses a strict heredoc-style block and converts the raw content into
the existing internal file-editor action shape.
"""

from __future__ import annotations

import os
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from backend.core.errors import FunctionCallValidationError
from backend.core.logger import app_logger as logger
from backend.core.type_safety.path_validation import PathValidationError, SafePath
from backend.engine.function_calling_helpers import parse_bool_argument, set_security_risk
from backend.ledger.action import FileEditAction
from backend.ledger.action.files import StartFileEditAction
from backend.ledger.observation import AgentThinkObservation, ErrorObservation, Observation

TransactionStatus = Literal[
    'pending_content',
    'content_captured',
    'applying',
    'applied',
    'failed',
    'cancelled',
]

DEFAULT_MAX_CONTENT_SIZE = int(
    os.getenv('GRINTA_EDITOR_MODE_MAX_CONTENT_BYTES', '100000')
)
_SESSION_NONE_KEY = '__grinta_default_session__'
_OPEN_TAG_RE = re.compile(r'^<file_edit(?:\s+transaction_id="([^"]+)")?>$')

CONTENT_REQUIRED_OPERATIONS = frozenset({'insert', 'replace_range'})
UNSUPPORTED_START_FILE_EDIT_OPERATIONS = frozenset(
    {
        'create',
        'read',
        'undo',
        'find_symbol',
        'edit_symbol',
        'edit_symbols',
        'multi_edit',
        'rename_symbol',
        'normalize_indent',
    }
)
VALID_START_FILE_EDIT_OPERATIONS = (
    CONTENT_REQUIRED_OPERATIONS
    | UNSUPPORTED_START_FILE_EDIT_OPERATIONS
)
PROHIBITED_CONTENT_FIELDS = frozenset(
    {
        'content',
        'new_content',
        'replacement',
        'replacement_text',
        'file_body',
        'file_text',
        'new_str',
        'new_body',
        'new_code',
        'edits',
        'file_edits',
    }
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _session_key(session_id: str | None) -> str:
    return session_id or _SESSION_NONE_KEY


@dataclass
class EditTransaction:
    transaction_id: str
    session_id: str | None
    path: str
    operation: str
    delimiter: str
    metadata: dict[str, Any]
    status: TransactionStatus
    retry_count: int = 0
    max_retries: int = 2
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def touch(self, *, status: TransactionStatus | None = None) -> None:
        if status is not None:
            self.status = status
        self.updated_at = _now()


@dataclass(frozen=True)
class ParseResult:
    ok: bool
    content: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class EditTransactionStore:
    """Thread-safe active transaction store keyed by session id."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._active: dict[str, EditTransaction] = {}

    def create_transaction(
        self,
        session_id: str | None,
        path: str,
        operation: str,
        metadata: dict[str, Any],
    ) -> EditTransaction:
        txn = EditTransaction(
            transaction_id=f'edit_{secrets.token_hex(12)}',
            session_id=session_id,
            path=path,
            operation=operation,
            delimiter=f'GRINTA_END_{secrets.token_hex(12)}',
            metadata=dict(metadata),
            status='pending_content',
        )
        with self._lock:
            self._active[_session_key(session_id)] = txn
        logger.info(
            'EDIT_TRANSACTION_STARTED session=%s transaction=%s path=%s operation=%s',
            session_id,
            txn.transaction_id,
            path,
            operation,
        )
        return txn

    def get_active_transaction(self, session_id: str | None) -> EditTransaction | None:
        with self._lock:
            return self._active.get(_session_key(session_id))

    def set_active_transaction(
        self, session_id: str | None, txn: EditTransaction
    ) -> None:
        txn.touch()
        with self._lock:
            self._active[_session_key(session_id)] = txn

    def clear_active_transaction(self, session_id: str | None) -> None:
        with self._lock:
            txn = self._active.pop(_session_key(session_id), None)
        if txn is not None:
            logger.info(
                'EDIT_TRANSACTION_CLEARED session=%s transaction=%s',
                session_id,
                txn.transaction_id,
            )

    def update_transaction(
        self, session_id: str | None, txn: EditTransaction
    ) -> None:
        txn.touch()
        with self._lock:
            self._active[_session_key(session_id)] = txn


_TRANSACTION_STORE = EditTransactionStore()


def get_transaction_store() -> EditTransactionStore:
    return _TRANSACTION_STORE


def operation_requires_content(operation: str, metadata: dict[str, Any] | None = None) -> bool:
    op = operation.strip().lower()
    return op in CONTENT_REQUIRED_OPERATIONS


def reject_content_fields(arguments: dict[str, Any]) -> None:
    present = sorted(k for k in arguments if k in PROHIBITED_CONTENT_FIELDS)
    if present:
        raise FunctionCallValidationError(
            'start_file_edit does not accept file content fields. '
            f'Remove these metadata keys and provide raw content in EDITOR MODE: {present}'
        )


def validate_start_file_edit_metadata(
    operation: str,
    path: str,
    metadata: dict[str, Any],
) -> None:
    op = operation.strip().lower()
    if op not in VALID_START_FILE_EDIT_OPERATIONS:
        raise FunctionCallValidationError(
            f"Unsupported start_file_edit operation '{operation}'. "
            f'Valid operations: {sorted(VALID_START_FILE_EDIT_OPERATIONS)}'
        )
    if op in UNSUPPORTED_START_FILE_EDIT_OPERATIONS:
        raise FunctionCallValidationError(
            f"Operation '{op}' needs multiple or structure-aware payload handling and "
            'is not supported by the two-mode start_file_edit path yet. '
            'Use replace_range with explicit file context or the AST tools.'
        )
    if not isinstance(path, str) or not path.strip():
        raise FunctionCallValidationError('start_file_edit requires path')

    required_by_operation = {
        'insert': ('insert_line',),
        'replace_range': ('start_line', 'end_line'),
    }
    missing = [
        name
        for name in required_by_operation.get(op, ())
        if metadata.get(name) in (None, '')
    ]
    if missing:
        raise FunctionCallValidationError(
            f"start_file_edit operation '{op}' is missing required metadata: {missing}"
        )


def parse_editor_response(
    response_text: str,
    txn: EditTransaction,
    *,
    max_content_size: int = DEFAULT_MAX_CONTENT_SIZE,
) -> ParseResult:
    """Parse strict FILE EDITOR MODE output while preserving raw content."""
    try:
        lines = response_text.splitlines(keepends=True)
        lines = _unwrap_markdown_fence_wrapper(lines) or lines
        first = _first_non_ws_line(lines)
        last = _last_non_ws_line(lines)
        if first is None or last is None:
            return ParseResult(
                ok=False,
                error_code='MISSING_OPEN_TAG',
                error_message='Missing opening <file_edit> tag.',
            )

        open_line = lines[first].rstrip('\r\n')
        if _line_has_markdown_fence(open_line):
            return _markdown_fence_error()

        match = _OPEN_TAG_RE.match(open_line.strip())
        if not match:
            if open_line.strip().startswith('<file_edit'):
                return ParseResult(
                    ok=False,
                    error_code='MISSING_OPEN_TAG',
                    error_message='Opening tag must be on its own line.',
                )
            return ParseResult(
                ok=False,
                error_code='MISSING_OPEN_TAG',
                error_message='Opening tag must be the first non-whitespace line.',
            )

        close_idx = _find_delimiter_index(lines, first + 1, txn.delimiter)
        if close_idx is None:
            return ParseResult(
                ok=False,
                error_code='MISSING_DELIMITER',
                error_message=(
                    f'Missing delimiter {txn.delimiter} on its own line.'
                ),
            )

        if _count_delimiter_lines(lines, txn.delimiter) != 1:
            return ParseResult(
                ok=False,
                error_code='MISSING_DELIMITER',
                error_message='Delimiter must appear exactly once on its own line.',
            )

        closing_line_idx = close_idx + 1
        if closing_line_idx >= len(lines) or lines[closing_line_idx].strip() != '</file_edit>':
            return ParseResult(
                ok=False,
                error_code='MISSING_CLOSE_TAG',
                error_message='Closing </file_edit> tag must immediately follow the delimiter line.',
            )

        if closing_line_idx != last:
            if _has_markdown_fence(lines[closing_line_idx + 1 :]):
                return _markdown_fence_error()
            return ParseResult(
                ok=False,
                error_code='EXTRA_TEXT_OUTSIDE_BLOCK',
                error_message='Only whitespace is allowed after the closing </file_edit> tag.',
            )
        if first != 0 and any(line.strip() for line in lines[:first]):
            if _has_markdown_fence(lines[:first]):
                return _markdown_fence_error()
            return ParseResult(
                ok=False,
                error_code='EXTRA_TEXT_OUTSIDE_BLOCK',
                error_message='No explanatory text is allowed before the file_edit block.',
            )

        content = ''.join(lines[first + 1 : close_idx])
        if len(content.encode('utf-8')) > max_content_size:
            return ParseResult(
                ok=False,
                error_code='CONTENT_TOO_LARGE',
                error_message=(
                    f'Editor content exceeds the {max_content_size} byte limit.'
                ),
            )
        if content == '':
            return ParseResult(
                ok=False,
                error_code='EMPTY_CONTENT_NOT_ALLOWED',
                error_message='Empty editor content is not allowed for this operation.',
            )

        return ParseResult(ok=True, content=content)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug('EDITOR_PARSE_FAILED unexpected error', exc_info=True)
        return ParseResult(
            ok=False,
            error_code='UNKNOWN_PARSE_ERROR',
            error_message=str(exc),
        )


def _first_non_ws_line(lines: list[str]) -> int | None:
    for idx, line in enumerate(lines):
        if line.strip():
            return idx
    return None


def _last_non_ws_line(lines: list[str]) -> int | None:
    for idx in range(len(lines) - 1, -1, -1):
        if lines[idx].strip():
            return idx
    return None


def _unwrap_markdown_fence_wrapper(lines: list[str]) -> list[str] | None:
    """Accept a single markdown fence that wraps only the required block.

    The model sometimes adds a whole-response ```xml fence despite editor-mode
    instructions. Treat that as transport noise, but keep rejecting fences mixed
    with prose or placed only before/after the block.
    """
    first = _first_non_ws_line(lines)
    last = _last_non_ws_line(lines)
    if first is None or last is None:
        return None
    if not (_line_has_markdown_fence(lines[first]) and _line_has_markdown_fence(lines[last])):
        return None
    if first == last:
        return None
    inner = lines[first + 1 : last]
    inner_first = _first_non_ws_line(inner)
    inner_last = _last_non_ws_line(inner)
    if inner_first is None or inner_last is None:
        return None
    first_inner_text = inner[inner_first].strip()
    last_inner_text = inner[inner_last].strip()
    if not first_inner_text.startswith('<file_edit'):
        return None
    if last_inner_text != '</file_edit>':
        return None
    return inner


def _line_has_markdown_fence(line: str) -> bool:
    return line.strip().startswith('```')


def _has_markdown_fence(lines: list[str]) -> bool:
    return any(_line_has_markdown_fence(line) for line in lines)


def _markdown_fence_error() -> ParseResult:
    return ParseResult(
        ok=False,
        error_code='MARKDOWN_FENCE_DETECTED',
        error_message='Markdown fences are not allowed around the file_edit block.',
    )


def _find_delimiter_index(
    lines: list[str], start: int, delimiter: str
) -> int | None:
    for idx in range(start, len(lines)):
        if lines[idx].rstrip('\r\n') == delimiter:
            return idx
    return None


def _count_delimiter_lines(lines: list[str], delimiter: str) -> int:
    return sum(1 for line in lines if line.rstrip('\r\n') == delimiter)


def build_editor_mode_prompt(
    txn: EditTransaction,
    target_context: str | None = None,
    parse_error: ParseResult | None = None,
) -> str:
    lines = [
        'You are in FILE EDITOR MODE.',
        '',
        'You are not in normal tool-calling mode.',
        'No tools are available.',
        'Do not output JSON.',
        'Do not output markdown.',
        'Do not explain.',
        'Do not include code fences.',
        'Do not include commentary.',
        'Output exactly one file_edit block.',
        'replace_range overwrites the inclusive line range; it does not insert.',
        '',
        'Transaction:',
        f'- path: {txn.path}',
        f'- operation: {txn.operation}',
        f'- delimiter: {txn.delimiter}',
        '',
    ]
    if parse_error is not None and not parse_error.ok:
        lines.extend(
            [
                'Previous editor response was rejected:',
                f'- error_code: {parse_error.error_code}',
                f'- error_message: {parse_error.error_message}',
                '',
            ]
        )
    if target_context:
        lines.extend(['Current target content:', '<current_target>', target_context, '</current_target>', ''])
    lines.extend(
        [
            'Required output format:',
            '<file_edit>',
            '[raw replacement content only]',
            txn.delimiter,
            '</file_edit>',
            '',
            'Do not include transaction_id in the opening tag; the runtime handles it.',
            'The delimiter must appear exactly once, on its own line.',
            'The closing tag must immediately follow the delimiter line.',
            'Everything between opening tag and delimiter is raw file content.',
            'Do not serialize it as JSON or a tool payload.',
        ]
    )
    return '\n'.join(lines)


def build_file_edit_action_from_transaction(
    content: str,
    txn: EditTransaction,
) -> FileEditAction:
    metadata = dict(txn.metadata)
    expected_file_hash = metadata.get('expected_file_hash') or metadata.get(
        'expected_old_hash'
    )
    op = txn.operation

    if op == 'create':
        return _with_security(
            FileEditAction(
                path=txn.path,
                command='create_file',
                file_text=content,
                overwrite_existing=parse_bool_argument(
                    metadata.get('overwrite_existing', False)
                ),
                expected_file_hash=expected_file_hash,
            ),
            metadata,
        )
    if op == 'insert':
        return _with_security(
            FileEditAction(
                path=txn.path,
                command='insert_text',
                insert_line=int(metadata['insert_line']),
                new_str=content,
            ),
            metadata,
        )
    if op == 'replace_range':
        return _with_security(
            FileEditAction(
                path=txn.path,
                command='edit',
                edit_mode='range',
                start_line=int(metadata['start_line']),
                end_line=int(metadata['end_line']),
                new_str=content,
                expected_file_hash=expected_file_hash,
            ),
            metadata,
        )
    raise FunctionCallValidationError(
        f"Operation '{op}' does not accept editor-mode content."
    )


def _with_security(action: FileEditAction, metadata: dict[str, Any]) -> FileEditAction:
    set_security_risk(action, metadata)
    return action


def apply_edit_from_transaction(
    content: str | None,
    txn: EditTransaction,
) -> FileEditAction:
    """Build the existing internal editor action from captured raw content."""
    if content is None:
        raise FunctionCallValidationError('Editor transaction content is missing.')
    return build_file_edit_action_from_transaction(content, txn)


def start_file_edit_transaction(runtime: Any, action: StartFileEditAction) -> Observation:
    """Runtime-side handler for the metadata-only start_file_edit action."""
    metadata = dict(action.metadata or {})
    operation = action.operation.strip().lower()
    try:
        validate_start_file_edit_metadata(operation, action.path, metadata)
        _validate_path_against_runtime(runtime, action.path)
        if not operation_requires_content(operation, metadata):
            raise FunctionCallValidationError(
                f"start_file_edit operation '{operation}' is not supported. "
                'Use the standalone read/create/find_symbol/undo tools instead.'
            )
        session_id = action.session_id or getattr(runtime, 'sid', None)
        txn = get_transaction_store().create_transaction(
            session_id=session_id,
            path=action.path,
            operation=operation,
            metadata=metadata,
        )
        action.session_id = session_id
        action.transaction_id = txn.transaction_id
        action.delimiter = txn.delimiter
        obs = AgentThinkObservation(
            content=(
                f'EDITOR_MODE_REQUIRED: transaction {txn.transaction_id} '
                f'for {operation} {action.path}'
            ),
            suppress_cli=True,
        )
        obs.tool_result = {
            'ok': True,
            'status': 'editor_mode_required',
            'transaction_id': txn.transaction_id,
            'delimiter': txn.delimiter,
            'path': txn.path,
            'operation': txn.operation,
            'instructions': (
                'The runtime will enter EDITOR MODE. Do not include file content in tool arguments.'
            ),
        }
        return obs
    except (FunctionCallValidationError, PathValidationError, ValueError) as exc:
        get_transaction_store().clear_active_transaction(action.session_id)
        return ErrorObservation(content=f'start_file_edit failed: {exc}')


def _validate_path_against_runtime(runtime: Any, path: str) -> None:
    editor = getattr(runtime, 'file_editor', None)
    resolver = getattr(editor, '_resolve_path_safe', None)
    if callable(resolver):
        resolver(path)
        return

    workspace_root = (
        getattr(runtime, 'workspace_root', None)
        or getattr(runtime, '_initial_cwd', None)
        or getattr(runtime, 'initial_cwd', None)
        or Path.cwd()
    )
    SafePath.validate(path, workspace_root=str(workspace_root), must_be_relative=True)


def build_target_context(
    txn: EditTransaction,
    workspace_root: str | Path | None,
    *,
    max_lines: int = 80,
) -> str | None:
    if workspace_root is None or txn.operation == 'create':
        return None
    try:
        safe = SafePath.validate(
            txn.path,
            workspace_root=workspace_root,
            must_exist=True,
            must_be_relative=True,
        )
        text = safe.path.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return None

    lines = text.splitlines(keepends=True)
    if not lines:
        return ''
    if txn.operation == 'replace_range':
        start = max(int(txn.metadata.get('start_line', 1)) - 1, 0)
        end = min(int(txn.metadata.get('end_line', start + 1)), len(lines))
        return ''.join(lines[start:end])
    if txn.operation == 'insert':
        insert_line = int(txn.metadata.get('insert_line', 0))
        start = max(insert_line - 5, 0)
        end = min(insert_line + 5, len(lines))
        return ''.join(lines[start:end])
    return ''.join(lines[:max_lines])
