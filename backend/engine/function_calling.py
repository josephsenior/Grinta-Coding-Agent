"""This file contains the function calling implementation for different actions.

This is similar to the functionality of `OrchestratorResponseParser`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, cast

import backend.engine.tools.analyze_project_structure as analyze_project_structure_tools
import backend.engine.tools.blackboard as blackboard_tools
import backend.engine.tools.checkpoint as checkpoint_tools
import backend.engine.tools.debugger as debugger_tools
import backend.engine.tools.delegate_task as delegate_task_tools
import backend.engine.tools.explore_code as explore_code_tools
import backend.engine.tools.lsp_query as lsp_query_tools
import backend.engine.tools.terminal_manager as terminal_manager_tools
from backend.core.constants import NOTE_TOOL_NAME, RECALL_TOOL_NAME
from backend.core.enums import FileEditSource, FileReadSource
from backend.core.errors import (
    FunctionCallNotExistsError,
    FunctionCallValidationError,
)
from backend.core.logger import app_logger as logger
from backend.engine.common import (
    common_response_to_actions,
)
from backend.engine.tools import (
    create_cmd_run_tool,
    create_finish_tool,
    create_summarize_context_tool,
    create_symbol_editor_tool,
    create_text_editor_tool,
    create_think_tool,
)
from backend.engine.tools.analyze_project_structure import (
    ANALYZE_PROJECT_STRUCTURE_TOOL_NAME,
)
from backend.engine.tools.blackboard import (
    BLACKBOARD_TOOL_NAME,
)
from backend.engine.tools.browser_native import (
    BROWSER_TOOL_NAME,
    build_browser_tool_action,
)
from backend.engine.tools.checkpoint import (
    CHECKPOINT_TOOL_NAME,
)
from backend.engine.tools.debugger import DEBUGGER_TOOL_NAME
from backend.engine.tools.delegate_task import (
    DELEGATE_TASK_TOOL_NAME,
)
from backend.engine.tools.execute_mcp_tool import EXECUTE_MCP_TOOL_TOOL_NAME
from backend.engine.tools.lsp_query import (
    CODE_INTELLIGENCE_TOOL_NAME,
)
from backend.engine.tools.memory_manager import (
    MEMORY_MANAGER_TOOL_NAME,
)
from backend.engine.tools.meta_cognition import COMMUNICATE_TOOL_NAME
from backend.engine.tools.note import build_note_action, build_recall_action
from backend.engine.tools.search_code import (
    SEARCH_CODE_TOOL_NAME,
    build_search_code_action,
)
from backend.engine.tools.security_utils import RISK_LEVELS
from backend.engine.tools.task_tracker import TaskTracker
from backend.engine.tools.terminal_manager import (
    TERMINAL_MANAGER_TOOL_NAME,
)
from backend.inference.tool_names import TASK_TRACKER_TOOL_NAME
from backend.ledger.action import (
    Action,
    ActionSecurityRisk,
    AgentThinkAction,
    BrowserToolAction,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    MessageAction,
    PlaybookFinishAction,
    TaskTrackingAction,
)
from backend.ledger.action.agent import CondensationRequestAction
from backend.ledger.action.mcp import MCPAction

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
build_explore_tree_structure_action = cast(
    AgentThinkToolHandler,
    cast(Any, explore_code_tools).build_explore_tree_structure_action,
)
build_read_symbol_definition_action = cast(
    AgentThinkToolHandler,
    cast(Any, explore_code_tools).build_read_symbol_definition_action,
)
build_lsp_query_action = cast(
    ToolHandler, cast(Any, lsp_query_tools).build_lsp_query_action
)
handle_terminal_manager_tool = cast(
    ToolHandler, cast(Any, terminal_manager_tools).handle_terminal_manager_tool
)
handle_debugger_tool = cast(
    ToolHandler, cast(Any, debugger_tools).handle_debugger_tool
)

# Callback for semantic recall — set by the orchestrator at init time.
# Signature: (query: str, k: int) -> list[dict[str, Any]]
_semantic_recall_registry: dict[str, Callable[[str, int], list[dict[str, Any]]]] = {}


def register_semantic_recall(fn: Callable[[str, int], list[dict[str, Any]]]) -> None:
    """Register the vector-memory recall callback (called by orchestrator)."""
    _semantic_recall_registry['fn'] = fn


def get_semantic_recall_fn() -> Callable[[str, int], list[dict[str, Any]]] | None:
    """Return the registered semantic recall callback, or None."""
    return _semantic_recall_registry.get('fn')


if TYPE_CHECKING:
    ModelResponse = Any


def combine_thought(action: Action, thought: str) -> Action:
    """Combine a thought with an existing action's thought.

    Args:
        action: The action to combine the thought with.
        thought: The thought to combine.

    Returns:
        Action: The action with the combined thought.

    """
    if thought:
        existing = getattr(action, 'thought', None)
        action.thought = f'{thought}\n{existing}' if existing else thought
    return action


def set_security_risk(action: Action, arguments: Mapping[str, Any]) -> None:
    """Set the security risk level for the action."""
    if 'security_risk' in arguments:
        if arguments['security_risk'] in RISK_LEVELS:
            action.security_risk = getattr(
                ActionSecurityRisk, str(arguments['security_risk'])
            )
        else:
            logger.warning(
                'Invalid security_risk value: %s', arguments['security_risk']
            )


def _parse_bool_argument(raw: Any) -> bool:
    """Parse bool-ish tool arguments consistently."""
    return raw is True or (isinstance(raw, str) and raw.lower() == 'true')


def _require_tool_argument(
    arguments: Mapping[str, Any], key: str, tool_name: str
) -> Any:
    """Return a required argument value or raise a standardized validation error."""
    if key not in arguments:
        raise FunctionCallValidationError(
            f'Missing required argument "{key}" in tool call {tool_name}'
        )
    return arguments[key]


def _handle_browser_tool(arguments: Mapping[str, Any]) -> BrowserToolAction:
    """Handle native browser-use tool calls."""
    action = build_browser_tool_action(dict(arguments))
    set_security_risk(action, arguments)
    return action


def _handle_cmd_run_tool(arguments: Mapping[str, Any]) -> CmdRunAction:
    """Handle CmdRunTool (Bash) tool call."""
    from backend.engine.tools.bash import (
        windows_drive_glued_hint,
        windows_drive_glued_in_command,
    )

    tool_name = cast(str, create_cmd_run_tool().get('function', {}).get('name', ''))
    command = _require_tool_argument(arguments, 'command', tool_name)
    raw_is_input = arguments.get('is_input', False)
    is_input = _parse_bool_argument(raw_is_input)
    is_background = _parse_bool_argument(arguments.get('is_background', False))
    grep_pattern = arguments.get('grep_pattern')

    glue_hint = (
        windows_drive_glued_hint() if windows_drive_glued_in_command(command) else ''
    )

    action = CmdRunAction(
        command=command,
        is_input=is_input,
        is_background=is_background,
        grep_pattern=grep_pattern,
        truncation_strategy=cast(Any, arguments.get('truncation_strategy')),
        thought=glue_hint,
    )
    if 'timeout' in arguments:
        try:
            action.set_hard_timeout(float(arguments['timeout']))
        except ValueError as e:
            msg = f"Invalid float passed to 'timeout' argument: {arguments['timeout']}"
            raise FunctionCallValidationError(
                msg,
            ) from e
    set_security_risk(action, arguments)
    return action


def _handle_finish_tool(arguments: Mapping[str, Any]) -> PlaybookFinishAction:
    """Handle FinishTool tool call."""
    tool_name = cast(str, create_finish_tool().get('function', {}).get('name', ''))
    message = _require_tool_argument(arguments, 'message', tool_name)
    outputs: dict[str, Any] = {}
    if 'completed' in arguments:
        outputs['completed'] = arguments['completed']
    if 'blocked_by' in arguments:
        outputs['blocked_by'] = arguments['blocked_by']
    if 'next_steps' in arguments:
        outputs['next_steps'] = arguments['next_steps']
    lessons = arguments.get('lessons_learned')
    if lessons:
        outputs['lessons_learned'] = lessons
        # Persist lessons to the scratchpad so `recall(key="lessons")` in the
        # next session actually returns something. Without this, the finish
        # tool's `lessons_learned` field was write-only and died with the turn.
        try:
            from backend.engine.tools.note import append_to_note

            append_to_note('lessons', str(lessons))
        except Exception as exc:
            # Persistence is best-effort; never block finish on scratchpad I/O.
            logger.debug('Failed to persist finish lessons: %s', exc, exc_info=True)
    return PlaybookFinishAction(final_thought=message, outputs=outputs)


def _handle_memory_manager_tool(arguments: Mapping[str, Any]) -> AgentThinkAction:
    """Handle unified memory ops: note, recall, semantic_recall, working_memory."""
    action = arguments.get('action')
    if not action:
        raise FunctionCallValidationError("Missing 'action' in memory_manager tool.")

    if action == 'semantic_recall':
        query = cast(str, arguments.get('key', ''))
        if not query:
            raise FunctionCallValidationError(
                'Missing search phrase "key" in memory_manager (semantic_recall)'
            )
        k = 5
        recall_fn = _semantic_recall_registry.get('fn')
        if recall_fn is None:
            return AgentThinkAction(
                thought='[SEMANTIC_RECALL_RESULT] Vector memory is not available in this session.'
            )
        results = recall_fn(query, k)
        if not results:
            return AgentThinkAction(
                thought=f'[SEMANTIC_RECALL_RESULT] No indexed memory results found for query: {query!r}'
            )
        parts = [
            f'[SEMANTIC_RECALL_RESULT] {len(results)} results for query: {query!r}\n'
        ]
        for i, item in enumerate(results, 1):
            content = item.get('content_text', item.get('content', ''))
            role = item.get('role', 'unknown')
            score = item.get('score', '')
            score_str = f' (score={score:.3f})' if isinstance(score, float) else ''
            parts.append(f'  [{i}] ({role}{score_str}) {content[:500]}')
        return AgentThinkAction(thought='\n'.join(parts))

    elif action == 'working_memory':
        import backend.engine.tools.working_memory as working_memory_tools

        # Map arguments back to what build_working_memory_action expects
        wm_args = {
            'command': cast(str, arguments.get('update_type', 'get')),
            'section': cast(str, arguments.get('section', 'all')),
            'content': cast(str, arguments.get('content', '')),
        }
        build_working_memory_action = cast(
            AgentThinkToolHandler,
            cast(Any, working_memory_tools).build_working_memory_action,
        )
        return build_working_memory_action(wm_args)

    else:
        raise FunctionCallValidationError(f'Unknown memory_manager action: {action}')


def _handle_search_code_tool(arguments: Mapping[str, Any]) -> AgentThinkAction:
    """Handle SEARCH_CODE_TOOL: fast code search via ripgrep/grep."""
    return build_search_code_action(
        pattern=cast(str, arguments.get('pattern', '')),
        path=cast(str, arguments.get('path', '.')),
        file_pattern=cast(str, arguments.get('file_pattern', '')),
        context_lines=cast(int, arguments.get('context_lines', 2)),
        case_sensitive=cast(bool, arguments.get('case_sensitive', False)),
        max_results=cast(int, arguments.get('max_results', 50)),
    )


def _handle_checkpoint_tool(arguments: Mapping[str, Any]) -> AgentThinkAction:
    """Handle checkpoint tool: save/view/revert/clear progress checkpoints."""
    return build_checkpoint_action(dict(arguments))


def _handle_analyze_project_structure_tool(
    arguments: Mapping[str, Any],
) -> AgentThinkAction:
    """Handle analyze_project_structure tool: structural overview of the workspace."""
    return build_analyze_project_structure_action(dict(arguments))


def _validate_text_editor_args(
    arguments: Mapping[str, Any]
) -> tuple[str, str]:
    """Validate required arguments for text_editor tool."""
    tool_name = cast(str, create_text_editor_tool().get('function', {}).get('name', ''))
    command = _require_tool_argument(arguments, 'command', tool_name)
    path = arguments.get('path')
    if not path:
        msg = f'Missing required argument "path" in tool call {tool_name}'
        raise FunctionCallValidationError(msg)
    return str(path), str(command)


def _normalize_file_editor_command_and_args(
    command: str,
    arguments: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Normalize canonical file editor arguments.

    No aliases — the command value must match what the schema declares.
    """
    normalized_command = str(command or '').strip().lower()
    normalized_args: dict[str, Any] = dict(arguments)
    return normalized_command, normalized_args


def _filter_valid_editor_kwargs(
    other_kwargs: Mapping[str, Any]
) -> dict[str, Any]:
    """Filter and validate kwargs for file editor."""
    text_editor_tool = create_text_editor_tool()
    valid_params = set(
        cast(dict[str, Any], text_editor_tool.get('function', {}).get('parameters', {})).get('properties', {}).keys()
    )
    valid_kwargs_for_editor: dict[str, Any] = {}
    tool_name = cast(str, text_editor_tool.get('function', {}).get('name', ''))

    for key, value in other_kwargs.items():
        if key not in valid_params:
            msg = f'Unexpected argument {key} in tool call {tool_name}. Allowed arguments are: {valid_params}'
            raise FunctionCallValidationError(
                msg,
            )
        if key != 'security_risk':
            valid_kwargs_for_editor[key] = value
    return valid_kwargs_for_editor


def _preview_str_replace_edit(
    path: str, command: str, kwargs: Mapping[str, Any]
) -> AgentThinkAction:
    """Generate a unified diff preview of what an insert_text edit would produce."""
    import difflib
    import os

    if not os.path.isfile(path):
        return AgentThinkAction(thought=f'[PREVIEW] File not found: {path}')

    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            original_lines = f.readlines()
    except OSError as exc:
        return AgentThinkAction(thought=f'[PREVIEW] Cannot read {path}: {exc}')

    new_lines = list(original_lines)

    if command == 'insert_text':
        insert_line = int(kwargs.get('insert_line', 0))
        new_str = cast(str, kwargs.get('new_str', ''))
        insert_text = new_str if new_str.endswith('\n') else new_str + '\n'
        new_lines[insert_line:insert_line] = [insert_text]

    diff = difflib.unified_diff(
        original_lines,
        new_lines,
        fromfile=f'a/{path}',
        tofile=f'b/{path}',
        lineterm='',
    )
    diff_text = '\n'.join(diff)
    if not diff_text:
        return AgentThinkAction(thought=f'[PREVIEW] No changes detected for {path}')

    return AgentThinkAction(
        thought=(
            f'[PREVIEW] Proposed changes for {path} (dry-run, no file writes):\n'
            f'```diff\n{diff_text}\n```'
        )
    )


def _apply_confidence_preview_override(
    kwargs: dict[str, Any], path: str
) -> None:
    """If confidence < 0.7, force preview mode. Mutates kwargs."""
    confidence = kwargs.pop('confidence', None)
    if confidence is None or not isinstance(confidence, (int, float)):
        return
    if float(confidence) >= 0.7:
        return
    logger.info(
        '[confidence] Low confidence (%.2f) on %s — switching to preview mode',
        confidence,
        path,
    )
    kwargs.setdefault('preview', True)


def _is_preview_enabled(raw: Any) -> bool:
    """Parse preview flag from tool arguments."""
    return _parse_bool_argument(raw)


def _handle_llm_based_file_edit_tool(arguments: Mapping[str, Any]) -> FileEditAction:
    """Handle legacy direct content edits over an optional line range."""
    path = _require_tool_argument(arguments, 'path', 'llm_based_file_edit')
    content = _require_tool_argument(arguments, 'content', 'llm_based_file_edit')

    action = FileEditAction(
        path=str(path),
        content=str(content),
        start=cast(int, arguments.get('start', 1)),
        end=cast(int, arguments.get('end', -1)),
        impl_source=FileEditSource.LLM_BASED_EDIT,
    )
    set_security_risk(action, arguments)
    return action


def _handle_text_editor_tool(arguments: Mapping[str, Any]) -> Action:
    """Handle text_editor tool call."""
    command = cast(str, arguments.get('command', ''))

    path, command = _validate_text_editor_args(arguments)
    command, normalized_args = _normalize_file_editor_command_and_args(
        command, arguments
    )

    # Repair double-escape residue (``\n`` / ``\"``) that slips through when
    # models mis-encode tool-call JSON. Only applies to structured file types
    # where literal escape pairs are syntactically impossible; a no-op for
    # anything else. The repair is logged so the model sees the correction.
    from backend.core.content_escape_repair import repair_arguments_in_place

    repair_changes = repair_arguments_in_place(normalized_args, path)
    if repair_changes:
        logger.warning(
            '[escape_repair] %s: corrected literal escapes in %s',
            path,
            ', '.join(f'{name}(x{count})' for name, count in repair_changes),
        )
    valid_commands = {
        'read_file',
        'create_file',
        'replace_text',
        'insert_text',
        'undo_last_edit',
    }
    if command not in valid_commands:
        raise FunctionCallValidationError(
            f"Unknown command '{command}' for text_editor tool. "
            f"Valid commands: {sorted(valid_commands)}"
        )
    path = str(normalized_args.get('path', path))
    other_kwargs = {
        k: v for k, v in normalized_args.items() if k not in ['command', 'path']
    }

    _apply_confidence_preview_override(other_kwargs, path)

    raw_preview = other_kwargs.pop('preview', False)
    if _is_preview_enabled(raw_preview) and command == 'insert_text':
        return _preview_str_replace_edit(path, command, other_kwargs)

    if command == 'read_file':
        return FileReadAction(
            path=path,
            impl_source=FileReadSource.FILE_EDITOR,
            view_range=cast(Any, other_kwargs.get('view_range')),
        )

    other_kwargs.pop('view_range', None)
    valid_kwargs = _filter_valid_editor_kwargs(other_kwargs)

    action = FileEditAction(
        path=path,
        command=command,
        impl_source=FileEditSource.FILE_EDITOR,
        **valid_kwargs,
    )
    set_security_risk(action, arguments)
    return action


def _handle_think_tool(arguments: Mapping[str, Any]) -> AgentThinkAction:
    """Handle ThinkTool tool call."""
    tool_name = cast(str, create_think_tool().get('function', {}).get('name', ''))
    thought = _require_tool_argument(arguments, 'thought', tool_name)
    return AgentThinkAction(thought=thought)


def _handle_summarize_context_tool(
    arguments: Mapping[str, Any]
) -> CondensationRequestAction:
    """Handle Summarize Context tool call."""
    return CondensationRequestAction()


def _normalize_task_tracker_step(s: Mapping[str, Any], idx: int) -> dict[str, Any]:
    """Normalize a single task step dict. Raises FunctionCallValidationError on invalid input."""
    from backend.core.contracts.state import normalize_plan_step_payload

    if not isinstance(s, dict):
        raise FunctionCallValidationError(
            f'Task item must be a dictionary, got {type(s)}'
        )
    try:
        return normalize_plan_step_payload(s, idx)
    except TypeError as e:
        raise FunctionCallValidationError(str(e)) from e


def _normalize_task_tracker_list(
    raw_list: list[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Normalize task list. Raises FunctionCallValidationError on invalid structure."""
    try:
        return [
            _normalize_task_tracker_step(task, i + 1) for i, task in enumerate(raw_list)
        ]
    except FunctionCallValidationError:
        raise
    except Exception as e:
        logger.warning('Error normalizing task list: %s', e)
        raise FunctionCallValidationError(f'Invalid task list structure: {e}') from e


def _handle_task_tracker_tool(arguments: Mapping[str, Any]) -> Action:
    """Handle TASK_TRACKER_TOOL tool call."""
    command = _require_tool_argument(arguments, 'command', TASK_TRACKER_TOOL_NAME)
    if command not in {'view', 'update'}:
        raise FunctionCallValidationError(
            f'Unsupported command {command!r} for tool call {TASK_TRACKER_TOOL_NAME}'
        )

    if command == 'update' and 'task_list' not in arguments:
        raise FunctionCallValidationError(
            f'Missing required argument "task_list" for "update" command in tool call {TASK_TRACKER_TOOL_NAME}'
        )

    tracker = TaskTracker()
    raw_task_list: Sequence[Mapping[str, Any]]

    existing_normalized_task_list: list[dict[str, Any]] = []
    if command == 'view':
        raw_task_list = cast(list[Mapping[str, Any]], tracker.load_from_file())
    else:
        # Capture the current persisted plan so we can detect no-op updates
        # that otherwise create tool-call loops without advancing execution.
        existing_raw = tracker.load_from_file()
        try:
            existing_normalized_task_list = _normalize_task_tracker_list(
                cast(list[Mapping[str, Any]], existing_raw)
            )
        except FunctionCallValidationError:
            existing_normalized_task_list = []
        raw_task_list_any = arguments.get('task_list', [])
        if not isinstance(raw_task_list_any, Sequence):
            raise FunctionCallValidationError(
                f'Invalid format for "task_list". Expected a list but got {type(raw_task_list_any)}.'
            )
        raw_task_list = cast(Sequence[Mapping[str, Any]], raw_task_list_any)

    normalized_task_list = _normalize_task_tracker_list(list(raw_task_list))

    if (
        command == 'update'
        and normalized_task_list
        and normalized_task_list == existing_normalized_task_list
    ):
        logger.info('Converting no-op task_tracker update into a no-op task action')
        return TaskTrackingAction(
            command=command,
            task_list=normalized_task_list,
            thought=(
                '[TASK_TRACKER] Update skipped because the plan is unchanged. '
                'Do a concrete next action now (edit, run command/tests, or read a targeted file), '
                'and refresh tracking only after status/result changes.'
            ),
        )

    if command == 'update':
        tracker.save_to_file(normalized_task_list)

    return TaskTrackingAction(command=command, task_list=normalized_task_list)


def _handle_mcp_tool(
    tool_call_name: str, arguments: Mapping[str, Any] | None
) -> MCPAction:
    """Handle MCP tool call."""
    logger.debug(
        'Creating MCP action for tool: %s with arguments: %s', tool_call_name, arguments
    )

    # Basic validation - ensure arguments is a dict
    if arguments is None:
        logger.warning('MCP tool arguments is not a mapping, got: %s', type(arguments))
        normalized_args = {}
    else:
        normalized_args = dict(arguments)

    return MCPAction(name=tool_call_name, arguments=normalized_args)


def _merge_mcp_gateway_inner_arguments(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Merge MCP tool args from ``call_mcp_tool`` into one dict.

    Frontier models often place parameter keys beside ``tool_name`` instead of
    nesting them under ``arguments``. Without this merge, the MCP child sees
    an empty object and returns -32602 (e.g. Context7 ``resolve-library-id``).
    """
    raw_inner = arguments.get('arguments')
    if isinstance(raw_inner, Mapping):
        inner: dict[str, Any] = dict(cast(Mapping[str, Any], raw_inner))
    else:
        inner = {}

    for key, value in arguments.items():
        if key in ('tool_name', 'arguments'):
            continue
        if value is None:
            continue
        if key not in inner or inner.get(key) in (None, ''):
            inner[key] = value

    return inner


def _apply_context7_resolve_library_defaults(inner: dict[str, Any]) -> None:
    """Context7 ``resolve-library-id`` requires both ``libraryName`` and ``query``."""
    if not inner.get('libraryName') or inner.get('query') not in (None, ''):
        return
    ln = str(inner['libraryName']).strip()
    if not ln:
        return
    inner['query'] = (
        f'Documentation, setup, and API reference for {ln} — pick the best-matching library.'
    )


def _handle_execute_mcp_tool_tool(arguments: dict[str, Any]) -> MCPAction:
    """Handle the call_mcp_tool gateway — route to the real MCP tool."""
    tool_name = _require_tool_argument(arguments, 'tool_name', 'call_mcp_tool')
    inner_args = _merge_mcp_gateway_inner_arguments(arguments)
    if tool_name == 'resolve-library-id':
        _apply_context7_resolve_library_defaults(inner_args)
    logger.info('MCP gateway routing to tool: %s', tool_name)
    return MCPAction(name=tool_name, arguments=inner_args)


def _validate_symbol_editor_args(
    arguments: Mapping[str, Any], tool_name: str
) -> tuple[str, str]:
    """Validate required arguments for structure editor.

    Args:
        arguments: Tool call arguments
        tool_name: Name of the tool

    Returns:
        Tuple of (command, path)

    Raises:
        FunctionCallValidationError: If validation fails

    """
    command = _require_tool_argument(arguments, 'command', tool_name)
    path = _require_tool_argument(arguments, 'path', tool_name)
    return str(command), str(path)


def _normalize_symbol_editor_alias(
    command: str,
    arguments: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Normalize symbol_editor command casing.

    Canonical-only mode: no legacy command or field aliases are accepted.
    """
    normalized_args: dict[str, Any] = dict(arguments)
    normalized_command = str(command or '').strip().lower()
    return normalized_command, normalized_args


_MAX_EDIT_SYMBOLS_PER_BATCH = 25


def _handle_edit_symbol_body_command(
    editor: Any, path: str, arguments: Mapping[str, Any]
) -> Action:
    """Handle edit_symbol_body command."""
    symbol_name = cast(str | None, arguments.get('symbol_name'))
    new_body = cast(str | None, arguments.get('new_body'))

    if not symbol_name or not new_body:
        raise FunctionCallValidationError(
            "edit_symbol_body requires 'symbol_name' and 'new_body' arguments"
        )

    result = editor.edit_function(path, symbol_name, new_body)

    if result.success:
        return FileReadAction(
            path=path, impl_source=FileReadSource.DEFAULT, thought=result.message
        )
    return MessageAction(content=f'❌ Edit failed: {result.message}')


def _handle_edit_symbols_command(
    editor: Any, path: str, arguments: Mapping[str, Any]
) -> Action:
    """Apply multiple ``edit_symbol_body``-style replacements in one call.

    On any failure after the file was modified, restores the file from a
    pre-batch snapshot so the workspace does not stay half-refactored.
    """
    import os

    raw_edits_any = arguments.get('edits') or arguments.get('symbol_edits')
    if not isinstance(raw_edits_any, Sequence) or isinstance(raw_edits_any, (str, bytes)):
        raise FunctionCallValidationError(
            "edit_symbols requires a non-empty 'edits' array "
            "(objects with function_name or symbol, and new_body)"
        )
    raw_edits: list[Any] = list(raw_edits_any)
    if not raw_edits:
        raise FunctionCallValidationError(
            "edit_symbols requires a non-empty 'edits' array "
            "(objects with function_name or symbol, and new_body)"
        )
    if len(raw_edits) > _MAX_EDIT_SYMBOLS_PER_BATCH:
        raise FunctionCallValidationError(
            f'edit_symbols supports at most {_MAX_EDIT_SYMBOLS_PER_BATCH} edits per call'
        )

    normalized: list[tuple[str, str]] = []
    seen: set[str] = set()
    for i, item_any in enumerate(raw_edits):
        if not isinstance(item_any, Mapping):
            raise FunctionCallValidationError(
                f'edit_symbols edits[{i}] must be an object'
            )
        item: Mapping[str, Any] = cast(Mapping[str, Any], item_any)
        fn = cast(str | None, item.get('symbol_name'))
        nb = cast(str | None, item.get('new_body'))
        if not fn:
            raise FunctionCallValidationError(
                f'edit_symbols edits[{i}] requires symbol_name and new_body'
            )
        if not isinstance(nb, str):
            raise FunctionCallValidationError(
                f'edit_symbols edits[{i}] requires new_body (string)'
            )
        key = fn.strip()
        if key in seen:
            raise FunctionCallValidationError(
                f'edit_symbols: duplicate symbol {key!r} in batch'
            )
        seen.add(key)
        normalized.append((key, nb))

    backup: str | None = None
    if os.path.isfile(path):
        try:
            with open(path, encoding='utf-8') as f:
                backup = f.read()
        except OSError as e:
            return MessageAction(
                content=f'❌ edit_symbols: could not read {path} for backup: {e}'
            )

    messages: list[str] = []
    for idx, (fn, nb) in enumerate(normalized):
        result = editor.edit_function(path, fn, nb)
        if not result.success:
            if backup is not None:
                try:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(backup)
                except OSError as restore_err:
                    return MessageAction(
                        content=(
                            f'❌ edit_symbols failed at step {idx + 1} ({fn}): {result.message}. '
                            f'Could not restore file: {restore_err}'
                        )
                    )
            return MessageAction(
                content=(
                    f'❌ edit_symbols failed at step {idx + 1} ({fn}): {result.message} '
                    '(file restored to pre-batch state)'
                    if backup is not None
                    else f'❌ edit_symbols failed at step {idx + 1} ({fn}): {result.message}'
                )
            )
        messages.append(result.message)

    summary = (
        f'✓ edit_symbols applied {len(normalized)} replacement(s) in {path}:\n'
        + '\n'.join(f'  - {m}' for m in messages)
    )
    return FileReadAction(
        path=path, impl_source=FileReadSource.DEFAULT, thought=summary
    )


def _handle_rename_symbol_command(
    editor: Any, path: str, arguments: Mapping[str, Any]
) -> Action:
    """Handle rename_symbol command."""
    old_name = cast(str | None, arguments.get('old_name'))
    new_name = cast(str | None, arguments.get('new_name'))

    if not old_name or not new_name:
        raise FunctionCallValidationError(
            "rename_symbol requires 'old_name' and 'new_name' arguments"
        )

    result = editor.rename_symbol(path, old_name, new_name)

    if result.success:
        return FileReadAction(
            path=path, impl_source=FileReadSource.DEFAULT, thought=result.message
        )
    return MessageAction(content=f'❌ Rename failed: {result.message}')


def _handle_find_symbol_command(
    editor: Any, path: str, arguments: Mapping[str, Any]
) -> Action:
    """Handle find_symbol command."""
    symbol_name = cast(str | None, arguments.get('symbol_name'))
    if not symbol_name:
        raise FunctionCallValidationError("find_symbol requires 'symbol_name' argument")

    symbol_type = cast(str | None, arguments.get('symbol_type'))
    result = editor.find_symbol(path, symbol_name, symbol_type)

    if result:
        message = (
            f"✓ Found '{symbol_name}' in {path}:\n"
            f"  Type: {result.node_type}\n"
            f"  Lines: {result.line_start}-{result.line_end}"
        )
        if result.parent_name:
            message += f'\n  Parent: {result.parent_name}'
        return MessageAction(content=message)
    return MessageAction(content=f"❌ Symbol '{symbol_name}' not found in {path}")


def _handle_replace_range_command(
    editor: Any, path: str, arguments: Mapping[str, Any]
) -> Action:
    """Handle replace_range command."""
    start_line = arguments.get('start_line')
    end_line = arguments.get('end_line')
    new_code = arguments.get('new_code')

    if start_line is None or end_line is None or new_code is None:
        raise FunctionCallValidationError(
            "replace_range requires 'start_line', 'end_line', and 'new_code' arguments"
        )

    result = editor.replace_code_range(path, start_line, end_line, new_code)

    if result.success:
        return FileReadAction(
            path=path, impl_source=FileReadSource.DEFAULT, thought=result.message
        )
    return MessageAction(content=f'❌ Replace failed: {result.message}')


def _handle_normalize_indent_command(
    editor: Any, path: str, arguments: Mapping[str, Any]
) -> Action:
    """Handle normalize_indent command."""
    style = arguments.get('style')
    size = arguments.get('size')
    result = editor.normalize_file_indent(path, style, size)

    if result.success:
        return FileReadAction(
            path=path, impl_source=FileReadSource.DEFAULT, thought=result.message
        )
    return MessageAction(content=f'❌ Normalization failed: {result.message}')


def _handle_create_file_command(path: str, arguments: Mapping[str, Any]) -> Action:
    """Handle create_file command — delegates to text_editor create_file."""
    file_text = cast(str, arguments.get('file_text', ''))
    return FileEditAction(
        path=path,
        command='create_file',
        file_text=file_text,
        impl_source=FileEditSource.FILE_EDITOR,
    )


def _handle_read_file_command(
    path: str, _arguments: Mapping[str, Any] | None = None
) -> Action:
    """Handle read_file command — reads file contents."""
    return FileReadAction(path=path, impl_source=FileReadSource.FILE_EDITOR)


def _handle_insert_text_command(path: str, arguments: Mapping[str, Any]) -> Action:
    """Handle insert_text command — inserts text after a line number."""
    new_str = cast(str | None, arguments.get('new_str'))
    insert_line = arguments.get('insert_line')
    if new_str is None or insert_line is None:
        raise FunctionCallValidationError(
            "insert_text requires 'new_str' and 'insert_line' arguments"
        )
    return FileEditAction(
        path=path,
        command='insert_text',
        insert_line=int(insert_line),
        new_str=new_str,
        impl_source=FileEditSource.FILE_EDITOR,
    )


def _handle_undo_last_edit_command(
    path: str, _arguments: Mapping[str, Any] | None = None
) -> Action:
    """Handle undo_last_edit — restores last snapshot for *path* in runtime FileEditor."""
    return FileEditAction(
        path=path,
        command='undo_last_edit',
        impl_source=FileEditSource.FILE_EDITOR,
    )


def _handle_symbol_editor_tool(arguments: Mapping[str, Any]) -> Action:
    """Handle StructureEditor tool call."""
    tool_name = cast(
        str, create_symbol_editor_tool().get('function', {}).get('name', '')
    )

    # Validate arguments
    command, path = _validate_symbol_editor_args(dict(arguments), tool_name)
    command, normalized_args = _normalize_symbol_editor_alias(command, dict(arguments))

    # Repair double-escaped content (``\n`` / ``\"``) before it reaches the
    # StructureEditor. Structure-aware commands (replace_range, etc.) build
    # FileEditActions directly and would otherwise bypass the repair applied
    # in ``_handle_text_editor_tool``.
    from backend.core.content_escape_repair import repair_arguments_in_place

    repair_changes = repair_arguments_in_place(normalized_args, path)
    if repair_changes:
        logger.warning(
            '[escape_repair] %s (symbol_editor): corrected literal escapes in %s',
            path,
            ', '.join(f'{name}(x{count})' for name, count in repair_changes),
        )

    file_editor_commands = {
        'create_file',
        'read_file',
        'insert_text',
        'undo_last_edit',
    }
    if command in file_editor_commands:
        passthrough_args: dict[str, Any] = {
            'command': command,
            'path': path,
        }
        for key in (
            'file_text',
            'new_str',
            'insert_line',
            'start_line',
            'end_line',
            'view_range',
            'normalize_ws',
            'match_mode',
            'preview',
            'confidence',
            'edit_mode',
            'format_kind',
            'format_op',
            'format_path',
            'format_value',
            'anchor_type',
            'anchor_value',
            'anchor_occurrence',
            'section_action',
            'section_content',
            'patch_text',
            'expected_hash',
            'expected_file_hash',
            'start_line',
            'end_line',
            'security_risk',
        ):
            if key in normalized_args:
                passthrough_args[key] = normalized_args[key]
        return _handle_text_editor_tool(passthrough_args)

    # Initialize editor
    try:
        from backend.engine.tools.structure_editor import StructureEditor

        editor = StructureEditor()
    except Exception as e:
        raise FunctionCallValidationError(
            f'Failed to initialize Structure Editor: {e}'
        ) from e

    # Command dispatch map — editor-powered commands use the StructureEditor instance
    editor_command_handlers = {
        'edit_symbol_body': _handle_edit_symbol_body_command,
        'edit_symbols': _handle_edit_symbols_command,
        'rename_symbol': _handle_rename_symbol_command,
        'find_symbol': _handle_find_symbol_command,
        'replace_range': _handle_replace_range_command,
        'normalize_indent': _handle_normalize_indent_command,
    }
    # File I/O commands delegate directly to runtime actions (no StructureEditor needed)
    # Simple command handlers for standard file operations
    simple_command_handlers: dict[str, Callable[[str, Mapping[str, Any]], Action]] = {
        'create_file': _handle_create_file_command,
        'read_file': _handle_read_file_command,
        'insert_text': _handle_insert_text_command,
        'undo_last_edit': _handle_undo_last_edit_command,
    }

    # Execute command
    try:
        if command in editor_command_handlers:
            handler = editor_command_handlers[command]
            return handler(editor, path, normalized_args)
        elif command in simple_command_handlers:
            simple_handler = simple_command_handlers[command]
            return simple_handler(path, normalized_args)
        else:
            all_cmds = list(editor_command_handlers.keys()) + list(
                simple_command_handlers.keys()
            )
            raise FunctionCallValidationError(
                f"Unknown command '{command}' for symbol_editor tool. "
                f"Valid commands: {all_cmds}"
            )

    except FunctionCallValidationError:
        raise
    except Exception as e:
        return MessageAction(content=f'❌ Structure Editor error: {str(e)}')


def _handle_communicate_tool(arguments: Mapping[str, Any]) -> Action:
    """Route the unified communicate tool to the specific Action class based on intent."""
    intent = cast(str, arguments.get('intent', 'clarification'))
    message = cast(str, arguments.get('message', ''))
    options = cast(Sequence[str], arguments.get('options', []))
    context = cast(str, arguments.get('context', ''))
    thought = cast(str, arguments.get('thought', ''))

    if intent == 'uncertainty':
        from backend.ledger.action.agent import UncertaintyAction

        return UncertaintyAction(
            uncertainty_level=0.5,
            specific_concerns=[message],
            requested_information=context,
            thought=thought,
        )

    elif intent == 'proposal':
        from backend.ledger.action.agent import ProposalAction

        # Format the options cleanly for the existing UI
        formatted_options: list[dict[str, Any]] = (
            [{'approach': opt, 'pros': [], 'cons': []} for opt in options]
            if options
            else [{'approach': message}]
        )
        return ProposalAction(
            options=formatted_options,
            rationale=context or message,
            thought=thought,
            recommended=0,
        )

    elif intent == 'escalate':
        from backend.ledger.action.agent import EscalateToHumanAction

        return EscalateToHumanAction(
            reason=message,
            attempts_made=[context] if context else [],
            specific_help_needed='',
            thought=thought,
        )

    else:  # Default to clarification
        from backend.ledger.action.agent import ClarificationRequestAction

        return ClarificationRequestAction(
            question=message,
            options=list(options),
            context=context,
            thought=thought,
        )


def _create_tool_dispatch_map() -> dict[str, ToolHandler]:
    """Create dispatch map for tool handlers."""
    return {
        cast(str, create_cmd_run_tool().get('function', {}).get('name', '')): _handle_cmd_run_tool,
        cast(str, create_finish_tool().get('function', {}).get('name', '')): _handle_finish_tool,
        cast(str, create_text_editor_tool().get('function', {}).get('name', '')): _handle_text_editor_tool,
        cast(str, create_symbol_editor_tool().get('function', {}).get('name', '')): _handle_symbol_editor_tool,
        cast(str, create_think_tool().get('function', {}).get('name', '')): _handle_think_tool,
        cast(str, create_summarize_context_tool().get('function', {}).get('name', '')): _handle_summarize_context_tool,
        TASK_TRACKER_TOOL_NAME: _handle_task_tracker_tool,
        MEMORY_MANAGER_TOOL_NAME: _handle_memory_manager_tool,
        NOTE_TOOL_NAME: lambda args: build_note_action(cast(str, args['key']), cast(str, args['value'])),
        RECALL_TOOL_NAME: lambda args: build_recall_action(cast(str, args['key'])),
        SEARCH_CODE_TOOL_NAME: _handle_search_code_tool,
        ANALYZE_PROJECT_STRUCTURE_TOOL_NAME: _handle_analyze_project_structure_tool,
        DELEGATE_TASK_TOOL_NAME: lambda args: build_delegate_task_action(dict(args)),
        CODE_INTELLIGENCE_TOOL_NAME: lambda args: build_lsp_query_action(dict(args)),
        DEBUGGER_TOOL_NAME: lambda args: handle_debugger_tool(dict(args)),
        BLACKBOARD_TOOL_NAME: lambda args: build_blackboard_action(dict(args)),
        TERMINAL_MANAGER_TOOL_NAME: lambda args: handle_terminal_manager_tool(dict(args)),
        'explore_tree_structure': lambda args: build_explore_tree_structure_action(dict(args)),
        'read_symbol_definition': lambda args: build_read_symbol_definition_action(dict(args)),
        COMMUNICATE_TOOL_NAME: _handle_communicate_tool,
        EXECUTE_MCP_TOOL_TOOL_NAME: _handle_execute_mcp_tool_tool,
        CHECKPOINT_TOOL_NAME: _handle_checkpoint_tool,
        BROWSER_TOOL_NAME: _handle_browser_tool,
    }


def response_to_actions(
    response: ModelResponse,
    mcp_tool_names: list[str] | None = None,
    mcp_tools: dict[str, Any] | None = None,
) -> list[Action]:
    """Convert LLM response to agent actions."""

    def process_with_mcp_tools(tc: Any, args: dict[str, Any]) -> Action:
        return _process_single_tool_call(tc, args)

    return common_response_to_actions(
        response=response,
        create_action_fn=process_with_mcp_tools,
        combine_thought_fn=combine_thought,
        mcp_tool_names=mcp_tool_names,
    )


# Lazily-initialized dispatch map — built once per process to avoid
# re-creating tool definition dicts on every tool call.
_tool_dispatch_map: dict[str, ToolHandler] | None = None


def _get_tool_dispatch_map() -> dict[str, ToolHandler]:
    global _tool_dispatch_map
    if _tool_dispatch_map is None:
        _tool_dispatch_map = _create_tool_dispatch_map()
    return _tool_dispatch_map


def _process_single_tool_call(tool_call: Any, arguments: dict[str, Any]) -> Action:
    """Process a single tool call and return the corresponding action."""
    logger.debug('Tool call in function_calling.py: %s', tool_call)
    tool_dispatch = _get_tool_dispatch_map()

    tool_name = cast(str, tool_call.function.name)
    mcp_tool_names = cast(list[str] | None, getattr(tool_call, '_mcp_tool_names', None))

    if tool_name in tool_dispatch:
        return tool_dispatch[tool_name](arguments)
    if mcp_tool_names and tool_name in mcp_tool_names:
        return _handle_mcp_tool(tool_name, arguments)
    msg = f'Tool {tool_name} is not registered. (arguments: {arguments}). Please check the tool name and retry with an existing tool.'
    raise FunctionCallNotExistsError(
        msg,
    )
