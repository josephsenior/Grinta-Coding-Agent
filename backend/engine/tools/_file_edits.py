"""File edit handlers used by function-calling tool dispatch.

Pure code motion: split into ``_file_edits_*`` submodules. No logic changes.
"""

from __future__ import annotations

from backend.engine.tools._file_edits_common import (
    _MAX_MULTI_EDIT_FILES,
    _multi_edit_raise,
)
from backend.engine.tools._file_edits_handlers import (
    _handle_create_file_tool,
    _handle_multiedit_tool,
    _handle_read_file_tool,
    _handle_replace_string_tool,
    _normalize_multiedit_operations,
    _normalize_multiedit_replace_string,
)
from backend.engine.tools._file_edits_multi import (
    _apply_multi_edit_operation,
    _apply_multi_edit_to_temp_files,
    _commit_multi_edit_transaction,
    _format_multi_edit_failure,
    _format_multi_edit_success,
    _handle_multi_edit_command,
    _multi_edit_relative_path,
    _parse_multi_edit_items,
    _parse_multi_edit_operation,
    _resolve_multi_edit_path,
    _validate_multi_edit_arguments,
    _validate_multi_edit_file_final,
    _verify_no_concurrent_modifications,
)
from backend.engine.tools._file_edits_symbols import (
    _build_create_file_action,
    _build_read_file_action,
    _handle_find_symbols_tool,
    _handle_read_range_public,
    execute_find_symbols,
)

__all__ = [
    '_MAX_MULTI_EDIT_FILES',
    '_apply_multi_edit_operation',
    '_apply_multi_edit_to_temp_files',
    '_build_create_file_action',
    '_build_read_file_action',
    '_commit_multi_edit_transaction',
    '_format_multi_edit_failure',
    '_format_multi_edit_success',
    '_handle_create_file_tool',
    '_handle_find_symbols_tool',
    '_handle_multi_edit_command',
    '_handle_multiedit_tool',
    '_handle_read_file_tool',
    '_handle_read_range_public',
    '_handle_replace_string_tool',
    '_multi_edit_raise',
    '_multi_edit_relative_path',
    '_normalize_multiedit_operations',
    '_normalize_multiedit_replace_string',
    '_parse_multi_edit_items',
    '_parse_multi_edit_operation',
    '_resolve_multi_edit_path',
    '_validate_multi_edit_arguments',
    '_validate_multi_edit_file_final',
    '_verify_no_concurrent_modifications',
    'execute_find_symbols',
]
