"""This file contains the function calling implementation for different actions.

This is similar to the functionality of `OrchestratorResponseParser`.

Split into sibling modules to keep this file under the 40 KB cap:
  - backend.engine.tools._file_ops       (read helpers + symbol search)
  - backend.engine.tools._file_edits     (file edit handlers)
  - backend.engine.tools._tool_handlers  (browser/finish/memory/search/etc.)
Pure code motion: no logic changes. The flat re-export shim at the bottom
preserves back-compat with callers using ``from backend.engine.function_calling
import ...``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

import backend.engine.tools.analyze_project_structure as analyze_project_structure_tools
import backend.engine.tools.blackboard as blackboard_tools
import backend.engine.tools.checkpoint as checkpoint_tools
import backend.engine.tools.debugger as debugger_tools
import backend.engine.tools.delegate_task as delegate_task_tools
import backend.engine.tools.lsp_query as lsp_query_tools
import backend.engine.tools.terminal_manager as terminal_manager_tools
from backend.core.constants import NOTE_TOOL_NAME, RECALL_TOOL_NAME
from backend.core.errors import FunctionCallNotExistsError, FunctionCallValidationError
from backend.core.interaction_modes import (
    CHAT_MODE_ALLOWED_TOOLS,
    PLAN_MODE,
    PLAN_MODE_ALLOWED_TOOLS,
    is_chat_mode,
    normalize_interaction_mode,
)
from backend.core.logger import app_logger as logger
from backend.engine.common import common_response_to_actions
from backend.engine.function_calling_helpers import combine_thought
from backend.engine.tools import (
    create_cmd_run_tool,
    create_create_tool,
    create_edit_symbols_tool,
    create_find_symbols_tool,
    create_finish_tool,
    create_multiedit_tool,
    create_read_tool,
    create_replace_string_tool,
    create_summarize_context_tool,
)
from backend.engine.tools.analyze_project_structure import (
    ANALYZE_PROJECT_STRUCTURE_TOOL_NAME,
)
from backend.engine.tools.blackboard import BLACKBOARD_TOOL_NAME
from backend.engine.tools.browser_native import BROWSER_TOOL_NAME
from backend.engine.tools.checkpoint import CHECKPOINT_TOOL_NAME
from backend.engine.tools.debugger import DEBUGGER_TOOL_NAME
from backend.engine.tools.delegate_task import DELEGATE_TASK_TOOL_NAME
from backend.engine.tools.execute_mcp_tool import EXECUTE_MCP_TOOL_TOOL_NAME
from backend.engine.tools.lsp_query import CODE_INTELLIGENCE_TOOL_NAME
from backend.engine.tools.memory_manager import MEMORY_MANAGER_TOOL_NAME
from backend.engine.tools.meta_cognition import COMMUNICATE_TOOL_NAME
from backend.engine.tools.note import build_note_action, build_recall_action
from backend.engine.tools.search_code import SEARCH_CODE_TOOL_NAME
from backend.engine.tools.terminal_manager import TERMINAL_MANAGER_TOOL_NAME
from backend.inference.tool_names import (
    TASK_TRACKER_TOOL_NAME,
    UNDO_LAST_EDIT_TOOL_NAME,
)
from backend.ledger.action import Action, AgentThinkAction

if TYPE_CHECKING:
    ModelResponse = Any

ToolHandler = Callable[[dict[str, Any]], Action]
AgentThinkToolHandler = Callable[[dict[str, Any]], AgentThinkAction]

build_analyze_project_structure_action = cast(
    AgentThinkToolHandler,
    cast(Any, analyze_project_structure_tools).build_analyze_project_structure_action,
)
build_blackboard_action = cast(
    ToolHandler, cast(Any, blackboard_tools).build_blackboard_action
)
build_checkpoint_action = cast(
    AgentThinkToolHandler, cast(Any, checkpoint_tools).build_checkpoint_action
)
build_delegate_task_action = cast(
    ToolHandler, cast(Any, delegate_task_tools).build_delegate_task_action
)
build_lsp_query_action = cast(
    ToolHandler, cast(Any, lsp_query_tools).build_lsp_query_action
)
handle_terminal_manager_tool = cast(
    ToolHandler, cast(Any, terminal_manager_tools).handle_terminal_manager_tool
)
handle_debugger_tool = cast(ToolHandler, cast(Any, debugger_tools).handle_debugger_tool)


def _create_tool_dispatch_map() -> dict[str, ToolHandler]:
    """Create dispatch map for tool handlers."""
    return {
        cast(
            str, create_cmd_run_tool().get('function', {}).get('name', '')
        ): _handle_cmd_run_tool,
        cast(
            str, create_finish_tool().get('function', {}).get('name', '')
        ): _handle_finish_tool,
        cast(
            str, create_read_tool().get('function', {}).get('name', '')
        ): _handle_read_tool,
        cast(
            str, create_find_symbols_tool().get('function', {}).get('name', '')
        ): _handle_find_symbols_tool,
        cast(
            str, create_create_tool().get('function', {}).get('name', '')
        ): _handle_create_tool,
        cast(
            str, create_replace_string_tool().get('function', {}).get('name', '')
        ): _handle_replace_string_tool,
        cast(
            str, create_edit_symbols_tool().get('function', {}).get('name', '')
        ): _handle_edit_symbols_tool,
        cast(
            str, create_multiedit_tool().get('function', {}).get('name', '')
        ): _handle_multiedit_tool,
        cast(
            str, create_summarize_context_tool().get('function', {}).get('name', '')
        ): _handle_summarize_context_tool,
        TASK_TRACKER_TOOL_NAME: _handle_task_tracker_tool,
        MEMORY_MANAGER_TOOL_NAME: _handle_memory_manager_tool,
        NOTE_TOOL_NAME: lambda args: build_note_action(
            cast(str, args['key']), cast(str, args['value'])
        ),
        RECALL_TOOL_NAME: lambda args: build_recall_action(cast(str, args['key'])),
        SEARCH_CODE_TOOL_NAME: _handle_search_code_tool,
        ANALYZE_PROJECT_STRUCTURE_TOOL_NAME: _handle_analyze_project_structure_tool,
        DELEGATE_TASK_TOOL_NAME: lambda args: build_delegate_task_action(dict(args)),
        CODE_INTELLIGENCE_TOOL_NAME: lambda args: build_lsp_query_action(dict(args)),
        DEBUGGER_TOOL_NAME: lambda args: handle_debugger_tool(dict(args)),
        BLACKBOARD_TOOL_NAME: lambda args: build_blackboard_action(dict(args)),
        TERMINAL_MANAGER_TOOL_NAME: lambda args: handle_terminal_manager_tool(
            dict(args)
        ),
        COMMUNICATE_TOOL_NAME: _handle_communicate_tool,
        EXECUTE_MCP_TOOL_TOOL_NAME: _handle_execute_mcp_tool_tool,
        CHECKPOINT_TOOL_NAME: _handle_checkpoint_tool,
        UNDO_LAST_EDIT_TOOL_NAME: _handle_undo_last_edit_tool,
        BROWSER_TOOL_NAME: _handle_browser_tool,
    }


def response_to_actions(
    response: ModelResponse,
    mcp_tool_names: list[str] | None = None,
    mcp_tools: dict[str, Any] | None = None,
    mode: str = 'agent',
) -> list[Action]:
    """Convert LLM response to agent actions.

    Normal tools use provider-native tool calls.
    """
    from backend.engine.planner import CODE_PAYLOAD_TOOLS

    def process_with_mcp_tools(tc: Any, args: dict[str, Any]) -> Action:
        return _process_single_tool_call(tc, args, mode=mode)

    return common_response_to_actions(
        response=response,
        create_action_fn=process_with_mcp_tools,
        combine_thought_fn=combine_thought,
        mcp_tool_names=mcp_tool_names,
        xml_tool_names=CODE_PAYLOAD_TOOLS,
    )


# Lazily-initialized dispatch map — built once per process to avoid
# re-creating tool definition dicts on every tool call.
_tool_dispatch_map: dict[str, ToolHandler] | None = None


def _get_tool_dispatch_map() -> dict[str, ToolHandler]:
    global _tool_dispatch_map
    if _tool_dispatch_map is None:
        _tool_dispatch_map = _create_tool_dispatch_map()
    return _tool_dispatch_map


def _process_single_tool_call(
    tool_call: Any,
    arguments: dict[str, Any],
    *,
    mode: str = 'agent',
) -> Action:
    """Process a single tool call and return the corresponding action."""
    logger.debug('Tool call in function_calling.py: %s', tool_call)
    tool_dispatch = _get_tool_dispatch_map()

    tool_name = cast(str, tool_call.function.name)
    normalized_mode = normalize_interaction_mode(mode)
    mcp_tool_names = cast(list[str] | None, getattr(tool_call, '_mcp_tool_names', None))
    if is_chat_mode(normalized_mode):
        if tool_name not in CHAT_MODE_ALLOWED_TOOLS or (
            mcp_tool_names and tool_name in mcp_tool_names
        ):
            raise FunctionCallValidationError(
                f'Tool `{tool_name}` is not available in Chat Mode. '
                'Chat Mode is read-only; use plain text or inspection tools only.'
            )
    if normalized_mode == PLAN_MODE and tool_name not in PLAN_MODE_ALLOWED_TOOLS:
        raise FunctionCallValidationError(
            f'Tool `{tool_name}` is not available in Plan Mode. '
            'Plan Mode is read-only; use inspection tools, communicate_with_user, or finish.'
        )
    if tool_name == 'file_editor':
        raise FunctionCallValidationError(
            'The legacy file_editor tool has been removed. Use read, create, '
            'replace_string, edit_symbols, or multiedit.'
        )
    if '__xml_syntax_error__' in arguments:
        from backend.engine.common import _check_format_error_retry_guard

        serialized_args = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
        error_sig = f'xml_syntax_error:{arguments["__xml_syntax_error__"]}'
        allowed, reason = _check_format_error_retry_guard(
            tool_name, serialized_args, error_sig
        )
        if not allowed:
            logger.error(
                'FORMAT_ERROR retry guard in _process_single_tool_call: %s', reason
            )
            raise FunctionCallValidationError(
                f'[FORMAT_ERROR] Retry guard stopped repeated FORMAT_ERROR for '
                f'tool `{tool_name}` after multiple attempts.\n'
                f'{reason}\n'
                f'[SYSTEM_ACTION] Report this as a system/tool error.'
            )
        raise FunctionCallValidationError(
            f'Malformed XML tool call for {tool_name}: '
            f'{arguments["__xml_syntax_error__"]}'
        )
    if tool_name == _finish_tool_name(normalized_mode):
        return _handle_finish_tool(arguments, mode=normalized_mode)
    if tool_name in tool_dispatch:
        return tool_dispatch[tool_name](arguments)
    if mcp_tool_names and tool_name in mcp_tool_names:
        return _handle_mcp_tool(tool_name, arguments)
    msg = f'Tool {tool_name} is not registered. (arguments: {arguments}). Please check the tool name and retry with an existing tool.'
    raise FunctionCallNotExistsError(
        msg,
    )


# ---------------------------------------------------------------------------
# Flat re-export shim for back-compat
# ---------------------------------------------------------------------------
# Symbols previously defined in this module have been moved to:
#   - backend.engine.tools._file_ops       (read helpers + symbol search)
#   - backend.engine.tools._file_edits     (read/create/replace/edit_symbols/multiedit)
#   - backend.engine.tools._tool_handlers  (browser/finish/memory/search/task-tracker/mcp/...)
# Kept as flat re-exports for in-repo callers. Will be removed once
# downstream callers migrate to the new paths.
from backend.engine.function_calling_helpers import (  # noqa: E402, F401
    parse_bool_argument,
    require_tool_argument,
    set_security_risk,
    validate_security_risk,
)
from backend.engine.tools._file_edits import (  # noqa: E402, F401
    _MAX_MULTI_EDIT_FILES,
    _apply_multi_edit_operation,
    _build_create_file_action,
    _build_read_file_action,
    _build_symbol_insert_action,
    _coerce_insert_position,
    _coerce_read_symbol_targets,
    _handle_create_symbol_public,
    _handle_create_tool,
    _handle_edit_symbols_tool,
    _handle_find_symbols_tool,
    _handle_multi_edit_command,
    _handle_multiedit_tool,
    _handle_read_range_public,
    _handle_read_symbols_public,
    _handle_read_tool,
    _handle_replace_string_tool,
    _insert_line_for_symbol,
    _multi_edit_raise,
    _multi_edit_relative_path,
    _normalize_edit_symbols_public_edits,
    _normalize_multiedit_operations,
    _parse_multi_edit_operation,
    _read_symbol_payload,
    _resolve_multi_edit_path,
    _resolve_public_symbol_edit,
    _resolve_read_symbol_target,
)
from backend.engine.tools._file_ops import (  # noqa: E402, F401
    _SKIP_SYMBOL_SEARCH_PARTS,
    _SOURCE_SYMBOL_SUFFIXES,
    _candidate_from_location,
    _candidate_paths_for_symbol_search,
    _coerce_optional_int,
    _filter_symbol_candidates,
    _find_symbol_candidates,
    _find_symbol_candidates_in_file,
    _guard_content_arguments,
    _node_kind,
    _parse_symbol_id,
    _read_text_for_tool,
    _relative_display_path,
    _resolve_symbol_candidates,
    _safe_workspace_path,
    _sha256_text,
    _single_symbol_candidate,
    _symbol_action_ambiguity_error,
    _symbol_id,
    _symbol_preview,
    _workspace_root,
)
from backend.engine.tools._tool_handlers import (  # noqa: E402, F401  # noqa: E402, F401
    _FINISH_STATUSES,
    _apply_context7_resolve_library_defaults,
    _finish_tool_name,
    _handle_agent_finish_tool,
    _handle_analyze_project_structure_tool,
    _handle_browser_tool,
    _handle_checkpoint_tool,
    _handle_cmd_run_tool,
    _handle_communicate_tool,
    _handle_execute_mcp_tool_tool,
    _handle_finish_tool,
    _handle_mcp_tool,
    _handle_memory_manager_tool,
    _handle_plan_finish_tool,
    _handle_search_code_tool,
    _handle_summarize_context_tool,
    _handle_task_tracker_tool,
    _handle_undo_last_edit_tool,
    _maybe_noop_task_tracker_action,
    _merge_mcp_gateway_inner_arguments,
    _normalize_task_tracker_list,
    _normalize_task_tracker_step,
    _require_finish_dict,
    _require_finish_list,
    _require_finish_status,
    _require_finish_string,
    _semantic_recall_registry,
    _task_tracker_existing_normalized,
    get_semantic_recall_fn,
    register_semantic_recall,
)
