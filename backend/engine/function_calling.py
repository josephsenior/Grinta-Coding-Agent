"""This file contains the function calling implementation for different actions.

This is similar to the functionality of `OrchestratorResponseParser`.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

import backend.engine.tools.analyze_project_structure as analyze_project_structure_tools
import backend.engine.tools.blackboard as blackboard_tools
import backend.engine.tools.checkpoint as checkpoint_tools
import backend.engine.tools.debugger as debugger_tools
import backend.engine.tools.delegate_task as delegate_task_tools
import backend.engine.tools.lsp_query as lsp_query_tools
import backend.engine.tools.terminal_manager as terminal_manager_tools
from backend.core.constants import NOTE_TOOL_NAME, RECALL_TOOL_NAME
from backend.core.editor_recovery import append_editor_recovery_guidance
from backend.core.enums import FileEditSource, FileReadSource
from backend.core.errors import (
    FunctionCallNotExistsError,
    FunctionCallValidationError,
)
from backend.core.logger import app_logger as logger
from backend.engine.common import (
    common_response_to_actions,
)
from backend.engine.function_calling_helpers import (
    combine_thought,
    parse_bool_argument,
    require_tool_argument,
    set_security_risk,
    validate_security_risk,
)
from backend.engine.tools import (
    create_cmd_run_tool,
    create_create_file_tool,
    create_find_symbol_tool,
    create_read_file_tool,
    create_rename_symbol_tool,
    create_undo_last_edit_tool,

    create_finish_tool,
    create_start_file_edit_tool,
    create_summarize_context_tool,
)
from backend.engine.tools.symbol_editor_tool import create_symbol_editor_tool
from backend.engine.tools.text_editor import create_text_editor_tool
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
from backend.engine.tools.read_symbol import (
    READ_SYMBOL_TOOL_NAME,
    build_read_symbol_action,
)
from backend.engine.tools.search_code import (
    SEARCH_CODE_TOOL_NAME,
    build_search_code_action,
)
from backend.engine.tools.task_tracker import TaskTracker
from backend.engine.tools.terminal_manager import (
    TERMINAL_MANAGER_TOOL_NAME,
)
from backend.inference.tool_names import (
    CREATE_FILE_TOOL_NAME,
    FIND_SYMBOL_TOOL_NAME,
    READ_FILE_TOOL_NAME,
    RENAME_SYMBOL_TOOL_NAME,
    START_FILE_EDIT_TOOL_NAME,
    TASK_TRACKER_TOOL_NAME,
    UNDO_LAST_EDIT_TOOL_NAME,
)
from backend.ledger.action import (
    Action,
    AgentThinkAction,
    BrowserToolAction,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    MessageAction,
    PlaybookFinishAction,
    StartFileEditAction,
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
build_lsp_query_action = cast(
    ToolHandler, cast(Any, lsp_query_tools).build_lsp_query_action
)
handle_terminal_manager_tool = cast(
    ToolHandler, cast(Any, terminal_manager_tools).handle_terminal_manager_tool
)
handle_debugger_tool = cast(ToolHandler, cast(Any, debugger_tools).handle_debugger_tool)

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


def _handle_browser_tool(arguments: Mapping[str, Any]) -> BrowserToolAction:
    """Handle native browser-use tool calls."""
    validate_security_risk(arguments, BROWSER_TOOL_NAME)
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
    command = require_tool_argument(arguments, 'command', tool_name)
    validate_security_risk(arguments, tool_name)
    raw_is_input = arguments.get('is_input', False)
    is_input = parse_bool_argument(raw_is_input)
    is_background = parse_bool_argument(arguments.get('is_background', False))
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
    message = require_tool_argument(arguments, 'message', tool_name)
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


def _handle_read_symbol_tool(
    arguments: Mapping[str, Any],
) -> AgentThinkAction:
    """Handle READ_SYMBOL_TOOL: fetch symbol/file source via tree-sitter."""
    return build_read_symbol_action(dict(arguments))


def _handle_checkpoint_tool(arguments: Mapping[str, Any]) -> AgentThinkAction:
    """Handle checkpoint tool: save/view/revert/clear progress checkpoints."""
    return build_checkpoint_action(dict(arguments))


def _handle_analyze_project_structure_tool(
    arguments: Mapping[str, Any],
) -> AgentThinkAction:
    """Handle analyze_project_structure tool: structural overview of the workspace."""
    return build_analyze_project_structure_action(dict(arguments))


def _validate_text_editor_args(arguments: Mapping[str, Any]) -> tuple[str, str]:
    """Validate required arguments for the internal native file tool schema."""
    tool_name = cast(str, create_text_editor_tool().get('function', {}).get('name', ''))
    command = require_tool_argument(arguments, 'command', tool_name)
    if str(command).strip().lower() == 'multi_edit':
        return '', str(command)
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


def _filter_valid_editor_kwargs(other_kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Filter and validate kwargs for file editor."""
    text_editor_tool = create_text_editor_tool()
    valid_params = set(
        cast(dict[str, Any], text_editor_tool.get('function', {}).get('parameters', {}))
        .get('properties', {})
        .keys()
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


def _filter_valid_symbol_editor_kwargs(other_kwargs: Mapping[str, Any]) -> dict[str, Any]:
    """Filter and validate kwargs for symbol editor."""
    symbol_editor_tool = create_symbol_editor_tool()
    valid_params = set(
        cast(dict[str, Any], symbol_editor_tool.get('function', {}).get('parameters', {}))
        .get('properties', {})
        .keys()
    )
    valid_kwargs: dict[str, Any] = {}
    tool_name = cast(str, symbol_editor_tool.get('function', {}).get('name', ''))

    for key, value in other_kwargs.items():
        if key not in valid_params:
            msg = f'Unexpected argument {key} in tool call {tool_name}. Allowed arguments are: {valid_params}'
            raise FunctionCallValidationError(
                msg,
            )
        if key != 'security_risk':
            valid_kwargs[key] = value
    return valid_kwargs


def _handle_text_editor_tool(arguments: Mapping[str, Any]) -> Action:
    """Handle the internal native file tool schema."""
    command = cast(str, arguments.get('command', ''))

    path, command = _validate_text_editor_args(arguments)
    validate_security_risk(arguments, 'file_edit')
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
        'insert_text',
        'undo_last_edit',
        'edit',
        'multi_edit',
    }
    if command not in valid_commands:
        raise FunctionCallValidationError(
            f"Unknown command '{command}' for file edit tool. "
            f'Valid commands: {sorted(valid_commands)}'
        )
    if command == 'multi_edit':
        return _handle_text_editor_multi_edit(arguments)
    # Handle 'edit' command - requires edit_mode parameter
    if command == 'edit':
        edit_mode = normalized_args.get('edit_mode')
        if not edit_mode:
            raise FunctionCallValidationError(
                "[ERROR] file edit command 'edit' requires 'edit_mode'. "
                '[CAUSE] edit_mode was omitted from the tool call arguments. '
                "[SUGGESTION] Provide 'range'. "
                'Example: {"command": "edit", "edit_mode": "range", '
                '"start_line": 1, "end_line": 10, "new_str": "..."}'
            )
        valid_edit_modes = {'range'}
        if edit_mode not in valid_edit_modes:
            raise FunctionCallValidationError(
                f"[ERROR] Unknown edit_mode '{edit_mode}'. "
                f"[CAUSE] '{edit_mode}' is not a recognised edit_mode value. "
                f'[SUGGESTION] Valid values: {sorted(valid_edit_modes)}. '
                f"Example: {{'command': 'edit', 'edit_mode': 'range', 'start_line': 1, 'end_line': 10, 'new_str': '...'}}"
            )
        # Early validation for edit_mode=range required parameters
        if edit_mode == 'range':
            if normalized_args.get('start_line') is None:
                raise FunctionCallValidationError(
                    "[ERROR] edit_mode=range requires 'start_line'. "
                    '[CAUSE] start_line was omitted from the tool call arguments. '
                    '[SUGGESTION] Add start_line: <int> (1-based line number). '
                    'Example: {"command": "edit", "edit_mode": "range", '
                    '"start_line": 1, "end_line": 10, "new_str": "..."}'
                )
            if normalized_args.get('end_line') is None:
                raise FunctionCallValidationError(
                    "[ERROR] edit_mode=range requires 'end_line'. "
                    '[CAUSE] end_line was omitted from the tool call arguments. '
                    '[SUGGESTION] Add end_line: <int> (1-based inclusive end line). '
                    'Example: {"command": "edit", "edit_mode": "range", '
                    '"start_line": 1, "end_line": 10, "new_str": "..."}'
                )
    path = str(normalized_args.get('path', path))
    other_kwargs = {
        k: v for k, v in normalized_args.items() if k not in ['command', 'path']
    }

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


def _parse_text_multi_edit_item(
    raw_item: Mapping[str, Any], idx: int
) -> tuple[str, str, dict[str, Any]]:
    item_path = raw_item.get('path')
    if not isinstance(item_path, str) or not item_path.strip():
        raise FunctionCallValidationError(
            f"multi_edit item {idx} is missing required 'path'."
        )
    command = str(raw_item.get('command') or '').strip().lower()
    if command not in {'create_file', 'insert_text', 'edit'}:
        raise FunctionCallValidationError(
            f"multi_edit item {idx} has unsupported command {command!r}."
        )
    item = dict(raw_item)
    if command == 'edit' and str(item.get('edit_mode') or '').strip().lower() != 'range':
        raise FunctionCallValidationError(
            f"multi_edit item {idx}: command='edit' only supports edit_mode='range'."
        )
    return item_path.strip(), command, item


def _apply_text_multi_edit_operation(
    *,
    temp_editor: Any,
    rel_path: str,
    command: str,
    item: dict[str, Any],
) -> None:
    if command == 'create_file':
        file_text = item.get('file_text')
        if not isinstance(file_text, str):
            raise FunctionCallValidationError(
                "multi_edit create_file requires 'file_text'."
            )
        result = temp_editor(
            command='create_file',
            path=rel_path,
            file_text=file_text,
            overwrite_existing=parse_bool_argument(item.get('overwrite_existing', False)),
        )
    elif command == 'insert_text':
        new_str = item.get('new_str')
        insert_line = item.get('insert_line')
        if not isinstance(new_str, str) or insert_line is None:
            raise FunctionCallValidationError(
                "multi_edit insert_text requires 'new_str' and 'insert_line'."
            )
        result = temp_editor(
            command='insert_text',
            path=rel_path,
            new_str=new_str,
            insert_line=int(insert_line),
        )
    else:
        new_str = item.get('new_str')
        start_line = item.get('start_line')
        end_line = item.get('end_line')
        if not isinstance(new_str, str) or start_line is None or end_line is None:
            raise FunctionCallValidationError(
                "multi_edit edit/range requires 'start_line', 'end_line', and 'new_str'."
            )
        result = temp_editor(
            command='edit',
            path=rel_path,
            edit_mode='range',
            start_line=int(start_line),
            end_line=int(end_line),
            new_str=new_str,
            expected_file_hash=item.get('expected_file_hash'),
        )
    if result.error:
        from backend.core.errors import ToolExecutionError

        raise ToolExecutionError(
            append_editor_recovery_guidance(
                f'multi_edit failed for {rel_path}: {result.error}',
                path=rel_path,
                tool_name='multi_edit',
                content=cast(str | None, item.get('file_text') or item.get('new_str')),
            )
        )


def _sort_multi_edit_bottom_to_top(
    staged_items: list[tuple[str, str, dict[str, Any]]],
) -> list[tuple[str, str, dict[str, Any]]]:
    """Sort multi-edit items so that range edits are applied bottom-to-top.

    For each file, range edits (those with ``start_line``) are sorted in
    descending order so that edits at the bottom of the file are applied
    first.  This prevents earlier edits from shifting the line coordinates
    of later edits.

    Non-range operations (``create_file``) use a high sentinel value so
    they sort before range edits for the same file (they set up the file
    content that subsequent edits modify).
    """
    _SENTINEL = float('inf')

    def _sort_key(entry: tuple[str, str, dict[str, Any]]) -> tuple[str, float]:
        item_path, _command, item = entry
        start_line = item.get('start_line')
        if start_line is not None:
            return (item_path, -int(start_line))
        # create_file / insert_text: put first for their file
        return (item_path, -_SENTINEL)

    return sorted(staged_items, key=_sort_key)


def _handle_text_editor_multi_edit(arguments: Mapping[str, Any]) -> Action:
    raw_edits = arguments.get('file_edits')
    if not isinstance(raw_edits, list) or not raw_edits:
        raise FunctionCallValidationError(
            "multi_edit requires a non-empty 'file_edits' array."
        )
    if len(raw_edits) > _MAX_MULTI_EDIT_FILES:
        raise FunctionCallValidationError(
            f'multi_edit supports at most {_MAX_MULTI_EDIT_FILES} items per call.'
        )

    parsed: list[tuple[str, str, str]] = []
    staged_items: list[tuple[str, str, dict[str, Any]]] = []
    for idx, raw_item in enumerate(raw_edits):
        if not isinstance(raw_item, Mapping):
            raise FunctionCallValidationError(
                f'multi_edit item {idx} must be an object.'
            )
        item_path, command, item = _parse_text_multi_edit_item(raw_item, idx)
        canonical_path, display_path = _resolve_multi_edit_path(item_path, idx)
        parsed.append((canonical_path, display_path, command))
        staged_items.append((canonical_path, command, item))

    try:
        from backend.core.workspace_resolution import require_effective_workspace_root
        from backend.engine.tools.atomic_refactor import AtomicRefactor
        from backend.execution.utils.file_editor import FileEditor, _file_lock_for_path
    except Exception as e:  # pragma: no cover
        from backend.core.errors import ToolExecutionError

        raise ToolExecutionError(f'multi_edit unavailable: {e}') from e

    workspace_root = require_effective_workspace_root()
    refactor = AtomicRefactor()
    transaction = refactor.begin_transaction()
    seen_paths = sorted({item_path for item_path, _cmd, _item in staged_items})
    final_contents: dict[str, str] = {}
    original_snapshots: dict[str, str | None] = {}
    try:
        with ExitStack() as stack:
            for item_path in seen_paths:
                stack.enter_context(_file_lock_for_path(Path(item_path)))
            with tempfile.TemporaryDirectory(prefix='grinta-text-multi-edit-') as temp_root_str:
                temp_root = Path(temp_root_str)
                temp_editor = FileEditor(workspace_root=str(temp_root))
                temp_paths: dict[str, Path] = {}

                # ── Bottom-to-top batch sort ─────────────────────────
                # Sort range edits in descending start_line order per file
                # so that edits at the bottom are applied first.  This
                # prevents earlier edits from shifting the line numbers
                # of later edits.  Non-range operations (create_file,
                # insert_text) use a high sentinel so they sort first
                # (before any range edits for the same file).
                staged_items = _sort_multi_edit_bottom_to_top(staged_items)

                for item_path, command, item in staged_items:
                    real_path = Path(item_path)
                    rel_path = _multi_edit_relative_path(item_path, workspace_root)
                    temp_path = temp_root / rel_path
                    if item_path not in temp_paths:
                        temp_paths[item_path] = temp_path
                        temp_path.parent.mkdir(parents=True, exist_ok=True)
                        if real_path.exists():
                            original_snapshots[item_path] = real_path.read_text(
                                encoding='utf-8'
                            )
                            shutil.copyfile(real_path, temp_path)
                        else:
                            original_snapshots[item_path] = None
                    _apply_text_multi_edit_operation(
                        temp_editor=temp_editor,
                        rel_path=rel_path,
                        command=command,
                        item=item,
                    )
                for item_path, temp_path in temp_paths.items():
                    if not temp_path.exists():
                        from backend.core.errors import ToolExecutionError

                        raise ToolExecutionError(
                            f'multi_edit produced no output for {_multi_edit_relative_path(item_path, workspace_root)}'
                        )
                    final_contents[item_path] = temp_path.read_text(encoding='utf-8')

        for item_path, old_content in original_snapshots.items():
            real_path = Path(item_path)
            disk_now = real_path.read_text(encoding='utf-8') if real_path.exists() else None
            if disk_now != old_content:
                from backend.core.errors import ToolExecutionError

                raise ToolExecutionError(
                    append_editor_recovery_guidance(
                        'multi_edit aborted because the file changed on disk during batch preparation. Re-read and retry.',
                        path=_multi_edit_relative_path(item_path, workspace_root),
                        tool_name='multi_edit',
                    )
                )

        for item_path, final_content in final_contents.items():
            operation = 'modify' if Path(item_path).exists() else 'create'
            refactor.add_file_edit(
                transaction, item_path, final_content, operation=operation
            )
        result = refactor.commit(transaction, validate=False)
    except FunctionCallValidationError:
        raise
    except Exception:
        try:
            refactor.rollback(transaction)
        except Exception:
            pass
        raise

    if not result.success:
        from backend.core.errors import ToolExecutionError

        err_lines = '\n'.join(f'  - {e}' for e in (result.errors or [result.message]))
        raise ToolExecutionError(
            append_editor_recovery_guidance(
                f'multi_edit transaction rolled back — no files modified.\n{err_lines}',
                tool_name='multi_edit',
            )
        )

    paths = sorted({display_path for _item_path, display_path, _command in parsed})
    file_lines = '\n'.join(f'  • {path}' for path in paths)
    return MessageAction(
        content=(
            f'✓ multi_edit committed {result.files_modified} file(s) atomically\n'
            f'{file_lines}'
        )
    )


def _handle_summarize_context_tool(
    arguments: Mapping[str, Any],
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
    raw_list: list[Mapping[str, Any]],
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


def _task_tracker_existing_normalized(
    tracker: TaskTracker,
) -> list[dict[str, Any]]:
    existing_raw = tracker.load_from_file()
    try:
        return _normalize_task_tracker_list(cast(list[Mapping[str, Any]], existing_raw))
    except FunctionCallValidationError:
        return []


def _maybe_noop_task_tracker_action(
    command: str,
    normalized_task_list: list[dict[str, Any]],
    existing_normalized_task_list: list[dict[str, Any]],
) -> TaskTrackingAction | None:
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
    return None


def _handle_task_tracker_tool(arguments: Mapping[str, Any]) -> Action:
    """Handle TASK_TRACKER_TOOL tool call."""
    command = require_tool_argument(arguments, 'command', TASK_TRACKER_TOOL_NAME)
    if command not in {'view', 'update', 'update_status'}:
        raise FunctionCallValidationError(
            f'Unsupported command {command!r} for tool call {TASK_TRACKER_TOOL_NAME}'
        )

    if command == 'update' and 'task_list' not in arguments:
        raise FunctionCallValidationError(
            f'Missing required argument "task_list" for "update" command in tool call {TASK_TRACKER_TOOL_NAME}'
        )

    if command == 'update_status':
        task_id = require_tool_argument(arguments, 'task_id', TASK_TRACKER_TOOL_NAME)
        status = require_tool_argument(arguments, 'status', TASK_TRACKER_TOOL_NAME)
        result = arguments.get('result')
        tracker = TaskTracker()
        success, message = tracker.update_task_status(task_id, status, result)
        if not success:
            return TaskTrackingAction(
                command='update_status',
                task_list=[],
                thought=f'[TASK_TRACKER] {message}',
            )
        return TaskTrackingAction(
            command='update_status',
            task_list=[],
            thought=f'[TASK_TRACKER] {message}',
        )

    tracker = TaskTracker()
    raw_task_list: Sequence[Mapping[str, Any]]
    existing_normalized_task_list: list[dict[str, Any]] = []

    if command == 'view':
        raw_task_list = cast(list[Mapping[str, Any]], tracker.load_from_file())
    else:
        existing_normalized_task_list = _task_tracker_existing_normalized(tracker)
        raw_task_list_any = arguments.get('task_list', [])
        if not isinstance(raw_task_list_any, Sequence):
            raise FunctionCallValidationError(
                f'Invalid format for "task_list". Expected a list but got {type(raw_task_list_any)}.'
            )
        raw_task_list = cast(Sequence[Mapping[str, Any]], raw_task_list_any)

    normalized_task_list = _normalize_task_tracker_list(list(raw_task_list))

    noop = _maybe_noop_task_tracker_action(
        command, normalized_task_list, existing_normalized_task_list
    )
    if noop is not None:
        return noop

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
    tool_name = require_tool_argument(arguments, 'tool_name', 'call_mcp_tool')
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
    command = require_tool_argument(arguments, 'command', tool_name)
    cmd_lower = str(command).strip().lower()
    if cmd_lower == 'multi_edit':
        # multi_edit operates on a list of files (file_edits[]). The top-level
        # `path` is intentionally optional for this batch command.
        path = arguments.get('path', '') or ''
        return str(command), str(path)
    path = require_tool_argument(arguments, 'path', tool_name)
    return str(command), str(path)


def _normalize_symbol_editor_alias(
    command: str,
    arguments: Mapping[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Normalize structure edit command casing.

    Canonical-only mode: no legacy command or field aliases are accepted.
    """
    normalized_args: dict[str, Any] = dict(arguments)
    normalized_command = str(command or '').strip().lower()
    return normalized_command, normalized_args


_MAX_EDIT_SYMBOLS_PER_BATCH = 25


def _handle_edit_symbol_command(
    editor: Any,
    path: str,
    arguments: Mapping[str, Any],
    *,
    tool_name: str = 'start_file_edit',
) -> Action:
    """Handle edit_symbol command."""
    symbol_name = cast(str | None, arguments.get('symbol_name'))
    new_body = cast(str | None, arguments.get('new_body'))
    line_number = cast(int | None, arguments.get('line_number'))

    if not symbol_name or not new_body:
        raise FunctionCallValidationError(
            "edit_symbol requires 'symbol_name' and 'new_body' arguments"
        )

    logger.info(f"Executing edit_symbol: symbol='{symbol_name}' in {path}")

    from backend.utils.treesitter_editor import AmbiguousSymbolError

    try:
        result = editor.edit_function(
            path, symbol_name, new_body, line_number=line_number
        )
    except AmbiguousSymbolError as e:
        error_msg = append_editor_recovery_guidance(
            f"Ambiguous symbol '{symbol_name}': {e}",
            path=path,
            tool_name=tool_name,
        )
        logger.warning(f'❌ {error_msg}')
        from backend.core.errors import ToolExecutionError

        raise ToolExecutionError(error_msg)

    if result.success:
        logger.info(f"✓ edit_symbol succeeded for '{symbol_name}'")
        return FileReadAction(
            path=path, impl_source=FileReadSource.DEFAULT, thought=result.message
        )

    error_msg = append_editor_recovery_guidance(
        f"Edit failed for '{symbol_name}': {result.message}",
        path=path,
        tool_name=tool_name,
    )
    logger.warning(f'❌ {error_msg}')
    from backend.core.errors import ToolExecutionError

    raise ToolExecutionError(error_msg)


def _normalized_edit_symbols_tuple(
    i: int,
    item_any: Any,
    seen: set[str],
) -> tuple[str, str]:
    if not isinstance(item_any, Mapping):
        raise FunctionCallValidationError(f'edit_symbols edits[{i}] must be an object')
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
    return key, nb


def _parse_edit_symbols_edits(arguments: Mapping[str, Any]) -> list[tuple[str, str]]:
    raw_edits_any = arguments.get('edits') or arguments.get('symbol_edits')
    if not isinstance(raw_edits_any, Sequence) or isinstance(
        raw_edits_any, (str, bytes)
    ):
        raise FunctionCallValidationError(
            "edit_symbols requires a non-empty 'edits' array "
            '(objects with function_name or symbol, and new_body)'
        )
    raw_edits: list[Any] = list(raw_edits_any)
    if not raw_edits:
        raise FunctionCallValidationError(
            "edit_symbols requires a non-empty 'edits' array "
            '(objects with function_name or symbol, and new_body)'
        )
    if len(raw_edits) > _MAX_EDIT_SYMBOLS_PER_BATCH:
        raise FunctionCallValidationError(
            f'edit_symbols supports at most {_MAX_EDIT_SYMBOLS_PER_BATCH} edits per call'
        )

    seen: set[str] = set()
    normalized: list[tuple[str, str]] = []
    for i, item_any in enumerate(raw_edits):
        normalized.append(_normalized_edit_symbols_tuple(i, item_any, seen))
    return normalized


def _read_utf8_backup_or_message(path: str) -> tuple[str | None, MessageAction | None]:
    import os

    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, encoding='utf-8') as f:
            return f.read(), None
    except OSError as e:
        return None, MessageAction(
            content=f'❌ edit_symbols: could not read {path} for backup: {e}'
        )


def _edit_symbols_failure_content(
    idx: int, fn: str, result_msg: str, backup: str | None
) -> str:
    step = idx + 1
    base = f'❌ edit_symbols failed at step {step} ({fn}): {result_msg}'
    if backup is not None:
        return f'{base} (file restored to pre-batch state)'
    return base


def _run_edit_symbols_sequence(
    editor: Any,
    path: str,
    normalized: list[tuple[str, str]],
    backup: str | None,
) -> Action:
    logger.info(
        f'Executing edit_symbols batch: {len(normalized)} replacements in {path}'
    )
    messages: list[str] = []
    for idx, (fn, nb) in enumerate(normalized):
        logger.debug(f"Batch step {idx + 1}/{len(normalized)}: symbol='{fn}'")
        result = editor.edit_function(path, fn, nb)
        if result.success:
            logger.debug(f"✓ Step {idx + 1} succeeded ('{fn}')")
            messages.append(result.message)
            continue
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
        error_msg = _edit_symbols_failure_content(idx, fn, result.message, backup)
        logger.warning(error_msg)
        from backend.core.errors import ToolExecutionError

        raise ToolExecutionError(error_msg)

    summary = (
        f'✓ edit_symbols applied {len(normalized)} replacement(s) in {path}:\n'
        + '\n'.join(f'  - {m}' for m in messages)
    )
    return FileReadAction(
        path=path, impl_source=FileReadSource.DEFAULT, thought=summary
    )


def _handle_edit_symbols_command(
    editor: Any,
    path: str,
    arguments: Mapping[str, Any],
    *,
    tool_name: str = 'structure_edit',
) -> Action:
    """Apply multiple ``edit_symbol``-style replacements in one call.

    On any failure after the file was modified, restores the file from a
    pre-batch snapshot so the workspace does not stay half-refactored.
    """
    normalized = _parse_edit_symbols_edits(arguments)
    backup, backup_err = _read_utf8_backup_or_message(path)
    if backup_err is not None:
        return backup_err
    return _run_edit_symbols_sequence(editor, path, normalized, backup)


def _handle_rename_symbol_command(
    editor: Any,
    path: str,
    arguments: Mapping[str, Any],
    *,
    tool_name: str = 'rename_symbol',
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

    error_msg = append_editor_recovery_guidance(
        f'Rename failed: {result.message}',
        path=path,
        tool_name=tool_name,
    )
    logger.warning(f'❌ {error_msg}')
    from backend.core.errors import ToolExecutionError

    raise ToolExecutionError(error_msg)


def _handle_find_symbol_command(
    editor: Any,
    path: str,
    arguments: Mapping[str, Any],
    *,
    tool_name: str = 'find_symbol',
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
            f'  Type: {result.node_type}\n'
            f'  Lines: {result.line_start}-{result.line_end}'
        )
        if result.parent_name:
            message += f'\n  Parent: {result.parent_name}'

        return FileReadAction(
            path=path,
            start=result.line_start,
            end=result.line_end,
            impl_source=FileReadSource.DEFAULT,
            thought=message,
        )

    error_msg = f"Symbol '{symbol_name}' not found in {path}"
    try:
        available_symbols = editor._get_available_symbols(path, symbol_type)
        suggestion = editor.errors.symbol_not_found(symbol_name, available_symbols)
        error_msg = f'{error_msg}\n\n{suggestion.message}'
    except Exception:
        pass
    error_msg = append_editor_recovery_guidance(
        error_msg,
        path=path,
        tool_name=tool_name,
    )
    logger.warning(f'❌ {error_msg}')
    from backend.core.errors import ToolExecutionError

    raise ToolExecutionError(error_msg)


def _handle_replace_range_command(
    editor: Any,
    path: str,
    arguments: Mapping[str, Any],
    *,
    tool_name: str = 'replace_range',
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
    error_msg = append_editor_recovery_guidance(
        f'❌ Replace failed: {result.message}',
        path=path,
        tool_name=tool_name,
    )
    from backend.core.errors import ToolExecutionError

    raise ToolExecutionError(error_msg)


def _handle_normalize_indent_command(
    editor: Any,
    path: str,
    arguments: Mapping[str, Any],
    *,
    tool_name: str = 'normalize_indent',
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
    """Handle create_file command."""
    file_text = cast(str, arguments.get('file_text', ''))
    return FileEditAction(
        path=path,
        command='create_file',
        file_text=file_text,
        overwrite_existing=bool(arguments.get('overwrite_existing', False)),
        impl_source=FileEditSource.FILE_EDITOR,
    )


def _handle_read_file_command(
    path: str, _arguments: Mapping[str, Any] | None = None
) -> Action:
    """Handle read_file command — reads file contents."""
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


def _handle_read_file_tool(arguments: Mapping[str, Any]) -> Action:
    validate_security_risk(arguments, READ_FILE_TOOL_NAME)
    path = require_tool_argument(arguments, 'path', READ_FILE_TOOL_NAME)
    action = _handle_read_file_command(str(path), arguments)
    set_security_risk(action, arguments)
    return action


def _handle_create_file_tool(arguments: Mapping[str, Any]) -> Action:
    validate_security_risk(arguments, CREATE_FILE_TOOL_NAME)
    path = require_tool_argument(arguments, 'path', CREATE_FILE_TOOL_NAME)
    require_tool_argument(arguments, 'file_text', CREATE_FILE_TOOL_NAME)
    normalized_args = dict(arguments)
    from backend.core.content_escape_repair import repair_arguments_in_place

    repair_arguments_in_place(normalized_args, str(path))
    action = _handle_create_file_command(str(path), normalized_args)
    set_security_risk(action, arguments)
    return action


def _handle_undo_last_edit_tool(arguments: Mapping[str, Any]) -> Action:
    validate_security_risk(arguments, UNDO_LAST_EDIT_TOOL_NAME)
    path = require_tool_argument(arguments, 'path', UNDO_LAST_EDIT_TOOL_NAME)
    action = _handle_undo_last_edit_command(str(path), arguments)
    set_security_risk(action, arguments)
    return action


def _handle_rename_symbol_tool(arguments: Mapping[str, Any]) -> Action:
    validate_security_risk(arguments, RENAME_SYMBOL_TOOL_NAME)
    path = require_tool_argument(arguments, 'path', RENAME_SYMBOL_TOOL_NAME)
    normalized_args = dict(arguments)
    from backend.core.content_escape_repair import repair_arguments_in_place
    from backend.engine.tools.structure_editor import StructureEditor

    repair_arguments_in_place(normalized_args, str(path))
    editor = StructureEditor()
    action = _handle_rename_symbol_command(
        editor, str(path), normalized_args, tool_name=RENAME_SYMBOL_TOOL_NAME
    )
    set_security_risk(action, arguments)
    return action


def _handle_find_symbol_tool(arguments: Mapping[str, Any]) -> Action:
    validate_security_risk(arguments, FIND_SYMBOL_TOOL_NAME)
    path = require_tool_argument(arguments, 'path', FIND_SYMBOL_TOOL_NAME)
    normalized_args = dict(arguments)
    from backend.core.content_escape_repair import repair_arguments_in_place
    from backend.engine.tools.structure_editor import StructureEditor

    repair_arguments_in_place(normalized_args, str(path))
    editor = StructureEditor()
    action = _handle_find_symbol_command(
        editor, str(path), normalized_args, tool_name=FIND_SYMBOL_TOOL_NAME
    )
    set_security_risk(action, arguments)
    return action


_MAX_MULTI_EDIT_FILES = 50


def _structure_editor_supports_multi_edit() -> bool:
    """Capability probe used by the system-prompt builder.

    Returns True when this build registers the ``multi_edit`` file_editor
    command. Keeping the probe co-located with the handler ensures the system
    prompt automatically tracks the live tool surface — no flag drift.
    """
    return True


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


def _multi_edit_raise(message: str, *, path: str | None = None) -> None:
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
    item_command = str(raw_item.get('command') or '').strip().lower()
    if not item_command:
        if isinstance(raw_item.get('new_content'), str):
            item_command = 'replace_file'
        elif (
            raw_item.get('start_line') is not None
            or raw_item.get('end_line') is not None
            or raw_item.get('new_code') is not None
        ):
            item_command = 'replace_range'
        elif raw_item.get('symbol_name') and raw_item.get('new_body'):
            item_command = 'edit_symbol'
        else:
            raise FunctionCallValidationError(
                f'multi_edit item {idx}: unable to infer command. '
                "Use 'replace_file', 'replace_range', or 'edit_symbol'."
            )
    return item_command, dict(raw_item)


def _apply_multi_edit_operation(
    *,
    rel_path: str,
    temp_path: Path,
    item_command: str,
    item: dict[str, Any],
    temp_editor: Any,
    structure_editor: Any,
) -> None:
    if item_command == 'replace_file':
        new_content = item.get('new_content')
        if not isinstance(new_content, str):
            raise FunctionCallValidationError(
                "multi_edit replace_file requires 'new_content' (string)."
            )
        result = temp_editor(command='create_file', path=rel_path, file_text=new_content)
        if result.error:
            _multi_edit_raise(
                f'❌ multi_edit replace_file failed for {rel_path}: {result.error}',
                path=rel_path,
            )
        return

    if item_command == 'replace_range':
        start_line = item.get('start_line')
        end_line = item.get('end_line')
        new_code = item.get('new_code')
        if start_line is None or end_line is None or not isinstance(new_code, str):
            raise FunctionCallValidationError(
                "multi_edit replace_range requires 'start_line', 'end_line', and 'new_code'."
            )
        result = temp_editor(
            command='edit',
            path=rel_path,
            edit_mode='range',
            start_line=int(start_line),
            end_line=int(end_line),
            new_str=new_code,
        )
        if result.error:
            _multi_edit_raise(
                f'❌ multi_edit replace_range failed for {rel_path}: {result.error}',
                path=rel_path,
            )
        return

    if item_command == 'edit_symbol':
        symbol_name = item.get('symbol_name')
        new_body = item.get('new_body')
        line_number = item.get('line_number')
        if not isinstance(symbol_name, str) or not isinstance(new_body, str):
            raise FunctionCallValidationError(
                "multi_edit edit_symbol requires 'symbol_name' and 'new_body'."
            )
        result = structure_editor.edit_function(
            str(temp_path),
            symbol_name,
            new_body,
            line_number=line_number,
        )
        if not result.success:
            _multi_edit_raise(
                f'❌ multi_edit edit_symbol failed for {rel_path}: {result.message}',
                path=rel_path,
            )
        return

    raise FunctionCallValidationError(
        f"multi_edit item command {item_command!r} is unsupported. "
        "Use 'replace_file', 'replace_range', or 'edit_symbol'."
    )


def _handle_multi_edit_command(_path: str, arguments: Mapping[str, Any]) -> Action:
    """Apply an atomic multi-file batch edit via :class:`AtomicRefactor`.

    All edits commit together or all are rolled back from per-file backups.
    Side effects run synchronously inside this handler (same pattern as
    ``edit_symbols``); the returned ``MessageAction`` summarizes the outcome.
    """
    raw_edits = arguments.get('file_edits')
    if not isinstance(raw_edits, list) or not raw_edits:
        raise FunctionCallValidationError("multi_edit requires a non-empty 'file_edits' array.")
    if len(raw_edits) > _MAX_MULTI_EDIT_FILES:
        raise FunctionCallValidationError(
            f'multi_edit supports at most {_MAX_MULTI_EDIT_FILES} files per call '
            f'(got {len(raw_edits)}). Split the batch.'
        )

    parsed: list[tuple[str, str, str, dict[str, Any]]] = []
    seen_paths: set[str] = set()
    for idx, item in enumerate(raw_edits):
        if not isinstance(item, Mapping):
            raise FunctionCallValidationError(f'multi_edit item {idx} must be an object.')
        item_path = item.get('path')
        if not isinstance(item_path, str) or not item_path.strip():
            raise FunctionCallValidationError(
                f"multi_edit item {idx} is missing required 'path'."
            )
        requested_path = item_path.strip()
        canonical_path, display_path = _resolve_multi_edit_path(requested_path, idx)
        seen_paths.add(canonical_path)
        item_command, normalized_item = _parse_multi_edit_operation(item, idx)
        parsed.append((canonical_path, display_path, item_command, normalized_item))

    try:
        from backend.engine.tools.atomic_refactor import AtomicRefactor
        from backend.engine.tools.structure_editor import StructureEditor
        from backend.core.workspace_resolution import require_effective_workspace_root
        from backend.execution.utils.file_editor import FileEditor, _file_lock_for_path
    except Exception as e:  # pragma: no cover - defensive import guard
        _multi_edit_raise(f'❌ multi_edit unavailable: AtomicRefactor import failed: {e}')

    workspace_root = require_effective_workspace_root()
    refactor = AtomicRefactor()
    transaction = refactor.begin_transaction()
    try:
        original_snapshots: dict[str, str | None] = {}
        final_contents: dict[str, str] = {}
        with ExitStack() as stack:
            for item_path in sorted(seen_paths):
                stack.enter_context(_file_lock_for_path(Path(item_path)))
            with tempfile.TemporaryDirectory(prefix='grinta-multi-edit-') as temp_root_str:
                temp_root = Path(temp_root_str)
                temp_editor = FileEditor(workspace_root=str(temp_root))
                structure_editor = StructureEditor()
                temp_paths: dict[str, Path] = {}

                for item_path, _display_path, item_command, item in parsed:
                    real_path = Path(item_path)
                    rel_path = _multi_edit_relative_path(item_path, workspace_root)
                    temp_path = temp_root / rel_path
                    if item_path not in temp_paths:
                        temp_paths[item_path] = temp_path
                        temp_path.parent.mkdir(parents=True, exist_ok=True)
                        if real_path.exists():
                            original_snapshots[item_path] = real_path.read_text(
                                encoding='utf-8'
                            )
                            shutil.copyfile(real_path, temp_path)
                        else:
                            original_snapshots[item_path] = None
                    _apply_multi_edit_operation(
                        rel_path=rel_path,
                        temp_path=temp_path,
                        item_command=item_command,
                        item=item,
                        temp_editor=temp_editor,
                        structure_editor=structure_editor,
                    )

                for item_path, temp_path in temp_paths.items():
                    if not temp_path.exists():
                        _multi_edit_raise(
                            f'❌ multi_edit produced no output file for {_multi_edit_relative_path(item_path, workspace_root)}.',
                            path=_multi_edit_relative_path(item_path, workspace_root),
                        )
                    final_contents[item_path] = temp_path.read_text(encoding='utf-8')

            for item_path, old_content in original_snapshots.items():
                real_path = Path(item_path)
                disk_now = (
                    real_path.read_text(encoding='utf-8') if real_path.exists() else None
                )
                if disk_now != old_content:
                    _multi_edit_raise(
                        '❌ multi_edit aborted because the file changed on disk during batch preparation. Re-read and retry.',
                        path=_multi_edit_relative_path(item_path, workspace_root),
                    )

            for item_path, final_content in final_contents.items():
                operation = 'modify' if Path(item_path).exists() else 'create'
                refactor.add_file_edit(transaction, item_path, final_content, operation=operation)
            result = refactor.commit(transaction, validate=False)
    except FunctionCallValidationError:
        raise
    except Exception as e:
        # Best-effort rollback if commit raised before completion.
        try:
            refactor.rollback(transaction)
        except Exception:
            pass
        _multi_edit_raise(f'❌ multi_edit failed before commit: {e}. No files modified.')

    if result.success:
        paths = sorted(
            {display_path for _item_path, display_path, _item_command, _item in parsed}
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
    err_lines = '\n'.join(f'  - {e}' for e in (result.errors or [result.message]))
    _multi_edit_raise(
        f'❌ multi_edit transaction rolled back — no files modified.\n{err_lines}'
    )


_SYMBOL_EDITOR_TEXT_EDITOR_COMMANDS = frozenset(
    {
        'create_file',
        'read_file',
        'insert_text',
        'undo_last_edit',
    }
)

_SYMBOL_EDITOR_BRIDGE_KEYS = (
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
    'expected_hash',
    'expected_file_hash',
    'overwrite_existing',
    'security_risk',
)


def _symbol_editor_bridge_to_text_editor(
    command: str, path: str, normalized_args: dict[str, Any]
) -> Action | None:
    if command not in _SYMBOL_EDITOR_TEXT_EDITOR_COMMANDS:
        return None
    passthrough_args: dict[str, Any] = {'command': command, 'path': path}
    for key in _SYMBOL_EDITOR_BRIDGE_KEYS:
        if key in normalized_args:
            passthrough_args[key] = normalized_args[key]
    return _handle_text_editor_tool(passthrough_args)


def _dispatch_structure_editor_commands(
    editor: Any,
    command: str,
    path: str,
    normalized_args: dict[str, Any],
    *,
    tool_name: str = 'structure_edit',
) -> Action:
    editor_command_handlers: dict[
        str, Callable[[Any, str, Mapping[str, Any]], Action]
    ] = {
        'edit_symbol': _handle_edit_symbol_command,
        'edit_symbols': _handle_edit_symbols_command,
        'rename_symbol': _handle_rename_symbol_command,
        'find_symbol': _handle_find_symbol_command,
        'replace_range': _handle_replace_range_command,
        'normalize_indent': _handle_normalize_indent_command,
    }
    simple_command_handlers: dict[str, Callable[[str, Mapping[str, Any]], Action]] = {
        'create_file': _handle_create_file_command,
        'read_file': _handle_read_file_command,
        'insert_text': _handle_insert_text_command,
        'undo_last_edit': _handle_undo_last_edit_command,
        'multi_edit': _handle_multi_edit_command,
    }
    try:
        if command in editor_command_handlers:
            handler = editor_command_handlers[command]
            return handler(editor, path, normalized_args, tool_name=tool_name)
        if command in simple_command_handlers:
            simple_handler = simple_command_handlers[command]
            return simple_handler(path, normalized_args)
        all_cmds = list(editor_command_handlers.keys()) + list(
            simple_command_handlers.keys()
        )
        raise FunctionCallValidationError(
            f"Unknown command '{command}' for {tool_name} tool. "
            f'Valid commands: {all_cmds}'
        )
    except FunctionCallValidationError:
        raise
    except Exception as e:
        error_msg = append_editor_recovery_guidance(
            f'Symbol Editor error: {str(e)}',
            path=path,
            tool_name=tool_name,
        )
        logger.error(error_msg, exc_info=True)
        from backend.core.errors import ToolExecutionError

        raise ToolExecutionError(error_msg) from e


def _handle_symbol_editor_tool(arguments: Mapping[str, Any]) -> Action:
    """Handle StructureEditor tool call."""
    tool_name = cast(
        str, create_symbol_editor_tool().get('function', {}).get('name', '')
    )

    command, path = _validate_symbol_editor_args(dict(arguments), tool_name)
    validate_security_risk(arguments, tool_name)
    command, normalized_args = _normalize_symbol_editor_alias(command, dict(arguments))

    # Validate command early so invalid commands get clear errors before param filtering
    _VALID_SYMBOL_EDITOR_COMMANDS = {
        'edit_symbol', 'edit_symbols', 'rename_symbol', 'find_symbol',
        'replace_range', 'normalize_indent', 'create_file', 'read_file',
        'insert_text', 'undo_last_edit', 'multi_edit',
    }
    if command not in _VALID_SYMBOL_EDITOR_COMMANDS:
        raise FunctionCallValidationError(
            f"Unknown command '{command}' for structure edit tool. "
            f'Valid commands: {sorted(_VALID_SYMBOL_EDITOR_COMMANDS)}'
        )

    # Repair double-escaped content (``\n`` / ``\"``) before it reaches the
    # StructureEditor. Structure-aware commands (replace_range, etc.) build
    # FileEditActions directly and would otherwise bypass the repair applied
    # in ``_handle_text_editor_tool``.
    from backend.core.content_escape_repair import repair_arguments_in_place

    repair_changes = repair_arguments_in_place(normalized_args, path)
    if repair_changes:
        logger.warning(
            '[escape_repair] %s (structure_edit): corrected literal escapes in %s',
            path,
            ', '.join(f'{name}(x{count})' for name, count in repair_changes),
        )

    # Filter out unknown parameters using the schema whitelist
    filtered_kwargs = {k: v for k, v in normalized_args.items() if k not in ('command', 'path')}
    filtered = _filter_valid_symbol_editor_kwargs(filtered_kwargs)
    # Preserve security_risk for downstream handlers
    if 'security_risk' in normalized_args:
        filtered['security_risk'] = normalized_args['security_risk']
    normalized_args = {'command': command, 'path': path, **filtered}

    bridged = _symbol_editor_bridge_to_text_editor(command, path, normalized_args)
    if bridged is not None:
        return bridged

    try:
        from backend.engine.tools.structure_editor import StructureEditor

        editor = StructureEditor()
    except Exception as e:
        raise FunctionCallValidationError(
            f'Failed to initialize Symbol Editor: {e}'
        ) from e

    action = _dispatch_structure_editor_commands(editor, command, path, normalized_args)
    set_security_risk(action, arguments)
    return action


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




def _handle_start_file_edit_tool(arguments: Mapping[str, Any]) -> Action:
    """Handle metadata-only file edit transaction starter."""
    from backend.engine.file_edit_protocol import (
        reject_content_fields,
        validate_start_file_edit_metadata,
    )

    tool_name = cast(
        str, create_start_file_edit_tool().get('function', {}).get('name', '')
    )
    operation = require_tool_argument(arguments, 'operation', tool_name)
    operation = str(operation).strip().lower()
    normalized_args = dict(arguments)
    reject_content_fields(normalized_args)
    validate_security_risk(normalized_args, tool_name)

    path = normalized_args.get('path')
    if operation == 'multi_edit' and not path:
        path = '<batch>'
    if not path:
        raise FunctionCallValidationError(
            f'Missing required argument "path" in tool call {tool_name}'
        )
    path = str(path)
    metadata = {
        k: v
        for k, v in normalized_args.items()
        if k not in {'operation', 'path'}
    }
    validate_start_file_edit_metadata(operation, path, metadata)

    action = StartFileEditAction(
        path=path,
        operation=operation,
        metadata=metadata,
    )
    set_security_risk(action, normalized_args)
    return action




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
            str, create_read_file_tool().get('function', {}).get('name', '')
        ): _handle_read_file_tool,
        cast(
            str, create_create_file_tool().get('function', {}).get('name', '')
        ): _handle_create_file_tool,
        cast(
            str, create_undo_last_edit_tool().get('function', {}).get('name', '')
        ): _handle_undo_last_edit_tool,
        cast(
            str, create_rename_symbol_tool().get('function', {}).get('name', '')
        ): _handle_rename_symbol_tool,
        cast(
            str, create_find_symbol_tool().get('function', {}).get('name', '')
        ): _handle_find_symbol_tool,
        START_FILE_EDIT_TOOL_NAME: _handle_start_file_edit_tool,
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
        READ_SYMBOL_TOOL_NAME: _handle_read_symbol_tool,
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
        BROWSER_TOOL_NAME: _handle_browser_tool,
    }


def response_to_actions(
    response: ModelResponse,
    mcp_tool_names: list[str] | None = None,
    mcp_tools: dict[str, Any] | None = None,
) -> list[Action]:
    """Convert LLM response to agent actions.

    Normal tools use provider-native tool calls. File content is captured by
    the separate editor-mode protocol after ``start_file_edit``.
    """
    from backend.engine.planner import CODE_PAYLOAD_TOOLS

    def process_with_mcp_tools(tc: Any, args: dict[str, Any]) -> Action:
        return _process_single_tool_call(tc, args)

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


def _process_single_tool_call(tool_call: Any, arguments: dict[str, Any]) -> Action:
    """Process a single tool call and return the corresponding action."""
    logger.debug('Tool call in function_calling.py: %s', tool_call)
    tool_dispatch = _get_tool_dispatch_map()

    tool_name = cast(str, tool_call.function.name)
    if tool_name == 'file_editor':
        raise FunctionCallValidationError(
            'The legacy file-edit tool has been removed. Use the EDIT_FILE raw block protocol '
            'in AGENT mode for file edits.'
        )
    if "__xml_syntax_error__" in arguments:
        from backend.engine.common import _check_format_error_retry_guard
        serialized_args = json.dumps(arguments, sort_keys=True, ensure_ascii=False)
        error_sig = f"xml_syntax_error:{arguments['__xml_syntax_error__']}"
        allowed, reason = _check_format_error_retry_guard(tool_name, serialized_args, error_sig)
        if not allowed:
            logger.error('FORMAT_ERROR retry guard in _process_single_tool_call: %s', reason)
            raise FunctionCallValidationError(
                f'[FORMAT_ERROR] Retry guard stopped repeated FORMAT_ERROR for '
                f'tool `{tool_name}` after multiple attempts.\n'
                f'{reason}\n'
                f'[SYSTEM_ACTION] Report this as a system/tool error.'
            )
        raise FunctionCallValidationError(
            f"Malformed XML tool call for {tool_name}: "
            f"{arguments['__xml_syntax_error__']}"
        )
    mcp_tool_names = cast(list[str] | None, getattr(tool_call, '_mcp_tool_names', None))

    if tool_name in tool_dispatch:
        return tool_dispatch[tool_name](arguments)
    if mcp_tool_names and tool_name in mcp_tool_names:
        return _handle_mcp_tool(tool_name, arguments)
    msg = f'Tool {tool_name} is not registered. (arguments: {arguments}). Please check the tool name and retry with an existing tool.'
    raise FunctionCallNotExistsError(
        msg,
    )
