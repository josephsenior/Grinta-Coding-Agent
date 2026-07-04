"""File edit handlers used by function-calling tool dispatch.

Pure code motion: split from ``backend.engine.function_calling`` to keep
that module under the 40 KB file-size cap. No logic changes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from backend.core.enums import FileEditSource, FileReadSource
from backend.core.errors import FunctionCallValidationError
from backend.core.tools.tool_names import FIND_SYMBOLS_TOOL_NAME, READ_FILE_TOOL_NAME
from backend.engine.function_calling.helpers import (
    parse_bool_argument,
    require_tool_argument,
)
from backend.engine.tools._file_ops import (
    _find_symbol_candidates,
)
from backend.ledger.action import (
    Action,
    FileEditAction,
    FileReadAction,
    FindSymbolsAction,
)
from backend.ledger.observation import FindSymbolsObservation


def _build_create_file_action(path: str, arguments: Mapping[str, Any]) -> Action:
    file_text = str(arguments.get('file_text', ''))
    return FileEditAction(
        path=path,
        command='create_file',
        file_text=file_text,
        overwrite=True,
        impl_source=FileEditSource.FILE_EDITOR,
    )


def _build_read_file_action(
    path: str, _arguments: Mapping[str, Any] | None = None
) -> Action:
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
    path = require_tool_argument(arguments, 'path', READ_FILE_TOOL_NAME)
    start_line = require_tool_argument(arguments, 'start_line', READ_FILE_TOOL_NAME)
    end_line = require_tool_argument(arguments, 'end_line', READ_FILE_TOOL_NAME)
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


def execute_find_symbols(action: FindSymbolsAction) -> FindSymbolsObservation:
    candidates, scope_capped = _find_symbol_candidates(
        action.query,
        path=action.path or None,
        symbol_kind=action.symbol_kind or None,
        include_private=action.include_private,
    )
    payload: dict[str, Any] = {
        'type': 'symbols',
        'status': 'ok',
        'query': action.query,
        'candidates': candidates,
    }
    if scope_capped:
        payload['scope_truncated'] = True
        payload['note'] = (
            'Search scope capped at 200 source files — results may be incomplete. '
            'Narrow the search by specifying a path.'
        )
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
