"""File edit handlers used by function-calling tool dispatch.

Pure code motion: split from ``backend.engine.function_calling`` to keep
that module under the 40 KB file-size cap. No logic changes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

from backend.core.enums import FileEditSource, FileReadSource
from backend.core.errors import FunctionCallValidationError
from backend.core.tools.tool_names import (
    FIND_SYMBOLS_TOOL_NAME,
    READ_TOOL_NAME,
)
from backend.engine.function_calling.helpers import (
    parse_bool_argument,
    require_tool_argument,
)
from backend.engine.tools._file_ops import (
    _coerce_optional_int,
    _filter_symbol_candidates,
    _find_symbol_candidates,
    _parse_symbol_id,
    _read_text_for_tool,
    _relative_display_path,
    _resolve_symbol_candidates,
    _safe_workspace_path,
    _sha256_text,
)
from backend.ledger.action import (
    Action,
    FileEditAction,
    FileReadAction,
    FindSymbolsAction,
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
    from backend.core.errors.structured_edit_errors import (
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
    from backend.core.errors.structured_edit_errors import (
        build_read_symbols_error_observation,
        compact_symbol_read_result,
    )

    payload = _build_read_symbols_payload(action)
    compact_results = [
        compact_symbol_read_result(result) if isinstance(result, dict) else result
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
