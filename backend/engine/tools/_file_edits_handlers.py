"""File edit handlers used by function-calling tool dispatch.

Pure code motion: split from ``backend.engine.function_calling`` to keep
that module under the 40 KB file-size cap. No logic changes.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from backend.core.enums import FileEditSource
from backend.core.errors import FunctionCallValidationError
from backend.core.tools.tool_names import (
    CREATE_TOOL_NAME,
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
from backend.engine.tools._file_edits_symbols import (
    _build_create_file_action,
    _build_read_file_action,
    _handle_read_range_public,
    _handle_read_symbols_public,
    _resolve_read_type,
)
from backend.engine.tools._file_ops import (
    _guard_content_arguments,
    _relative_display_path,
    _safe_workspace_path,
)
from backend.ledger.action import (
    Action,
    AgentThinkAction,
    FileEditAction,
)


def _handle_read_tool(arguments: Mapping[str, Any]) -> Action:
    read_type = _resolve_read_type(arguments)
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


def _handle_create_tool(arguments: Mapping[str, Any]) -> Action:
    validate_security_risk(arguments, CREATE_TOOL_NAME)
    path = require_tool_argument(arguments, 'path', CREATE_TOOL_NAME)
    content = require_tool_argument(arguments, 'content', CREATE_TOOL_NAME)
    normalized_args = dict(arguments)
    normalized_args['file_text'] = str(content)
    _guard_content_arguments(normalized_args)
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
                    'Use replace_string to modify specific sections. '
                    'Only use create for genuinely new files.'
                ),
            )
    except FunctionCallValidationError:
        pass  # Path validation failed; let the action proceed and fail downstream
    normalized_args['overwrite_existing'] = True
    action = _build_create_file_action(str(path), normalized_args)
    set_security_risk(action, arguments)
    return action


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
        normalized.append(_normalize_multiedit_replace_string(raw, index))
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
