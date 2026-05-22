"""Two-mode file editing protocol.

Normal Grinta tools remain provider-native JSON/function calls. File content is
captured only after ``start_file_edit`` opens an editor transaction, then the
runtime parses a strict heredoc-style block and converts the raw content into
the existing internal file-editor action shape.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

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

EditorPayloadKind = Literal['raw_text', 'json_document']

DEFAULT_MAX_CONTENT_SIZE = int(
    os.getenv('GRINTA_EDITOR_MODE_MAX_CONTENT_BYTES', '100000')
)
_SESSION_NONE_KEY = '__grinta_default_session__'
_OPEN_TAG_RE = re.compile(r'^<file_edit(?:\s+transaction_id="([^"]+)")?>$')
_SYMBOL_OPEN_TAG_RE = re.compile(r'^<symbol\s+name="([^"]+)">$')
_EDIT_OPEN_TAG_RE = re.compile(r'^<edit\s+index="(\d+)">$')

UNSUPPORTED_START_FILE_EDIT_OPERATIONS = frozenset(
    {
        'create',
        'read',
        'undo',
        'find_symbol',
        'rename_symbol',
        'normalize_indent',
    }
)
CONTENT_REQUIRED_OPERATIONS = frozenset(
    {'insert', 'replace_range', 'edit_symbol', 'edit_symbols', 'multi_edit'}
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


class EditorContentValidationError(FunctionCallValidationError):
    """Editor-mode content was well-framed but invalid for the target operation."""


@dataclass(frozen=True)
class EditorPayloadSpec:
    kind: EditorPayloadKind
    summary: str
    details: tuple[str, ...] = ()


_EDITOR_PAYLOAD_SPECS: dict[str, EditorPayloadSpec] = {
    'insert': EditorPayloadSpec(
        kind='raw_text',
        summary='Output only the text to insert.',
        details=('Write plain file text with real newlines.',),
    ),
    'replace_range': EditorPayloadSpec(
        kind='raw_text',
        summary='Output only the replacement text for the requested line range.',
        details=('replace_range overwrites the inclusive line range; it does not insert.',),
    ),
    'edit_symbol': EditorPayloadSpec(
        kind='raw_text',
        summary='Output only the complete replacement body/content for the target symbol.',
        details=('edit_symbol replaces the complete body/content for the target symbol.',),
    ),
    'edit_symbols': EditorPayloadSpec(
        kind='raw_text',
        summary='Inside the block, output one raw <symbol> block per target symbol.',
        details=(
            'Each <symbol> block contains raw replacement body text for exactly one symbol.',
        ),
    ),
    'multi_edit': EditorPayloadSpec(
        kind='raw_text',
        summary='Inside the block, output one raw <edit> block per batch item.',
        details=(
            'Each <edit> block contains only the raw content for that item.',
        ),
    ),
}


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
    if op != 'multi_edit' and (not isinstance(path, str) or not path.strip()):
        raise FunctionCallValidationError('start_file_edit requires path')

    required_by_operation = {
        'insert': ('insert_line',),
        'replace_range': ('start_line', 'end_line'),
        'edit_symbol': ('symbol_name',),
        'edit_symbols': ('symbol_names',),
        'multi_edit': ('batch_operations',),
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
    if op == 'edit_symbols':
        raw_names = metadata.get('symbol_names')
        if not isinstance(raw_names, list) or not raw_names:
            raise FunctionCallValidationError(
                "start_file_edit operation 'edit_symbols' requires non-empty symbol_names."
            )
        cleaned: list[str] = []
        seen: set[str] = set()
        for idx, name in enumerate(raw_names):
            if not isinstance(name, str) or not name.strip():
                raise FunctionCallValidationError(
                    f"edit_symbols symbol_names[{idx}] must be a non-empty string."
                )
            value = name.strip()
            if value in seen:
                raise FunctionCallValidationError(
                    f"edit_symbols symbol_names contains duplicate symbol {value!r}."
                )
            seen.add(value)
            cleaned.append(value)
        metadata['symbol_names'] = cleaned
    if op == 'multi_edit':
        raw_ops = metadata.get('batch_operations')
        if not isinstance(raw_ops, list) or not raw_ops:
            raise FunctionCallValidationError(
                "start_file_edit operation 'multi_edit' requires non-empty batch_operations."
            )
        normalized_ops: list[dict[str, Any]] = []
        for idx, item in enumerate(raw_ops):
            if not isinstance(item, dict):
                raise FunctionCallValidationError(
                    f'multi_edit batch_operations[{idx}] must be an object.'
                )
            item_path = item.get('path')
            item_op = str(item.get('operation', '')).strip().lower()
            if not isinstance(item_path, str) or not item_path.strip():
                raise FunctionCallValidationError(
                    f'multi_edit batch_operations[{idx}] requires path.'
                )
            if item_op not in {'replace_file', 'replace_range', 'edit_symbol'}:
                raise FunctionCallValidationError(
                    f"multi_edit batch_operations[{idx}] has unsupported operation {item_op!r}."
                )
            normalized_item = dict(item)
            normalized_item['path'] = item_path.strip()
            normalized_item['operation'] = item_op
            if item_op == 'replace_range':
                if item.get('start_line') is None or item.get('end_line') is None:
                    raise FunctionCallValidationError(
                        f'multi_edit batch_operations[{idx}] replace_range requires start_line and end_line.'
                    )
            if item_op == 'edit_symbol':
                if not isinstance(item.get('symbol_name'), str) or not str(item.get('symbol_name', '')).strip():
                    raise FunctionCallValidationError(
                        f'multi_edit batch_operations[{idx}] edit_symbol requires symbol_name.'
                    )
                normalized_item['symbol_name'] = str(item['symbol_name']).strip()
            normalized_ops.append(normalized_item)
        metadata['batch_operations'] = normalized_ops


def prepare_editor_transaction_metadata(
    operation: str,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    prepared = dict(metadata)
    if operation == 'edit_symbols':
        prepared['editor_items'] = [
            {
                'name': name,
                'delimiter': f'GRINTA_ITEM_END_{secrets.token_hex(12)}',
            }
            for name in cast(list[str], prepared.get('symbol_names', []))
        ]
    elif operation == 'multi_edit':
        editor_items: list[dict[str, Any]] = []
        for idx, item in enumerate(cast(list[dict[str, Any]], prepared.get('batch_operations', [])), start=1):
            editor_items.append(
                {
                    'index': idx,
                    'delimiter': f'GRINTA_ITEM_END_{secrets.token_hex(12)}',
                    **item,
                }
            )
        prepared['editor_items'] = editor_items
    return prepared


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
    spec = _EDITOR_PAYLOAD_SPECS.get(
        txn.operation,
        EditorPayloadSpec(
            kind='raw_text',
            summary='Output only the requested file text.',
        ),
    )
    lines = [
        'You are in FILE EDITOR MODE.',
        '',
        'You are not in normal tool-calling mode.',
        'No tools are available.',
        'Do not output markdown.',
        'Do not explain.',
        'Do not include code fences.',
        'Do not include commentary.',
        'Output exactly one file_edit block.',
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
    payload_rules = [
        spec.summary,
        *spec.details,
        'Do not add prose, tool-call syntax, or markdown fences inside the block.',
        'Do not serialize raw code as JSON strings or escaped newline sequences.',
    ]
    lines.extend(['Required output format:', '<file_edit>'])
    if txn.operation == 'edit_symbols':
        editor_items = cast(list[dict[str, Any]], txn.metadata.get('editor_items', []))
        for item in editor_items:
            lines.extend(
                [
                    f'<symbol name="{item["name"]}">',
                    f'[raw replacement body for {item["name"]}]',
                    item['delimiter'],
                    '</symbol>',
                ]
            )
    elif txn.operation == 'multi_edit':
        editor_items = cast(list[dict[str, Any]], txn.metadata.get('editor_items', []))
        for item in editor_items:
            lines.extend(
                [
                    f'<edit index="{item["index"]}">',
                    f'[raw content for {item["operation"]} on {item["path"]}]',
                    item['delimiter'],
                    '</edit>',
                ]
            )
    else:
        lines.append('[replacement content starts on the next line]')
    lines.extend(
        [
            txn.delimiter,
            '</file_edit>',
            '',
            'Do not include transaction_id in the opening tag; the runtime handles it.',
            'The delimiter must appear exactly once, on its own line.',
            'The closing tag must immediately follow the delimiter line.',
            'Everything between opening tag and delimiter is the exact payload the runtime will consume.',
            *payload_rules,
        ]
    )
    if txn.operation == 'multi_edit':
        lines.extend(['', 'Batch item metadata:'])
        for item in cast(list[dict[str, Any]], txn.metadata.get('editor_items', [])):
            lines.append(
                f'- index {item["index"]}: {item["operation"]} path={item["path"]}'
            )
            if item['operation'] == 'replace_range':
                lines.append(
                    f'  start_line={item["start_line"]} end_line={item["end_line"]}'
                )
            if item['operation'] == 'edit_symbol':
                lines.append(f'  symbol_name={item["symbol_name"]}')
    if txn.operation == 'edit_symbols':
        lines.extend(['', 'Symbols to edit:'])
        for item in cast(list[dict[str, Any]], txn.metadata.get('editor_items', [])):
            lines.append(f'- {item["name"]}')
    return '\n'.join(lines)


def build_file_edit_action_from_transaction(
    content: str,
    txn: EditTransaction,
) -> Any:
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
    if op == 'edit_symbol':
        symbol_name = str(metadata['symbol_name'])
        line_number = metadata.get('line_number')
        action = FileEditAction(
            path=txn.path,
            command='edit_symbol',
            new_str=content,
            structured_payload={
                'symbol_name': symbol_name,
                **(
                    {'line_number': int(line_number)}
                    if line_number is not None
                    else {}
                ),
            },
        )
        set_security_risk(action, metadata)
        return action
    if op == 'edit_symbols':
        payload = _parse_symbol_editor_blocks(content, txn)
        action = FileEditAction(
            path=txn.path,
            command='edit_symbols',
            structured_payload={'edits': payload},
        )
        set_security_risk(action, metadata)
        return action
    if op == 'multi_edit':
        payload = _parse_multi_edit_editor_blocks(content, txn)
        action = FileEditAction(
            path=txn.path,
            command='multi_edit',
            structured_payload={'file_edits': payload},
        )
        set_security_risk(action, metadata)
        return action
    raise FunctionCallValidationError(
        f"Operation '{op}' does not accept editor-mode content."
    )


def _parse_structured_editor_payload(
    content: str,
    *,
    key: str,
) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise EditorContentValidationError(
            f'Editor-mode payload must be valid JSON for structured edit operations: {exc}'
        ) from exc

    items: Any = parsed
    if isinstance(parsed, dict):
        items = parsed.get(key)
    if not isinstance(items, list) or not items:
        raise EditorContentValidationError(
            f'Editor-mode structured payload must contain a non-empty "{key}" array.'
        )
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise EditorContentValidationError(
                f'Editor-mode structured payload item {idx} must be an object.'
            )
    return items


def _first_non_ws_line_index(lines: list[str], start: int, end: int | None = None) -> int | None:
    limit = len(lines) if end is None else min(end, len(lines))
    for idx in range(start, limit):
        if lines[idx].strip():
            return idx
    return None


def _ensure_only_whitespace(lines: list[str], start: int, end: int) -> None:
    for idx in range(start, end):
        if lines[idx].strip():
            raise EditorContentValidationError(
                'No explanatory text is allowed between editor blocks.'
            )


def _parse_symbol_editor_blocks(
    content: str,
    txn: EditTransaction,
) -> list[dict[str, Any]]:
    lines = content.splitlines(keepends=True)
    specs = cast(list[dict[str, Any]], txn.metadata.get('editor_items', []))
    if not specs:
        raise EditorContentValidationError('edit_symbols transaction is missing editor_items metadata.')

    by_name = {str(item['name']): item for item in specs}
    parsed: dict[str, dict[str, Any]] = {}
    cursor = 0
    while True:
        next_idx = _first_non_ws_line_index(lines, cursor)
        if next_idx is None:
            break
        _ensure_only_whitespace(lines, cursor, next_idx)
        open_line = lines[next_idx].rstrip('\r\n').strip()
        match = _SYMBOL_OPEN_TAG_RE.match(open_line)
        if not match:
            raise EditorContentValidationError('edit_symbols requires <symbol name="..."> blocks only.')
        symbol_name = match.group(1)
        spec = by_name.get(symbol_name)
        if spec is None:
            raise EditorContentValidationError(
                f"Unexpected symbol block {symbol_name!r}; use the symbols requested by the runtime."
            )
        if symbol_name in parsed:
            raise EditorContentValidationError(
                f"Duplicate symbol block {symbol_name!r}."
            )
        delimiter = str(spec['delimiter'])
        close_idx = _find_delimiter_index(lines, next_idx + 1, delimiter)
        if close_idx is None:
            raise EditorContentValidationError(
                f'Missing item delimiter {delimiter} for symbol {symbol_name}.'
            )
        closing_line_idx = close_idx + 1
        if closing_line_idx >= len(lines) or lines[closing_line_idx].strip() != '</symbol>':
            raise EditorContentValidationError(
                f'Closing </symbol> tag must immediately follow the delimiter for symbol {symbol_name}.'
            )
        parsed[symbol_name] = {
            'symbol_name': symbol_name,
            'new_body': ''.join(lines[next_idx + 1 : close_idx]),
        }
        cursor = closing_line_idx + 1

    missing = [str(item['name']) for item in specs if str(item['name']) not in parsed]
    if missing:
        raise EditorContentValidationError(
            f'edit_symbols is missing blocks for: {missing}.'
        )
    return [parsed[str(item['name'])] for item in specs]


def _parse_multi_edit_editor_blocks(
    content: str,
    txn: EditTransaction,
) -> list[dict[str, Any]]:
    lines = content.splitlines(keepends=True)
    specs = cast(list[dict[str, Any]], txn.metadata.get('editor_items', []))
    if not specs:
        raise EditorContentValidationError('multi_edit transaction is missing editor_items metadata.')

    by_index = {int(item['index']): item for item in specs}
    parsed: dict[int, dict[str, Any]] = {}
    cursor = 0
    while True:
        next_idx = _first_non_ws_line_index(lines, cursor)
        if next_idx is None:
            break
        _ensure_only_whitespace(lines, cursor, next_idx)
        open_line = lines[next_idx].rstrip('\r\n').strip()
        match = _EDIT_OPEN_TAG_RE.match(open_line)
        if not match:
            raise EditorContentValidationError('multi_edit requires <edit index="N"> blocks only.')
        index = int(match.group(1))
        spec = by_index.get(index)
        if spec is None:
            raise EditorContentValidationError(
                f'Unexpected multi_edit block index {index}; use the batch items requested by the runtime.'
            )
        if index in parsed:
            raise EditorContentValidationError(f'Duplicate multi_edit block index {index}.')
        delimiter = str(spec['delimiter'])
        close_idx = _find_delimiter_index(lines, next_idx + 1, delimiter)
        if close_idx is None:
            raise EditorContentValidationError(
                f'Missing item delimiter {delimiter} for multi_edit index {index}.'
            )
        closing_line_idx = close_idx + 1
        if closing_line_idx >= len(lines) or lines[closing_line_idx].strip() != '</edit>':
            raise EditorContentValidationError(
                f'Closing </edit> tag must immediately follow the delimiter for multi_edit index {index}.'
            )
        raw_content = ''.join(lines[next_idx + 1 : close_idx])
        operation = str(spec['operation'])
        item_payload = {'path': spec['path']}
        if operation == 'replace_file':
            item_payload.update({'command': 'replace_file', 'new_content': raw_content})
        elif operation == 'replace_range':
            item_payload.update(
                {
                    'command': 'replace_range',
                    'start_line': spec['start_line'],
                    'end_line': spec['end_line'],
                    'new_code': raw_content,
                }
            )
        elif operation == 'edit_symbol':
            item_payload.update(
                {
                    'command': 'edit_symbol',
                    'symbol_name': spec['symbol_name'],
                    'new_body': raw_content,
                    **({'line_number': spec['line_number']} if spec.get('line_number') is not None else {}),
                }
            )
        else:
            raise EditorContentValidationError(
                f'Unsupported multi_edit operation {operation!r}.'
            )
        if spec.get('expected_file_hash') is not None:
            item_payload['expected_file_hash'] = spec['expected_file_hash']
        if spec.get('overwrite_existing') is not None:
            item_payload['overwrite_existing'] = spec['overwrite_existing']
        parsed[index] = item_payload
        cursor = closing_line_idx + 1

    missing = [int(item['index']) for item in specs if int(item['index']) not in parsed]
    if missing:
        raise EditorContentValidationError(
            f'multi_edit is missing blocks for indices: {missing}.'
        )
    return [parsed[int(item['index'])] for item in specs]


def validate_editor_transaction_content(
    content: str,
    txn: EditTransaction,
) -> None:
    """Preflight editor-mode content before dispatching to the existing handlers."""
    if txn.operation == 'edit_symbols':
        items = _parse_symbol_editor_blocks(content, txn)
        for idx, item in enumerate(items):
            symbol_name = item.get('symbol_name')
            new_body = item.get('new_body')
            if not isinstance(symbol_name, str) or not symbol_name.strip():
                raise EditorContentValidationError(
                    f'Editor-mode structured payload item {idx} must include symbol_name.'
                )
            if not isinstance(new_body, str):
                raise EditorContentValidationError(
                    f'Editor-mode structured payload item {idx} must include new_body as a string.'
                )
        return

    if txn.operation == 'multi_edit':
        items = _parse_multi_edit_editor_blocks(content, txn)
        for idx, item in enumerate(items):
            path = item.get('path')
            command = item.get('command')
            if not isinstance(path, str) or not path.strip():
                raise EditorContentValidationError(
                    f'Editor-mode structured payload item {idx} must include path.'
                )
            if not isinstance(command, str) or not command.strip():
                raise EditorContentValidationError(
                    f'Editor-mode structured payload item {idx} must include command or operation.'
                )
        return


def _with_security(action: FileEditAction, metadata: dict[str, Any]) -> FileEditAction:
    set_security_risk(action, metadata)
    return action


def apply_edit_from_transaction(
    content: str | None,
    txn: EditTransaction,
) -> Any:
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
        if operation != 'multi_edit':
            _validate_path_against_runtime(runtime, action.path)
        if not operation_requires_content(operation, metadata):
            raise FunctionCallValidationError(
                f"start_file_edit operation '{operation}' is not supported. "
                'Use the standalone read/create/find_symbol/undo tools instead.'
            )
        metadata = prepare_editor_transaction_metadata(operation, metadata)
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
    if txn.operation == 'edit_symbol':
        try:
            from backend.engine.tools.structure_editor import StructureEditor

            editor = StructureEditor()
            symbol = editor.find_symbol(
                txn.path,
                str(txn.metadata.get('symbol_name', '')),
                None,
            )
            if symbol is not None:
                start = max(symbol.line_start - 1, 0)
                end = min(symbol.line_end, len(lines))
                return ''.join(lines[start:end])
        except Exception:
            return None
    if txn.operation == 'edit_symbols':
        symbol_names = txn.metadata.get('symbol_names')
        if not isinstance(symbol_names, list) or not symbol_names:
            return None
        contexts: list[str] = []
        try:
            from backend.engine.tools.structure_editor import StructureEditor

            editor = StructureEditor()
            for raw_name in symbol_names:
                if not isinstance(raw_name, str) or not raw_name.strip():
                    continue
                symbol = editor.find_symbol(txn.path, raw_name, None)
                if symbol is None:
                    continue
                start = max(symbol.line_start - 1, 0)
                end = min(symbol.line_end, len(lines))
                contexts.append(
                    f'# symbol: {raw_name}\n' + ''.join(lines[start:end])
                )
        except Exception:
            return None
        return '\n\n'.join(contexts) or None
    if txn.operation == 'multi_edit':
        items = txn.metadata.get('editor_items')
        if not isinstance(items, list) or not items:
            return None
        summary_lines = ['Batch targets:']
        for item in items:
            if not isinstance(item, dict):
                continue
            operation = item.get('operation', '')
            path = item.get('path', '')
            line = f'- [{item.get("index")}] {operation} {path}'
            if operation == 'replace_range':
                line += f' lines {item.get("start_line")}-{item.get("end_line")}'
            elif operation == 'edit_symbol':
                line += f' symbol={item.get("symbol_name")}'
            summary_lines.append(line)
        return '\n'.join(summary_lines)
    if txn.operation == 'insert':
        insert_line = int(txn.metadata.get('insert_line', 0))
        start = max(insert_line - 5, 0)
        end = min(insert_line + 5, len(lines))
        return ''.join(lines[start:end])
    return ''.join(lines[:max_lines])
