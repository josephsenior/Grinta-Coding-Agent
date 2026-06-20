"""File edit handlers used by function-calling tool dispatch.

Pure code motion: split from ``backend.engine.function_calling`` to keep
that module under the 40 KB file-size cap. No logic changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from backend.core.enums import FileEditSource
from backend.core.errors import FunctionCallValidationError
from backend.core.tools.tool_names import (
    CREATE_TOOL_NAME,
    EDIT_SYMBOL_TOOL_NAME,
    MULTIEDIT_TOOL_NAME,
    READ_TOOL_NAME,
    REPLACE_STRING_TOOL_NAME,
)
from backend.engine.function_calling.helpers import (
    parse_bool_argument,
    require_tool_argument,
    set_security_risk,
    validate_security_risk,
)
from backend.engine.tools._file_edits_common import _multi_edit_raise
from backend.engine.tools._file_edits_symbols import (
    _build_create_file_action,
    _build_read_file_action,
    _handle_read_range_public,
    _handle_read_symbols_public,
)
from backend.engine.tools._file_ops import (
    _coerce_optional_int,
    _filter_symbol_candidates,
    _find_symbol_candidates,
    _guard_content_arguments,
    _parse_symbol_id,
    _relative_display_path,
    _resolve_symbol_candidates,
    _safe_workspace_path,
    _single_symbol_candidate,
)
from backend.ledger.action import (
    Action,
    AgentThinkAction,
    FileEditAction,
)


def _handle_read_tool(arguments: Mapping[str, Any]) -> Action:
    read_type = (
        str(require_tool_argument(arguments, 'type', READ_TOOL_NAME)).strip().lower()
    )
    if read_type == 'range':
        raise FunctionCallValidationError(
            'read type=range was removed. Use type=file with path, start_line, and end_line.'
        )
    if read_type == 'file':
        path = require_tool_argument(arguments, 'path', READ_TOOL_NAME)
        has_start = arguments.get('start_line') is not None
        has_end = arguments.get('end_line') is not None
        if has_start or has_end:
            if not (has_start and has_end):
                raise FunctionCallValidationError(
                    'read type=file line range requires both start_line and end_line.'
                )
            return _handle_read_range_public(arguments)
        return _build_read_file_action(str(path), {})
    if read_type == 'symbols':
        return _handle_read_symbols_public(arguments)
    raise FunctionCallValidationError("read type must be one of 'file' or 'symbols'.")


def _coerce_insert_position(value: object) -> str:
    position = str(value or '').strip().lower()
    valid = {'before', 'after', 'inside_start', 'inside_end'}
    if position not in valid:
        raise FunctionCallValidationError(
            f'create type=symbol position must be one of {sorted(valid)}.'
        )
    return position


def _insert_line_for_symbol(candidate: dict[str, Any], position: str) -> int:
    start = int(candidate['start_line'])
    end = int(candidate['end_line'])
    if position == 'before':
        return start
    if position == 'after':
        return end + 1
    if position == 'inside_start':
        return start + 1
    return end


def _handle_create_symbol_public(arguments: Mapping[str, Any]) -> Action:
    path = str(require_tool_argument(arguments, 'path', CREATE_TOOL_NAME))
    target_symbol = str(
        require_tool_argument(arguments, 'target_symbol', CREATE_TOOL_NAME)
    )
    content_to_insert = str(
        require_tool_argument(arguments, 'content', CREATE_TOOL_NAME)
    )
    position = _coerce_insert_position(
        require_tool_argument(arguments, 'position', CREATE_TOOL_NAME)
    )
    occurrence = _coerce_optional_int(arguments.get('occurrence'), 'occurrence')
    safe_path, content, candidate = _single_symbol_candidate(
        path=path,
        symbol_name=target_symbol,
        symbol_kind=cast(str | None, arguments.get('target_kind')),
        parent_symbol=cast(str | None, arguments.get('parent_symbol')),
        occurrence=occurrence,
    )
    action = FileEditAction(
        path=_relative_display_path(safe_path),
        command='insert_text',
        insert_line=_insert_line_for_symbol(candidate, position),
        new_str=content_to_insert,
        impl_source=FileEditSource.FILE_EDITOR,
    )
    set_security_risk(action, arguments)
    return action


def _handle_create_tool(arguments: Mapping[str, Any]) -> Action:
    validate_security_risk(arguments, CREATE_TOOL_NAME)
    create_type = (
        str(arguments.get('type', '') or '').strip().lower()
    )
    if not create_type:
        create_type = 'symbol' if arguments.get('target_symbol') else 'file'
    normalized_args = dict(arguments)
    _guard_content_arguments(normalized_args)
    if create_type == 'file':
        path = require_tool_argument(arguments, 'path', CREATE_TOOL_NAME)
        content = require_tool_argument(arguments, 'content', CREATE_TOOL_NAME)
        normalized_args['file_text'] = str(content)
        # Pre-flight existence check: if the file already exists, return a soft
        # guidance message instead of silently overwriting. The LLM has already
        # generated the content (tokens are spent), but this prevents accidental
        # data loss and steers the agent toward the correct edit tool.
        try:
            safe_path = _safe_workspace_path(str(path), must_exist=False)
            if safe_path.exists():
                return AgentThinkAction(
                    thought=(
                        f'File already exists at {path}. '
                        'Use replace_string to modify specific sections, '
                        'or edit_symbol for targeted symbol-level changes. '
                        'Only use create(type="file") for genuinely new files.'
                    ),
                )
        except FunctionCallValidationError:
            pass  # Path validation failed; let the action proceed and fail downstream
        normalized_args['overwrite_existing'] = True
        action = _build_create_file_action(str(path), normalized_args)
        set_security_risk(action, arguments)
        return action
    if create_type == 'symbol':
        return _handle_create_symbol_public(arguments)
    raise FunctionCallValidationError("create type must be 'file' or 'symbol'.")


def _handle_replace_string_tool(arguments: Mapping[str, Any]) -> Action:
    validate_security_risk(arguments, REPLACE_STRING_TOOL_NAME)
    path = str(require_tool_argument(arguments, 'path', REPLACE_STRING_TOOL_NAME))
    old_string = str(
        require_tool_argument(arguments, 'old_string', REPLACE_STRING_TOOL_NAME)
    )
    new_string = str(
        require_tool_argument(arguments, 'new_string', REPLACE_STRING_TOOL_NAME)
    )
    if old_string == '':
        raise FunctionCallValidationError(
            'replace_string old_string must not be empty.'
        )
    _guard_content_arguments(dict(arguments))
    safe_path = _safe_workspace_path(path, must_exist=True)
    action = FileEditAction(
        path=_relative_display_path(safe_path),
        command='replace_string',
        old_string=old_string,
        new_str=new_string,
        replace_all=parse_bool_argument(arguments.get('replace_all', False)),
        impl_source=FileEditSource.FILE_EDITOR,
    )
    set_security_risk(action, arguments)
    return action


def _resolve_symbol_by_id(
    symbol_id: str,
) -> tuple[str, str, int | None, int | None]:
    raw_path, symbol_name, start, end = _parse_symbol_id(symbol_id)
    return raw_path, symbol_name, start, end


def _resolve_symbol_by_name(
    symbol_name: str,
    symbol_kind: str | None,
    parent_symbol: str | None,
    occurrence: int | None,
    raw_path: str,
) -> tuple[Path, list[dict[str, Any]]]:
    if raw_path:
        safe_path, _content, candidates = _resolve_symbol_candidates(
            path=raw_path,
            symbol_name=symbol_name,
            symbol_kind=symbol_kind,
            parent_symbol=parent_symbol,
            occurrence=occurrence,
        )
    else:
        lookup_name = symbol_name.rsplit('.', 1)[-1]
        if not parent_symbol and '.' in symbol_name:
            maybe_parent, _, maybe_name = symbol_name.rpartition('.')
            parent_symbol = maybe_parent or None
            lookup_name = maybe_name
        candidates = _filter_symbol_candidates(
            _find_symbol_candidates(
                lookup_name,
                symbol_kind=symbol_kind,
                include_private=True,
            ),
            symbol_name=lookup_name,
            parent_symbol=parent_symbol,
            occurrence=occurrence,
        )
        safe_path = Path()
    return safe_path, candidates


def _select_and_validate_symbol(
    candidates: list[dict[str, Any]],
    symbol_id: str,
    symbol_name: str,
    requested_start: int | None,
    requested_end: int | None,
    index: int,
    *,
    path: str | None = None,
) -> dict[str, Any]:
    if requested_start is not None:
        candidates = [
            c
            for c in candidates
            if c.get('start_line') == requested_start
            and c.get('end_line') == requested_end
        ]
    if not candidates:
        target = symbol_id or symbol_name
        _multi_edit_raise(
            'edit_symbol failed: symbol not found.',
            error_code='SYMBOL_NOT_FOUND',
            path=path,
            operation='edit_symbol',
            symbol=target,
            retryable=True,
        )
    if len(candidates) > 1:
        from backend.core.errors.structured_edit_errors import (
            symbol_ambiguity_summary,
        )

        _multi_edit_raise(
            symbol_ambiguity_summary(symbol_name, candidates).split('\n')[0],
            error_code='SYMBOL_AMBIGUOUS',
            path=path,
            operation='edit_symbol',
            symbol=symbol_name,
            candidates=candidates,
            retryable=True,
        )
    return candidates[0]


def _build_edit_symbol_target_spec(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Build one deferred symbol edit spec from flat edit_symbol tool arguments."""
    if arguments.get('edits') is not None:
        raise FunctionCallValidationError(
            'edit_symbol edits one symbol per call. '
            'For multiple symbols, multiple ops on one file, or cross-file batches, use multiedit.'
        )

    new_content = arguments.get('new_content')
    if not isinstance(new_content, str):
        raise FunctionCallValidationError('edit_symbol requires new_content.')

    symbol_id = str(arguments.get('symbol_id') or '').strip()
    symbol_name = str(
        arguments.get('qualified_name') or arguments.get('symbol_name') or ''
    ).strip()
    if not symbol_id and not symbol_name:
        raise FunctionCallValidationError(
            'edit_symbol requires qualified_name, symbol_name, or symbol_id.'
        )

    spec: dict[str, Any] = {'new_content': new_content}
    if symbol_id:
        spec['symbol_id'] = symbol_id
    else:
        if arguments.get('qualified_name'):
            spec['qualified_name'] = str(arguments.get('qualified_name')).strip()
        elif arguments.get('symbol_name'):
            spec['symbol_name'] = str(arguments.get('symbol_name')).strip()
        if arguments.get('symbol_kind') is not None:
            spec['symbol_kind'] = arguments.get('symbol_kind')
        if arguments.get('parent_symbol') is not None:
            spec['parent_symbol'] = arguments.get('parent_symbol')
        if arguments.get('occurrence') is not None:
            spec['occurrence'] = arguments.get('occurrence')
    return spec


def _handle_edit_symbol_tool(arguments: Mapping[str, Any]) -> Action:
    validate_security_risk(arguments, EDIT_SYMBOL_TOOL_NAME)
    _guard_content_arguments(dict(arguments))
    path = str(require_tool_argument(arguments, 'path', EDIT_SYMBOL_TOOL_NAME)).strip()
    edit_spec = _build_edit_symbol_target_spec(arguments)
    action = FileEditAction(
        path='.',
        command='multi_edit',
        structured_payload={
            'file_edits': [
                {
                    'path': path,
                    'operation': 'edit_symbol_deferred',
                    'edits': [edit_spec],
                }
            ]
        },
        impl_source=FileEditSource.FILE_EDITOR,
    )
    set_security_risk(action, arguments)
    return action


def _normalize_multiedit_replace_string(
    raw: Mapping[str, Any],
    index: int,
) -> dict[str, Any]:
    path = raw.get('path')
    if not isinstance(path, str) or not path.strip():
        raise FunctionCallValidationError(
            f'multiedit operations[{index}] replace_string requires path.'
        )
    old_string = raw.get('old_string')
    new_string = raw.get('new_string')
    if not isinstance(old_string, str) or not isinstance(new_string, str):
        raise FunctionCallValidationError(
            f'multiedit operations[{index}] replace_string requires old_string and new_string.'
        )
    return {
        'path': path,
        'operation': 'replace_string',
        'old_string': old_string,
        'new_string': new_string,
        'replace_all': parse_bool_argument(raw.get('replace_all', False)),
    }


def _normalize_multiedit_edit_symbol(
    raw: Mapping[str, Any],
    index: int,
) -> list[dict[str, Any]]:
    path = raw.get('path')
    raw_edits = raw.get('edits')
    if raw_edits is None:
        raw_edits = [
            {
                'symbol_id': raw.get('symbol_id'),
                'path': raw.get('path'),
                'qualified_name': raw.get('qualified_name'),
                'symbol_name': raw.get('symbol_name'),
                'symbol_kind': raw.get('symbol_kind'),
                'parent_symbol': raw.get('parent_symbol'),
                'occurrence': raw.get('occurrence'),
                'new_content': raw.get('new_content'),
            }
        ]
    if not isinstance(raw_edits, list) or not raw_edits:
        raise FunctionCallValidationError(
            f'multiedit operations[{index}] edit_symbol requires a non-empty edits array.'
        )
    if not isinstance(path, str) or not path.strip():
        raise FunctionCallValidationError(
            f'multiedit operations[{index}] edit_symbol requires path.'
        )
    normalized_edits: list[dict[str, Any]] = []
    for edit_index, edit in enumerate(raw_edits):
        if not isinstance(edit, Mapping):
            raise FunctionCallValidationError(
                f'multiedit operations[{index}] edits[{edit_index}] must be an object.'
            )
        normalized_edits.append(dict(edit))
    return [
        {
            'path': path.strip(),
            'operation': 'edit_symbol_deferred',
            'edits': normalized_edits,
        }
    ]


def _dispatch_multiedit_operation(
    raw: Mapping[str, Any],
    index: int,
) -> list[dict[str, Any]]:
    command = str(raw.get('command') or '').strip().lower()
    if command == 'replace_string':
        return [_normalize_multiedit_replace_string(raw, index)]
    if command == 'edit_symbol':
        return _normalize_multiedit_edit_symbol(raw, index)
    raise FunctionCallValidationError(
        f'multiedit operations[{index}] command {command!r} is unsupported. '
        'Use replace_string or edit_symbol.'
    )


def _normalize_multiedit_operations(
    arguments: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw_ops = arguments.get('operations')
    if not isinstance(raw_ops, list) or not raw_ops:
        raise FunctionCallValidationError(
            'multiedit requires a non-empty operations array.'
        )
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_ops):
        if not isinstance(raw, Mapping):
            raise FunctionCallValidationError(
                f'multiedit operations[{index}] must be an object.'
            )
        normalized.extend(_dispatch_multiedit_operation(raw, index))
    return normalized


def _handle_multiedit_tool(arguments: Mapping[str, Any]) -> Action:
    validate_security_risk(arguments, MULTIEDIT_TOOL_NAME)
    _guard_content_arguments(dict(arguments))
    operations = _normalize_multiedit_operations(arguments)
    action = FileEditAction(
        path='.',
        command='multi_edit',
        structured_payload={'file_edits': operations},
        impl_source=FileEditSource.FILE_EDITOR,
    )
    set_security_risk(action, arguments)
    return action
