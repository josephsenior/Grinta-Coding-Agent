"""File edit handlers used by function-calling tool dispatch.

Pure code motion: split from ``backend.engine.function_calling`` to keep
that module under the 40 KB file-size cap. No logic changes.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import Any, NoReturn, cast

from backend.core.editor_recovery import append_editor_recovery_guidance
from backend.core.enums import FileEditSource, FileReadSource
from backend.core.errors import FunctionCallValidationError
from backend.engine.function_calling_helpers import (
    parse_bool_argument,
    require_tool_argument,
    set_security_risk,
    validate_security_risk,
)
from backend.engine.tools._file_ops import (
    _coerce_optional_int,
    _filter_symbol_candidates,
    _find_symbol_candidates,
    _guard_content_arguments,
    _parse_symbol_id,
    _read_text_for_tool,
    _relative_display_path,
    _resolve_symbol_candidates,
    _safe_workspace_path,
    _sha256_text,
    _single_symbol_candidate,
    _symbol_action_ambiguity_error,
)
from backend.inference.tool_names import (
    CREATE_TOOL_NAME,
    EDIT_SYMBOLS_TOOL_NAME,
    FIND_SYMBOLS_TOOL_NAME,
    MULTIEDIT_TOOL_NAME,
    READ_TOOL_NAME,
    REPLACE_STRING_TOOL_NAME,
)
from backend.ledger.action import (
    Action,
    AgentThinkAction,
    FileEditAction,
    FileReadAction,
    MessageAction,
)


def _build_create_file_action(path: str, arguments: Mapping[str, Any]) -> Action:
    """Build the internal FileEditor action used by create(type="file")."""
    file_text = cast(str, arguments.get('file_text', ''))
    return FileEditAction(
        path=path,
        command='create_file',
        file_text=file_text,
        overwrite_existing=bool(arguments.get('overwrite_existing', False)),
        impl_source=FileEditSource.FILE_EDITOR,
    )


def _build_read_file_action(
    path: str, _arguments: Mapping[str, Any] | None = None
) -> Action:
    """Build the internal FileEditor-backed read action used by read()."""
    view_range = None
    if _arguments is not None:
        raw_view_range = _arguments.get('view_range')
        if isinstance(raw_view_range, list):
            view_range = raw_view_range
    return FileReadAction(
        path=path,
        view_range=view_range,
        impl_source=FileReadSource.FILE_EDITOR,
    )


def _build_symbol_insert_action(path: str, arguments: Mapping[str, Any]) -> Action:
    """Build the internal insertion action used by create(type="symbol")."""
    new_str = cast(str | None, arguments.get('new_str'))
    insert_line = arguments.get('insert_line')
    if new_str is None or insert_line is None:
        raise FunctionCallValidationError(
            'create type=symbol requires resolved insertion text and insertion line.'
        )
    return FileEditAction(
        path=path,
        command='insert_text',
        insert_line=int(insert_line),
        new_str=new_str,
        impl_source=FileEditSource.FILE_EDITOR,
    )


def _handle_read_range_public(arguments: Mapping[str, Any]) -> Action:
    path = require_tool_argument(arguments, 'path', READ_TOOL_NAME)
    start_line = require_tool_argument(arguments, 'start_line', READ_TOOL_NAME)
    end_line = require_tool_argument(arguments, 'end_line', READ_TOOL_NAME)
    try:
        start_i = int(start_line)
        end_i = int(end_line)
    except (TypeError, ValueError) as exc:
        raise FunctionCallValidationError(
            'read type=range requires integer start_line and end_line.'
        ) from exc
    if start_i < 1:
        raise FunctionCallValidationError('read type=range start_line must be >= 1.')
    if end_i != -1 and end_i < start_i:
        raise FunctionCallValidationError(
            'read type=range end_line must be >= start_line, or -1 for EOF.'
        )
    action = _build_read_file_action(
        str(path),
        {
            'view_range': [start_i, end_i],
        },
    )
    return action


def _read_symbol_payload(
    *,
    safe_path: Path,
    content: str,
    candidate: dict[str, Any],
    target: str | None = None,
) -> dict[str, Any]:
    lines = content.splitlines(keepends=True)
    body = ''.join(lines[candidate['start_line'] - 1 : candidate['end_line']])
    return {
        'type': 'symbol',
        'status': 'resolved',
        'target': target or candidate.get('name'),
        **candidate,
        'file_rev': _sha256_text(content),
        'symbol_hash': _sha256_text(body),
        'content': body,
        'path': _relative_display_path(safe_path),
    }


def _resolve_symbol_candidates_with_path(
    path: str,
    symbol_name: str,
    symbol_kind: str | None,
    parent_symbol: str | None,
    occurrence: int | None,
) -> tuple[Path, str, list[dict[str, Any]]]:
    return _resolve_symbol_candidates(
        path=path,
        symbol_name=symbol_name,
        symbol_kind=symbol_kind,
        parent_symbol=parent_symbol,
        occurrence=occurrence,
    )


def _resolve_symbol_candidates_without_path(
    symbol_name: str,
    symbol_kind: str | None,
    parent_symbol: str | None,
    occurrence: int | None,
) -> tuple[Path, str, list[dict[str, Any]]]:
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
    return Path(), '', candidates


def _extract_read_symbol_fields(
    target: Mapping[str, Any],
    default_path: str | None,
    default_symbol_kind: str | None,
) -> tuple[str, str, str, str | None, str | None, int | None]:
    symbol_id = str(target.get('symbol_id') or '').strip()
    path = str(target.get('path') or default_path or '').strip()
    symbol_name = str(
        target.get('qualified_name')
        or target.get('symbol_name')
        or target.get('name')
        or target.get('query')
        or ''
    ).strip()
    symbol_kind = cast(str | None, target.get('symbol_kind') or default_symbol_kind)
    parent_symbol = cast(str | None, target.get('parent_symbol'))
    occurrence = _coerce_optional_int(target.get('occurrence'), 'occurrence')
    return symbol_id, path, symbol_name, symbol_kind, parent_symbol, occurrence


def _apply_read_symbol_id_override(
    symbol_id: str,
    path: str,
    symbol_name: str,
    occurrence: int | None,
) -> tuple[str, str, int | None, int | None, int | None]:
    if symbol_id:
        path, symbol_name, requested_start, requested_end = _parse_symbol_id(symbol_id)
        occurrence = None
    else:
        requested_start = None
        requested_end = None
    return path, symbol_name, requested_start, requested_end, occurrence


def _resolve_read_symbol_lookup(
    path: str,
    symbol_name: str,
    symbol_kind: str | None,
    parent_symbol: str | None,
    occurrence: int | None,
) -> tuple[Path, str, list[dict[str, Any]]]:
    if path:
        return _resolve_symbol_candidates_with_path(
            path, symbol_name, symbol_kind, parent_symbol, occurrence,
        )
    return _resolve_symbol_candidates_without_path(
        symbol_name, symbol_kind, parent_symbol, occurrence,
    )


def _filter_candidates_by_position(
    candidates: list[dict[str, Any]],
    requested_start: int | None,
    requested_end: int | None,
) -> list[dict[str, Any]]:
    if requested_start is not None:
        return [
            c
            for c in candidates
            if c.get('start_line') == requested_start
            and c.get('end_line') == requested_end
        ]
    return candidates


def _build_read_symbol_final(
    candidates: list[dict[str, Any]],
    safe_path: Path,
    content: str,
    path: str,
    display_target: str,
    symbol_name: str,
) -> dict[str, Any]:
    if not candidates:
        return {
            'status': 'not_found',
            'target': display_target,
            'symbol_name': symbol_name,
            'message': f"Symbol '{symbol_name}' was not found.",
        }
    if len(candidates) > 1:
        return {
            'status': 'ambiguous',
            'target': display_target,
            'symbol_name': symbol_name,
            'message': f"Symbol '{symbol_name}' is ambiguous.",
            'candidates': candidates,
        }
    candidate = candidates[0]
    if not path:
        safe_path = _safe_workspace_path(str(candidate['path']), must_exist=True)
        content = _read_text_for_tool(safe_path)
    return _read_symbol_payload(
        safe_path=safe_path,
        content=content,
        candidate=candidate,
        target=display_target,
    )


def _resolve_read_symbol_target(
    target: Mapping[str, Any],
    *,
    default_path: str | None,
    default_symbol_kind: str | None,
) -> dict[str, Any]:
    symbol_id, path, symbol_name, symbol_kind, parent_symbol, occurrence = (
        _extract_read_symbol_fields(target, default_path, default_symbol_kind)
    )
    path, symbol_name, requested_start, requested_end, occurrence = (
        _apply_read_symbol_id_override(symbol_id, path, symbol_name, occurrence)
    )
    display_target = symbol_id or symbol_name
    if not symbol_name:
        return {
            'status': 'not_found',
            'target': display_target,
            'message': 'Symbol target requires qualified_name, symbol_name, or symbol_id.',
        }
    safe_path, content, candidates = _resolve_read_symbol_lookup(
        path, symbol_name, symbol_kind, parent_symbol, occurrence,
    )
    candidates = _filter_candidates_by_position(candidates, requested_start, requested_end)
    return _build_read_symbol_final(
        candidates, safe_path, content, path, display_target, symbol_name,
    )


def _str_or_empty(value: object) -> str:
    return str(value or '').strip()


def _coerce_single_symbol_entry(
    raw: object,
    index: int,
) -> Mapping[str, Any] | None:
    if isinstance(raw, str):
        if raw.strip():
            return {'qualified_name': raw.strip()}
        return None
    if isinstance(raw, Mapping):
        return raw
    raise FunctionCallValidationError(
        f'read type=symbols symbols[{index}] must be a string or object.'
    )


def _coerce_symbols_list_argument(
    raw_symbols: object,
) -> list[Mapping[str, Any]] | None:
    if not isinstance(raw_symbols, list):
        return None
    targets: list[Mapping[str, Any]] = []
    for index, raw in enumerate(raw_symbols):
        entry = _coerce_single_symbol_entry(raw, index)
        if entry is not None:
            targets.append(entry)
    return targets if targets else None


def _build_single_symbol_target_from_scalars(
    arguments: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    symbol_id = _str_or_empty(arguments.get('symbol_id'))
    qualified_name = _str_or_empty(arguments.get('qualified_name'))
    symbol_name = _str_or_empty(
        arguments.get('symbol_name') or arguments.get('query')
    )
    if symbol_id or qualified_name or symbol_name:
        return [
            {
                'symbol_id': symbol_id,
                'qualified_name': qualified_name,
                'symbol_name': symbol_name,
                'path': arguments.get('path'),
                'symbol_kind': arguments.get('symbol_kind'),
                'parent_symbol': arguments.get('parent_symbol'),
                'occurrence': arguments.get('occurrence'),
            }
        ]
    raise FunctionCallValidationError(
        'read type=symbols requires symbols[], qualified_name, symbol_id, or symbol_name.'
    )


def _coerce_read_symbol_targets(
    arguments: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    raw_symbols = arguments.get('symbols')
    result = _coerce_symbols_list_argument(raw_symbols)
    if result is not None:
        return result
    return _build_single_symbol_target_from_scalars(arguments)


def _handle_read_symbols_public(arguments: Mapping[str, Any]) -> AgentThinkAction:
    raw_path = str(arguments.get('path') or '').strip()
    symbol_kind = cast(str | None, arguments.get('symbol_kind'))
    targets = _coerce_read_symbol_targets(arguments)
    results = [
        _resolve_read_symbol_target(
            target,
            default_path=raw_path or None,
            default_symbol_kind=symbol_kind,
        )
        for target in targets
    ]
    payload = {
        'type': 'symbols',
        'status': 'ok',
        'results': results,
    }
    return AgentThinkAction(thought='[READ]\n' + json.dumps(payload, indent=2))


def _handle_find_symbols_tool(arguments: Mapping[str, Any]) -> AgentThinkAction:
    query = str(
        require_tool_argument(arguments, 'query', FIND_SYMBOLS_TOOL_NAME)
    ).strip()
    if not query:
        raise FunctionCallValidationError('find_symbols query must not be empty.')
    raw_path = str(arguments.get('path') or '').strip()
    symbol_kind = cast(str | None, arguments.get('symbol_kind'))
    include_private = parse_bool_argument(arguments.get('include_private', False))

    candidates = _find_symbol_candidates(
        query,
        path=raw_path or None,
        symbol_kind=symbol_kind,
        include_private=include_private,
    )
    payload = {
        'type': 'symbols',
        'status': 'ok',
        'query': query,
        'candidates': candidates,
    }
    return AgentThinkAction(thought='[FIND_SYMBOLS]\n' + json.dumps(payload, indent=2))


def _handle_read_tool(arguments: Mapping[str, Any]) -> Action:
    read_type = (
        str(require_tool_argument(arguments, 'type', READ_TOOL_NAME)).strip().lower()
    )
    if read_type == 'file':
        path = require_tool_argument(arguments, 'path', READ_TOOL_NAME)
        action = _build_read_file_action(str(path), {})
        return action
    if read_type == 'range':
        return _handle_read_range_public(arguments)
    if read_type == 'symbols':
        return _handle_read_symbols_public(arguments)
    raise FunctionCallValidationError(
        "read type must be one of 'file', 'range', or 'symbols'."
    )


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
        str(require_tool_argument(arguments, 'type', CREATE_TOOL_NAME)).strip().lower()
    )
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
                        'or edit_symbols for targeted symbol-level changes. '
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
        raise FunctionCallValidationError(
            f'edit_symbols edits[{index}] could not find symbol {target!r}.'
        )
    if len(candidates) > 1:
        raise FunctionCallValidationError(
            _symbol_action_ambiguity_error(symbol_name, candidates)
        )
    return candidates[0]


def _resolve_public_symbol_edit(
    *,
    item: Mapping[str, Any],
    index: int,
    default_path: str | None,
) -> dict[str, Any]:
    new_content = item.get('new_content')
    if not isinstance(new_content, str):
        raise FunctionCallValidationError(
            f'edit_symbols edits[{index}] requires new_content.'
        )

    symbol_id = str(item.get('symbol_id') or '').strip()
    raw_path = str(item.get('path') or default_path or '').strip()
    symbol_name = str(
        item.get('qualified_name') or item.get('symbol_name') or ''
    ).strip()
    symbol_kind = cast(str | None, item.get('symbol_kind'))
    parent_symbol = cast(str | None, item.get('parent_symbol'))
    occurrence = _coerce_optional_int(
        item.get('occurrence'), f'edits[{index}].occurrence'
    )
    requested_start: int | None = None
    requested_end: int | None = None

    if symbol_id:
        raw_path, symbol_name, requested_start, requested_end = _resolve_symbol_by_id(
            symbol_id
        )
        occurrence = None

    if not symbol_name:
        raise FunctionCallValidationError(
            f'edit_symbols edits[{index}] requires qualified_name, symbol_name, or symbol_id.'
        )

    safe_path, candidates = _resolve_symbol_by_name(
        symbol_name, symbol_kind, parent_symbol, occurrence, raw_path
    )

    candidate = _select_and_validate_symbol(
        candidates, symbol_id, symbol_name, requested_start, requested_end, index
    )

    if not raw_path:
        safe_path = _safe_workspace_path(str(candidate['path']), must_exist=True)

    return {
        'path': _relative_display_path(safe_path),
        'operation': 'symbol_body_replacement',
        'start_line': int(candidate['start_line']),
        'end_line': int(candidate['end_line']),
        'content': new_content,
    }


def _normalize_edit_symbols_public_edits(
    edits: object,
    *,
    default_path: str | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(edits, list) or not edits:
        raise FunctionCallValidationError(
            'edit_symbols requires a non-empty edits array.'
        )
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(edits):
        if not isinstance(item, Mapping):
            raise FunctionCallValidationError(
                f'edit_symbols edits[{index}] must be an object.'
            )
        normalized.append(
            _resolve_public_symbol_edit(
                item=item,
                index=index,
                default_path=default_path,
            )
        )

    return sorted(
        normalized,
        key=lambda item: (str(item['path']), -int(item.get('start_line', 0))),
    )


def _handle_edit_symbols_tool(arguments: Mapping[str, Any]) -> Action:
    validate_security_risk(arguments, EDIT_SYMBOLS_TOOL_NAME)
    _guard_content_arguments(dict(arguments))
    default_path = str(arguments.get('path') or '').strip() or None
    edits = _normalize_edit_symbols_public_edits(
        arguments.get('edits'),
        default_path=default_path,
    )
    action = FileEditAction(
        path='.',
        command='multi_edit',
        structured_payload={'file_edits': edits},
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


def _normalize_multiedit_edit_symbols(
    raw: Mapping[str, Any],
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
    return _normalize_edit_symbols_public_edits(
        raw_edits,
        default_path=str(path).strip() if isinstance(path, str) else None,
    )


def _dispatch_multiedit_operation(
    raw: Mapping[str, Any],
    index: int,
) -> list[dict[str, Any]]:
    command = str(raw.get('command') or '').strip().lower()
    if command == 'replace_string':
        return [_normalize_multiedit_replace_string(raw, index)]
    if command == 'edit_symbols':
        return _normalize_multiedit_edit_symbols(raw)
    raise FunctionCallValidationError(
        f'multiedit operations[{index}] command {command!r} is unsupported. '
        'Use replace_string or edit_symbols.'
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


_MAX_MULTI_EDIT_FILES = 50


def _resolve_multi_edit_path(raw_path: str, item_index: int) -> tuple[str, str]:
    """Resolve a multi_edit target to a workspace-scoped absolute path."""
    from backend.core.type_safety.path_validation import PathValidationError, SafePath
    from backend.core.workspace_resolution import require_effective_workspace_root

    try:
        workspace_root = require_effective_workspace_root()
        safe_path = SafePath.validate(
            raw_path,
            workspace_root=str(workspace_root),
            must_be_relative=True,
        )
    except (PathValidationError, ValueError) as exc:
        raise FunctionCallValidationError(
            f'multi_edit item {item_index}: invalid path {raw_path!r}: {exc}'
        ) from exc
    return str(safe_path.path), safe_path.relative_to_workspace()


def _multi_edit_raise(message: str, *, path: str | None = None) -> NoReturn:
    from backend.core.errors import ToolExecutionError

    raise ToolExecutionError(
        append_editor_recovery_guidance(
            message,
            path=path,
            tool_name='multi_edit',
        )
    )


def _multi_edit_relative_path(item_path: str, workspace_root: Path) -> str:
    return str(Path(item_path).resolve().relative_to(workspace_root.resolve()))


def _parse_multi_edit_operation(
    raw_item: Mapping[str, Any],
    idx: int,
) -> tuple[str, dict[str, Any]]:
    operation = str(raw_item.get('operation') or '').strip().lower()
    allowed = {
        'replace_string',
        'symbol_body_replacement',
    }
    if operation not in allowed:
        raise FunctionCallValidationError(
            f'multi_edit item {idx}: unsupported internal operation {operation!r}. '
            f'Allowed operations: {sorted(allowed)}.'
        )
    return operation, dict(raw_item)


def _apply_multi_edit_operation(
    *,
    rel_path: str,
    temp_path: Path,
    operation: str,
    item: dict[str, Any],
    temp_editor: Any,
) -> None:
    if operation == 'replace_string':
        old_string = item.get('old_string')
        new_string = item.get('new_string')
        if not isinstance(old_string, str) or not isinstance(new_string, str):
            raise FunctionCallValidationError(
                "multi_edit replace_string operation requires 'old_string' and 'new_string'."
            )
        result = temp_editor(
            command='replace_string',
            path=rel_path,
            old_string=old_string,
            new_str=new_string,
            replace_all=parse_bool_argument(item.get('replace_all', False)),
        )
        if result.error:
            _multi_edit_raise(
                f'❌ multi_edit replace_string failed for {rel_path}: {result.error}',
                path=rel_path,
            )
        return

    if operation == 'symbol_body_replacement':
        start_line = item.get('start_line')
        end_line = item.get('end_line')
        content = item.get('content')
        if start_line is None or end_line is None or not isinstance(content, str):
            raise FunctionCallValidationError(
                "multi_edit symbol_body_replacement operation requires 'start_line', 'end_line', and 'content'."
            )
        result = temp_editor(
            command='edit',
            path=rel_path,
            edit_mode='range',
            start_line=int(start_line),
            end_line=int(end_line),
            new_str=content,
        )
        if result.error:
            _multi_edit_raise(
                f'❌ multi_edit symbol body replacement failed for {rel_path}: {result.error}',
                path=rel_path,
            )
        return

    raise FunctionCallValidationError(
        f'multi_edit internal operation {operation!r} is unsupported.'
    )


def _validate_multi_edit_arguments(raw_edits: Any) -> None:
    if not isinstance(raw_edits, list) or not raw_edits:
        raise FunctionCallValidationError(
            "multi_edit requires a non-empty 'file_edits' array."
        )
    _guard_content_arguments({'file_edits': raw_edits})
    if len(raw_edits) > _MAX_MULTI_EDIT_FILES:
        raise FunctionCallValidationError(
            f'multi_edit supports at most {_MAX_MULTI_EDIT_FILES} files per call '
            f'(got {len(raw_edits)}). Split the batch.'
        )


def _parse_multi_edit_items(raw_edits: list) -> list[tuple[str, str, str, dict[str, Any]]]:
    parsed: list[tuple[str, str, str, dict[str, Any]]] = []
    seen_paths: set[str] = set()
    for idx, item in enumerate(raw_edits):
        if not isinstance(item, Mapping):
            raise FunctionCallValidationError(
                f'multi_edit item {idx} must be an object.'
            )
        item_path = item.get('path')
        if not isinstance(item_path, str) or not item_path.strip():
            raise FunctionCallValidationError(
                f"multi_edit item {idx} is missing required 'path'."
            )
        requested_path = item_path.strip()
        canonical_path, display_path = _resolve_multi_edit_path(requested_path, idx)
        seen_paths.add(canonical_path)
        operation, normalized_item = _parse_multi_edit_operation(item, idx)
        parsed.append((canonical_path, display_path, operation, normalized_item))
    return parsed


def _apply_multi_edit_to_temp_files(
    parsed: list[tuple[str, str, str, dict[str, Any]]],
    seen_paths: set[str],
    workspace_root: str,
    temp_root: Path,
    temp_editor: Any,
) -> tuple[dict[str, str | None], dict[str, str]]:
    original_snapshots: dict[str, str | None] = {}
    final_contents: dict[str, str] = {}
    temp_paths: dict[str, Path] = {}

    for item_path, _display_path, operation, item in parsed:
        real_path = Path(item_path)
        rel_path = _multi_edit_relative_path(item_path, workspace_root)
        temp_path = temp_root / rel_path
        if item_path not in temp_paths:
            temp_paths[item_path] = temp_path
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            if real_path.exists():
                original_snapshots[item_path] = real_path.read_text(encoding='utf-8')
                shutil.copyfile(real_path, temp_path)
            else:
                original_snapshots[item_path] = None
        _apply_multi_edit_operation(
            rel_path=rel_path,
            temp_path=temp_path,
            operation=operation,
            item=item,
            temp_editor=temp_editor,
        )

    for item_path, temp_path in temp_paths.items():
        if not temp_path.exists():
            _multi_edit_raise(
                f'❌ multi_edit produced no output file for {_multi_edit_relative_path(item_path, workspace_root)}.',
                path=_multi_edit_relative_path(item_path, workspace_root),
            )
        final_contents[item_path] = temp_path.read_text(encoding='utf-8')

    return original_snapshots, final_contents


def _verify_no_concurrent_modifications(
    original_snapshots: dict[str, str | None],
    workspace_root: str,
) -> None:
    for item_path, old_content in original_snapshots.items():
        real_path = Path(item_path)
        disk_now = (
            real_path.read_text(encoding='utf-8')
            if real_path.exists()
            else None
        )
        if disk_now != old_content:
            _multi_edit_raise(
                '❌ multi_edit aborted because the file changed on disk during batch preparation. Re-read and retry.',
                path=_multi_edit_relative_path(item_path, workspace_root),
            )


def _commit_multi_edit_transaction(
    refactor: Any,
    transaction: Any,
    final_contents: dict[str, str],
) -> Any:
    for item_path, final_content in final_contents.items():
        operation = 'modify' if Path(item_path).exists() else 'create'
        refactor.add_file_edit(transaction, item_path, final_content, operation=operation)
    return refactor.commit(transaction, validate=False)


def _format_multi_edit_success(parsed: list, result: Any) -> MessageAction:
    paths = sorted({display_path for _item_path, display_path, _operation, _item in parsed})
    if len(paths) == 1:
        file_lines = f'  • {paths[0]}'
    else:
        file_lines = '\n'.join(f'  • {p}' for p in paths)
    return MessageAction(
        content=(
            f'✓ multi_edit committed {result.files_modified} file(s) atomically\n'
            f'{file_lines}'
        )
    )


def _format_multi_edit_failure(result: Any) -> None:
    err_lines = '\n'.join(f'  - {e}' for e in (result.errors or [result.message]))
    _multi_edit_raise(
        f'❌ multi_edit transaction rolled back — no files modified.\n{err_lines}'
    )


def _handle_multi_edit_command(_path: str, arguments: Mapping[str, Any]) -> Action:
    """Apply an atomic multi-file batch edit via :class:`AtomicRefactor`.

    All edits commit together or all are rolled back from per-file backups.
    Side effects run synchronously inside this handler (same pattern as
    ``edit_symbols``); the returned ``MessageAction`` summarizes the outcome.
    """
    raw_edits = arguments.get('file_edits')
    _validate_multi_edit_arguments(raw_edits)
    parsed = _parse_multi_edit_items(raw_edits)
    seen_paths = {p for p, _, _, _ in parsed}

    try:
        from backend.core.workspace_resolution import require_effective_workspace_root
        from backend.engine.tools.atomic_refactor import AtomicRefactor
        from backend.execution.utils.file_editor import FileEditor, _file_lock_for_path
    except Exception as e:  # pragma: no cover - defensive import guard
        _multi_edit_raise(
            f'❌ multi_edit unavailable: AtomicRefactor import failed: {e}'
        )

    workspace_root = require_effective_workspace_root()
    refactor = AtomicRefactor()
    transaction = refactor.begin_transaction()
    try:
        with ExitStack() as stack:
            for item_path in sorted(seen_paths):
                stack.enter_context(_file_lock_for_path(Path(item_path)))
            with tempfile.TemporaryDirectory(prefix='grinta-multi-edit-') as temp_root_str:
                temp_root = Path(temp_root_str)
                temp_editor = FileEditor(workspace_root=str(temp_root))
                original_snapshots, final_contents = _apply_multi_edit_to_temp_files(
                    parsed, seen_paths, workspace_root, temp_root, temp_editor,
                )
            _verify_no_concurrent_modifications(original_snapshots, workspace_root)
            result = _commit_multi_edit_transaction(refactor, transaction, final_contents)
    except FunctionCallValidationError:
        raise
    except Exception as e:
        try:
            refactor.rollback(transaction)
        except Exception:
            pass
        _multi_edit_raise(f'❌ multi_edit failed before commit: {e}. No files modified.')

    if result.success:
        return _format_multi_edit_success(parsed, result)
    _format_multi_edit_failure(result)
