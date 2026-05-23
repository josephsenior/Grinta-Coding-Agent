from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, cast

from backend.core.errors import FunctionCallValidationError
from backend.engine.function_calling_helpers import parse_bool_argument, set_security_risk
from backend.ledger.action import FileEditAction

TransactionStatus = Literal[
    'pending_content',
    'content_captured',
    'applying',
    'applied',
    'failed',
    'cancelled',
]

_SYMBOL_OPEN_TAG_RE = re.compile(r'^<symbol\s+name="([^"]+)">$')
_EDIT_OPEN_TAG_RE = re.compile(r'^<edit\s+index="(\d+)">$')


def _now() -> str:
    return datetime.now(UTC).isoformat()


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


class EditorContentValidationError(FunctionCallValidationError):
    """Editor-mode content was well-framed but invalid for the target operation."""


def _find_delimiter_index(
    lines: list[str], start: int, delimiter: str
) -> int | None:
    for idx in range(start, len(lines)):
        if lines[idx].rstrip('\r\n') == delimiter:
            return idx
    return None


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


def _with_security(action: FileEditAction, metadata: dict[str, Any]) -> FileEditAction:
    set_security_risk(action, metadata)
    return action


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
