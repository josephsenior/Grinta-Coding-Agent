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

from backend.core.enums import FileEditSource, FileReadSource
from backend.core.errors import FunctionCallValidationError, ToolExecutionError
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
    _find_symbol_candidates_in_file,
    _guard_content_arguments,
    _parse_symbol_id,
    _read_text_for_tool,
    _relative_display_path,
    _resolve_symbol_candidates,
    _safe_workspace_path,
    _sha256_text,
    _single_symbol_candidate,
)
from backend.inference.tool_names import (
    CREATE_TOOL_NAME,
    EDIT_SYMBOL_TOOL_NAME,
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
    FindSymbolsAction,
    MessageAction,
    ReadSymbolsAction,
)
from backend.ledger.observation import FindSymbolsObservation, ReadSymbolsObservation


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
            'read type=file line range requires integer start_line and end_line.'
        ) from exc
    if start_i < 1:
        raise FunctionCallValidationError('read start_line must be >= 1.')
    if end_i != -1 and end_i < start_i:
        raise FunctionCallValidationError(
            'read end_line must be >= start_line, or -1 for EOF.'
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
            path,
            symbol_name,
            symbol_kind,
            parent_symbol,
            occurrence,
        )
    return _resolve_symbol_candidates_without_path(
        symbol_name,
        symbol_kind,
        parent_symbol,
        occurrence,
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
    from backend.execution.structured_edit_errors import (
        compact_symbol_candidates,
        symbol_ambiguity_summary,
    )

    if not candidates:
        return {
            'status': 'not_found',
            'target': display_target,
            'symbol_name': symbol_name,
            'message': (
                f"read_symbols failed: symbol '{symbol_name}' not found."
                if symbol_name
                else 'read_symbols failed: symbol not found.'
            ),
        }
    if len(candidates) > 1:
        compact = compact_symbol_candidates(candidates)
        return {
            'status': 'ambiguous',
            'target': display_target,
            'symbol_name': symbol_name,
            'message': symbol_ambiguity_summary(symbol_name, candidates).split('\n')[0],
            'hint': 'Retry with path + qualified_name + symbol_kind, or use symbol_id.',
            'candidates': compact,
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
        path,
        symbol_name,
        symbol_kind,
        parent_symbol,
        occurrence,
    )
    candidates = _filter_candidates_by_position(
        candidates, requested_start, requested_end
    )
    return _build_read_symbol_final(
        candidates,
        safe_path,
        content,
        path,
        display_target,
        symbol_name,
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


def _coerce_read_symbol_targets(
    arguments: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    raw_symbols = arguments.get('symbols')
    result = _coerce_symbols_list_argument(raw_symbols)
    if result is not None:
        return result
    raise FunctionCallValidationError(
        'read type=symbols requires a non-empty symbols[] array.'
    )


def _build_read_symbols_payload(action: ReadSymbolsAction) -> dict[str, Any]:
    raw_path = action.path.strip()
    symbol_kind = action.symbol_kind or None
    results = [
        _resolve_read_symbol_target(
            target,
            default_path=raw_path or None,
            default_symbol_kind=symbol_kind,
        )
        for target in action.targets
    ]
    return {
        'type': 'symbols',
        'status': 'ok',
        'results': results,
    }


_SYMBOL_READ_SUCCESS_STATUSES = frozenset({'ok', 'resolved'})


def _build_read_symbols_tool_result(results: list[dict[str, Any]]) -> dict[str, Any]:
    failed = [
        result
        for result in results
        if isinstance(result, dict)
        and result.get('status') not in _SYMBOL_READ_SUCCESS_STATUSES
    ]
    if not failed:
        return {
            'tool': 'read_symbols',
            'ok': True,
            'count': len(results),
        }
    first = failed[0]
    status = str(first.get('status') or 'error')
    code_map = {
        'not_found': 'SYMBOL_NOT_FOUND',
        'ambiguous': 'SYMBOL_AMBIGUOUS',
    }
    tool_result: dict[str, Any] = {
        'tool': 'read_symbols',
        'ok': False,
        'error_code': code_map.get(status, 'SYMBOL_LOOKUP_FAILED'),
        'retryable': True,
        'symbol': first.get('symbol_name') or first.get('target'),
        'failed_count': len(failed),
    }
    if first.get('hint'):
        tool_result['hint'] = first['hint']
    if first.get('candidates'):
        tool_result['candidates'] = first['candidates']
    return tool_result


def execute_read_symbols(action: ReadSymbolsAction) -> Any:
    from backend.execution.structured_edit_errors import (
        build_read_symbols_error_observation,
        compact_symbol_read_result,
    )

    payload = _build_read_symbols_payload(action)
    compact_results = [
        compact_symbol_read_result(result)
        if isinstance(result, dict)
        else result
        for result in payload['results']
    ]
    failed = [
        result
        for result in compact_results
        if isinstance(result, dict)
        and result.get('status') not in _SYMBOL_READ_SUCCESS_STATUSES
    ]
    if failed:
        return build_read_symbols_error_observation(
            failed,
            total=len(compact_results),
        )

    payload = {**payload, 'results': compact_results}
    observation = ReadSymbolsObservation(
        content=json.dumps(payload, indent=2),
        path=action.path,
        symbol_kind=action.symbol_kind,
        results=compact_results,
    )
    observation.tool_result = _build_read_symbols_tool_result(compact_results)
    return observation


def _handle_read_symbols_public(arguments: Mapping[str, Any]) -> ReadSymbolsAction:
    raw_path = str(arguments.get('path') or '').strip()
    symbol_kind = cast(str | None, arguments.get('symbol_kind'))
    targets = _coerce_read_symbol_targets(arguments)
    return ReadSymbolsAction(
        targets=[dict(target) for target in targets],
        path=raw_path,
        symbol_kind=symbol_kind or '',
    )


def execute_find_symbols(action: FindSymbolsAction) -> FindSymbolsObservation:
    candidates = _find_symbol_candidates(
        action.query,
        path=action.path or None,
        symbol_kind=action.symbol_kind or None,
        include_private=action.include_private,
    )
    payload = {
        'type': 'symbols',
        'status': 'ok',
        'query': action.query,
        'candidates': candidates,
    }
    observation = FindSymbolsObservation(
        content=json.dumps(payload, indent=2),
        query=action.query,
        path=action.path,
        symbol_kind=action.symbol_kind,
        include_private=action.include_private,
        candidates=candidates,
    )
    observation.tool_result = {
        'tool': 'find_symbols',
        'ok': True,
        'query': action.query,
        'path': action.path,
        'count': len(candidates),
    }
    return observation


def _handle_find_symbols_tool(arguments: Mapping[str, Any]) -> FindSymbolsAction:
    query = str(
        require_tool_argument(arguments, 'query', FIND_SYMBOLS_TOOL_NAME)
    ).strip()
    if not query:
        raise FunctionCallValidationError('find_symbols query must not be empty.')
    raw_path = str(arguments.get('path') or '').strip()
    symbol_kind = cast(str | None, arguments.get('symbol_kind'))
    include_private = parse_bool_argument(arguments.get('include_private', False))
    return FindSymbolsAction(
        query=query,
        path=raw_path,
        symbol_kind=symbol_kind or '',
        include_private=include_private,
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
        from backend.execution.structured_edit_errors import symbol_ambiguity_summary

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


def _multi_edit_raise(
    summary: str,
    *,
    error_code: str,
    path: str | None = None,
    operation: str | None = None,
    failed_op_index: int | None = None,
    total_ops: int | None = None,
    retryable: bool = True,
    detail: str | None = None,
    line: int | None = None,
    symbol: str | None = None,
    candidates: list[dict[str, Any]] | None = None,
    match_count: int | None = None,
    transaction_rolled_back: bool = False,
    hint: str | None = None,
) -> NoReturn:
    from backend.execution.structured_edit_errors import multi_edit_raise

    multi_edit_raise(
        summary,
        error_code=error_code,
        path=path,
        operation=operation,
        failed_op_index=failed_op_index,
        total_ops=total_ops,
        retryable=retryable,
        detail=detail,
        line=line,
        symbol=symbol,
        candidates=candidates,
        match_count=match_count,
        transaction_rolled_back=transaction_rolled_back,
        hint=hint,
    )


def _multi_edit_relative_path(item_path: str, workspace_root: str | Path) -> str:
    root = Path(workspace_root)
    return str(Path(item_path).resolve().relative_to(root.resolve()))


def _parse_multi_edit_operation(
    raw_item: Mapping[str, Any],
    idx: int,
) -> tuple[str, dict[str, Any]]:
    operation = str(raw_item.get('operation') or '').strip().lower()
    if operation == 'edit_symbol_deferred':
        path = raw_item.get('path')
        edits = raw_item.get('edits')
        if not isinstance(path, str) or not path.strip():
            raise FunctionCallValidationError(
                f'multi_edit item {idx} edit_symbol_deferred is missing path.'
            )
        if not isinstance(edits, list) or not edits:
            raise FunctionCallValidationError(
                f'multi_edit item {idx} edit_symbol_deferred requires edits.'
            )
        return operation, dict(raw_item)
    allowed = {
        'replace_string',
        'symbol_body_replacement',
    }
    if operation not in allowed:
        raise FunctionCallValidationError(
            f'multi_edit item {idx}: unsupported internal operation {operation!r}. '
            f'Allowed operations: {sorted(allowed | {"edit_symbol_deferred"})}.'
        )
    return operation, dict(raw_item)


def _resolve_symbol_edit_on_temp_file(
    temp_path: Path,
    display_path: str,
    item: Mapping[str, Any],
    index: int,
) -> dict[str, Any]:
    """Resolve one edit_symbol target against the current temp-file contents."""
    new_content = item.get('new_content')
    if not isinstance(new_content, str):
        raise FunctionCallValidationError(
            f'multiedit edit_symbol edits[{index}] requires new_content.'
        )

    symbol_id = str(item.get('symbol_id') or '').strip()
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
        _raw_path, symbol_name, requested_start, requested_end = _resolve_symbol_by_id(
            symbol_id
        )
        occurrence = None

    if not symbol_name:
        raise FunctionCallValidationError(
            f'multiedit edit_symbol edits[{index}] requires qualified_name, '
            'symbol_name, or symbol_id.'
        )

    lookup_name = symbol_name.rsplit('.', 1)[-1]
    if not parent_symbol and '.' in symbol_name:
        maybe_parent, _, maybe_name = symbol_name.rpartition('.')
        parent_symbol = maybe_parent or None
        lookup_name = maybe_name

    candidates = _find_symbol_candidates_in_file(
        temp_path,
        lookup_name,
        symbol_kind=symbol_kind,
        include_private=True,
    )
    candidates = _filter_symbol_candidates(
        candidates,
        symbol_name=lookup_name,
        parent_symbol=parent_symbol,
        occurrence=occurrence,
    )
    if requested_start is not None:
        candidates = [
            c
            for c in candidates
            if c.get('start_line') == requested_start
            and c.get('end_line') == requested_end
        ]

    candidate = _select_and_validate_symbol(
        candidates,
        symbol_id,
        symbol_name,
        requested_start,
        requested_end,
        index,
        path=display_path,
    )
    return {
        'path': display_path,
        'operation': 'symbol_body_replacement',
        'start_line': int(candidate['start_line']),
        'end_line': int(candidate['end_line']),
        'content': new_content,
    }


def _resolve_deferred_edit_symbol(
    temp_path: Path,
    display_path: str,
    edits: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    resolved = [
        _resolve_symbol_edit_on_temp_file(temp_path, display_path, item, index)
        for index, item in enumerate(edits)
    ]
    return sorted(resolved, key=lambda item: -int(item.get('start_line', 0)))


def _validate_symbol_range_on_temp(
    temp_path: Path,
    start_line: int,
    end_line: int,
    rel_path: str,
    *,
    failed_op_index: int | None = None,
    total_ops: int | None = None,
) -> None:
    """Reject stale line ranges after prior batch edits on the temp copy."""
    if not temp_path.exists():
        _multi_edit_raise(
            'edit_symbol failed: file not found.',
            error_code='FILE_NOT_FOUND',
            path=rel_path,
            operation='edit_symbol',
            failed_op_index=failed_op_index,
            total_ops=total_ops,
            retryable=False,
        )
    line_count = len(temp_path.read_text(encoding='utf-8').splitlines())
    if start_line < 1 or end_line < start_line or end_line > line_count:
        _multi_edit_raise(
            'edit_symbol failed: symbol line range is invalid after prior batch edits.',
            error_code='INVALID_SYMBOL_RANGE',
            path=rel_path,
            operation='edit_symbol',
            failed_op_index=failed_op_index,
            total_ops=total_ops,
            detail=(
                f'range {start_line}-{end_line} invalid for {line_count} lines; '
                'use edit_symbol instead of line ranges when combining edits.'
            ),
            retryable=True,
        )


def _validate_multi_edit_file_final(
    temp_editor: Any,
    temp_path: Path,
    rel_path: str,
    original_content: str | None,
    *,
    failed_op_index: int | None = None,
    total_ops: int | None = None,
) -> None:
    from backend.execution.structured_edit_errors import (
        compact_syntax_detail,
        extract_syntax_line,
    )

    if not temp_path.exists():
        return
    final_content = temp_path.read_text(encoding='utf-8')
    if final_content == (original_content or ''):
        return

    regression_error = temp_editor._detect_introduced_syntax_error(
        temp_path, original_content, final_content
    )
    if regression_error is not None:
        _multi_edit_raise(
            'multi_edit failed: introduced syntax error.',
            error_code='INTRODUCED_SYNTAX_ERROR',
            path=rel_path,
            operation='multi_edit',
            failed_op_index=failed_op_index,
            total_ops=total_ops,
            line=extract_syntax_line(regression_error),
            detail=compact_syntax_detail(regression_error),
            retryable=True,
        )

    is_valid, msg = temp_editor._maybe_validate_syntax_for_file(
        temp_path, final_content
    )
    if not is_valid:
        _multi_edit_raise(
            'multi_edit failed: syntax validation failed.',
            error_code='SYNTAX_VALIDATION_FAILED',
            path=rel_path,
            operation='multi_edit',
            failed_op_index=failed_op_index,
            total_ops=total_ops,
            line=extract_syntax_line(str(msg or '')),
            detail=compact_syntax_detail(str(msg or '')),
            retryable=True,
        )


def _apply_multi_edit_operation(
    *,
    rel_path: str,
    temp_path: Path,
    operation: str,
    item: dict[str, Any],
    temp_editor: Any,
    failed_op_index: int | None = None,
    total_ops: int | None = None,
) -> None:
    from backend.execution.structured_edit_errors import summarize_editor_error

    if operation == 'edit_symbol_deferred':
        edits = item.get('edits')
        if not isinstance(edits, list) or not edits:
            raise FunctionCallValidationError(
                'multi_edit edit_symbol_deferred requires a non-empty edits array.'
            )
        if not temp_path.exists():
            _multi_edit_raise(
                'edit_symbol failed: file not found.',
                error_code='FILE_NOT_FOUND',
                path=rel_path,
                operation='edit_symbol',
                failed_op_index=failed_op_index,
                total_ops=total_ops,
                retryable=False,
            )
        resolved_ops = _resolve_deferred_edit_symbol(temp_path, rel_path, edits)
        for resolved in resolved_ops:
            _apply_multi_edit_operation(
                rel_path=rel_path,
                temp_path=temp_path,
                operation='symbol_body_replacement',
                item=resolved,
                temp_editor=temp_editor,
                failed_op_index=failed_op_index,
                total_ops=total_ops,
            )
        return

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
            error_code, summary, retryable, extra = summarize_editor_error(result)
            _multi_edit_raise(
                summary,
                error_code=error_code,
                path=rel_path,
                operation='replace_string',
                failed_op_index=failed_op_index,
                total_ops=total_ops,
                retryable=retryable,
                detail=extra.get('detail'),
                line=extra.get('line'),
                match_count=extra.get('match_count'),
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
        start = int(start_line)
        end = int(end_line)
        _validate_symbol_range_on_temp(
            temp_path,
            start,
            end,
            rel_path,
            failed_op_index=failed_op_index,
            total_ops=total_ops,
        )
        result = temp_editor(
            command='edit',
            path=rel_path,
            edit_mode='range',
            start_line=start,
            end_line=end,
            new_str=content,
        )
        if result.error:
            error_code, summary, retryable, extra = summarize_editor_error(result)
            _multi_edit_raise(
                summary,
                error_code=error_code,
                path=rel_path,
                operation='edit_symbol',
                failed_op_index=failed_op_index,
                total_ops=total_ops,
                retryable=retryable,
                detail=extra.get('detail'),
                line=extra.get('line'),
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


def _parse_multi_edit_items(
    raw_edits: list,
) -> list[tuple[str, str, str, dict[str, Any]]]:
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
                f"multiedit validation failed: item {idx} missing required field 'path'."
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
    workspace_root: str | Path,
    temp_root: Path,
    temp_editor: Any,
) -> tuple[dict[str, str | None], dict[str, str]]:
    """Apply multi_edit operations in declaration order against per-file temp copies.

    Each operation sees the temp file as left by all prior operations in the batch.
    ``edit_symbol`` targets are resolved at apply time (identity-based). Syntax is validated once per file after all operations complete.
    """
    original_snapshots: dict[str, str | None] = {}
    final_contents: dict[str, str] = {}
    temp_paths: dict[str, Path] = {}

    for op_index, (item_path, _display_path, operation, item) in enumerate(parsed):
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
            failed_op_index=op_index,
            total_ops=len(parsed),
        )

    for item_path, temp_path in temp_paths.items():
        rel_path = _multi_edit_relative_path(item_path, workspace_root)
        if not temp_path.exists():
            _multi_edit_raise(
                'multi_edit failed: produced no output file.',
                error_code='NO_OUTPUT_FILE',
                path=rel_path,
                operation='multi_edit',
                retryable=True,
            )
        _validate_multi_edit_file_final(
            temp_editor,
            temp_path,
            rel_path,
            original_snapshots.get(item_path),
            failed_op_index=len(parsed) - 1 if parsed else None,
            total_ops=len(parsed) or None,
        )
        final_contents[item_path] = temp_path.read_text(encoding='utf-8')

    return original_snapshots, final_contents


def _verify_no_concurrent_modifications(
    original_snapshots: dict[str, str | None],
    workspace_root: str | Path,
) -> None:
    for item_path, old_content in original_snapshots.items():
        real_path = Path(item_path)
        disk_now = real_path.read_text(encoding='utf-8') if real_path.exists() else None
        if disk_now != old_content:
            _multi_edit_raise(
                'multi_edit aborted: file changed on disk during batch preparation.',
                error_code='CONCURRENT_MODIFICATION',
                path=_multi_edit_relative_path(item_path, workspace_root),
                operation='multi_edit',
                detail='Re-read the file and retry.',
                retryable=True,
            )


def _commit_multi_edit_transaction(
    refactor: Any,
    transaction: Any,
    final_contents: dict[str, str],
) -> Any:
    for item_path, final_content in final_contents.items():
        operation = 'modify' if Path(item_path).exists() else 'create'
        refactor.add_file_edit(
            transaction, item_path, final_content, operation=operation
        )
    return refactor.commit(transaction, validate=False)


def _format_multi_edit_success(parsed: list, result: Any) -> MessageAction:
    paths = sorted(
        {display_path for _item_path, display_path, _operation, _item in parsed}
    )
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
    errors = list(result.errors or [result.message])
    primary = str(errors[0] if errors else 'transaction failed')
    _multi_edit_raise(
        'multi_edit transaction rolled back.',
        error_code='TRANSACTION_ROLLBACK',
        operation='multi_edit',
        detail=primary,
        transaction_rolled_back=True,
        retryable=True,
    )


def _handle_multi_edit_command(_path: str, arguments: Mapping[str, Any]) -> Action:
    """Apply an atomic multi-file batch edit via :class:`AtomicRefactor`.

    All edits commit together or all are rolled back from per-file backups.
    Side effects run synchronously inside this handler (same pattern as
    ``edit_symbol``); the returned ``MessageAction`` summarizes the outcome.
    """
    raw_edits = arguments.get('file_edits')
    _validate_multi_edit_arguments(raw_edits)
    assert isinstance(raw_edits, list)
    parsed = _parse_multi_edit_items(raw_edits)
    seen_paths = {p for p, _, _, _ in parsed}

    try:
        from backend.core.workspace_resolution import require_effective_workspace_root
        from backend.engine.tools.atomic_refactor import AtomicRefactor
        from backend.execution.utils.file_editor import FileEditor, _file_lock_for_path
    except Exception as e:  # pragma: no cover - defensive import guard
        _multi_edit_raise(
            'multi_edit unavailable: AtomicRefactor import failed.',
            error_code='MULTI_EDIT_UNAVAILABLE',
            operation='multi_edit',
            detail=str(e),
            retryable=False,
        )

    workspace_root = require_effective_workspace_root()
    refactor = AtomicRefactor()
    transaction = refactor.begin_transaction()
    try:
        with ExitStack() as stack:
            for item_path in sorted(seen_paths):
                stack.enter_context(_file_lock_for_path(Path(item_path)))
            with tempfile.TemporaryDirectory(
                prefix='grinta-multi-edit-'
            ) as temp_root_str:
                temp_root = Path(temp_root_str)
                temp_editor = FileEditor(workspace_root=str(temp_root))
                temp_editor._defer_syntax_validation = True
                original_snapshots, final_contents = _apply_multi_edit_to_temp_files(
                    parsed,
                    seen_paths,
                    workspace_root,
                    temp_root,
                    temp_editor,
                )
            _verify_no_concurrent_modifications(original_snapshots, workspace_root)
            result = _commit_multi_edit_transaction(
                refactor, transaction, final_contents
            )
    except FunctionCallValidationError:
        raise
    except ToolExecutionError:
        raise
    except Exception as e:
        try:
            refactor.rollback(transaction)
        except Exception:
            pass
        _multi_edit_raise(
            'multi_edit failed before commit.',
            error_code='MULTI_EDIT_COMMIT_FAILED',
            operation='multi_edit',
            detail=str(e),
            transaction_rolled_back=True,
            retryable=True,
        )

    if result.success:
        return _format_multi_edit_success(parsed, result)
    _format_multi_edit_failure(result)
    raise AssertionError('unreachable: _format_multi_edit_failure always raises')
