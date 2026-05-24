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
    create_create_tool,
    create_edit_symbols_tool,
    create_find_symbols_tool,
    create_multiedit_tool,
    create_read_tool,
    create_replace_string_tool,
    create_finish_tool,
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
from backend.engine.tools.search_code import (
    SEARCH_CODE_TOOL_NAME,
    build_search_code_action,
)
from backend.engine.tools.task_tracker import TaskTracker
from backend.engine.tools.terminal_manager import (
    TERMINAL_MANAGER_TOOL_NAME,
)
from backend.inference.tool_names import (
    CREATE_TOOL_NAME,
    EDIT_SYMBOLS_TOOL_NAME,
    FIND_SYMBOLS_TOOL_NAME,
    MULTIEDIT_TOOL_NAME,
    READ_TOOL_NAME,
    REPLACE_STRING_TOOL_NAME,
    TASK_TRACKER_TOOL_NAME,
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


def _workspace_root() -> Path:
    try:
        from backend.core.workspace_resolution import require_effective_workspace_root

        return Path(require_effective_workspace_root()).resolve()
    except Exception:
        return Path.cwd().resolve()


def _safe_workspace_path(path: str, *, must_exist: bool = False) -> Path:
    from backend.core.type_safety.path_validation import SafePath

    return SafePath.validate(
        path,
        workspace_root=_workspace_root(),
        must_exist=must_exist,
        must_be_relative=True,
    ).path


def _relative_display_path(path: Path) -> str:
    root = _workspace_root()
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _sha256_text(content: str) -> str:
    import hashlib

    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def _read_text_for_tool(path: Path) -> str:
    return path.read_text(encoding='utf-8')


def _guard_content_arguments(arguments: Mapping[str, Any]) -> None:
    from backend.core.content_escape_repair import validate_content_payloads

    validate_content_payloads(dict(arguments))


def _symbol_id(path: str, name: str, start_line: int, end_line: int) -> str:
    return f'{path}:{start_line}-{end_line}:{name}'


def _symbol_preview(content: str, start_line: int, end_line: int) -> str:
    lines = content.splitlines()
    if not lines:
        return ''
    selected = lines[start_line - 1 : min(end_line, start_line + 2)]
    return '\n'.join(selected)[:240]


def _candidate_from_location(location: Any, content: str, display_path: str) -> dict[str, Any]:
    name = str(getattr(location, 'symbol_name', '') or '')
    start_line = int(getattr(location, 'line_start', 0) or 0)
    end_line = int(getattr(location, 'line_end', 0) or 0)
    return {
        'symbol_id': _symbol_id(display_path, name, start_line, end_line),
        'name': name,
        'kind': getattr(location, 'node_type', None),
        'parent': getattr(location, 'parent_name', None),
        'path': display_path,
        'start_line': start_line,
        'end_line': end_line,
        'signature': _symbol_preview(content, start_line, end_line),
    }


_SOURCE_SYMBOL_SUFFIXES: frozenset[str] = frozenset(
    {'.py', '.js', '.jsx', '.ts', '.tsx', '.go', '.rs', '.java', '.rb', '.php'}
)
_SKIP_SYMBOL_SEARCH_PARTS: frozenset[str] = frozenset(
    {
        '.git',
        '.hg',
        '.svn',
        '.venv',
        'venv',
        'node_modules',
        '__pycache__',
        '.pytest_cache',
    }
)


def _node_kind(node_type: str) -> str:
    if 'class' in node_type:
        return 'class'
    if 'method' in node_type:
        return 'method'
    return 'function'


def _find_symbol_candidates_in_file(
    path: Path,
    query: str,
    *,
    symbol_kind: str | None = None,
    include_private: bool = False,
) -> list[dict[str, Any]]:
    from backend.utils.treesitter_editor import TreeSitterEditor

    editor = TreeSitterEditor()
    parse_result = editor.parse_file(str(path), use_cache=False)
    if not parse_result:
        return []
    tree, file_bytes, language = parse_result
    content = file_bytes.decode('utf-8', errors='replace')
    display_path = _relative_display_path(path)
    query_lower = query.lower()
    kind_filter = (symbol_kind or '').strip().lower()
    candidates: list[dict[str, Any]] = []

    class_types = {
        'class_definition',
        'class_declaration',
        'class_specifier',
    }
    function_types = {
        'function_definition',
        'function_declaration',
        'function',
        'method_definition',
        'method_declaration',
        'constructor_declaration',
        'function_item',
        'method',
        'singleton_method',
    }
    target_types = class_types | function_types

    def visit(node: Any, parent_name: str | None = None) -> None:
        next_parent = parent_name
        if node.type in target_types:
            name_node = editor.get_name_node(node)
            if name_node is not None:
                name = file_bytes[name_node.start_byte : name_node.end_byte].decode(
                    'utf-8', errors='replace'
                )
                kind = _node_kind(str(node.type))
                if (
                    query_lower in name.lower()
                    and (include_private or not name.startswith('_'))
                    and (not kind_filter or kind == kind_filter)
                ):
                    location = type(
                        '_Location',
                        (),
                        {
                            'symbol_name': name,
                            'node_type': node.type,
                            'parent_name': parent_name,
                            'line_start': node.start_point[0] + 1,
                            'line_end': node.end_point[0] + 1,
                        },
                    )()
                    candidates.append(
                        _candidate_from_location(location, content, display_path)
                    )
                if kind == 'class':
                    next_parent = name
        for child in getattr(node, 'children', []) or []:
            visit(child, next_parent)

    visit(tree.root_node)
    return candidates


def _candidate_paths_for_symbol_search(raw_path: str | None = None) -> list[Path]:
    if raw_path:
        return [_safe_workspace_path(raw_path, must_exist=True)]

    root = _workspace_root()
    paths: list[Path] = []
    for path in root.rglob('*'):
        if len(paths) >= 200:
            break
        if not path.is_file():
            continue
        if path.suffix.lower() not in _SOURCE_SYMBOL_SUFFIXES:
            continue
        if any(part in _SKIP_SYMBOL_SEARCH_PARTS for part in path.parts):
            continue
        paths.append(path)
    return paths


def _find_symbol_candidates(
    query: str,
    *,
    path: str | None = None,
    symbol_kind: str | None = None,
    include_private: bool = False,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for candidate_path in _candidate_paths_for_symbol_search(path):
        candidates.extend(
            _find_symbol_candidates_in_file(
                candidate_path,
                query,
                symbol_kind=symbol_kind,
                include_private=include_private,
            )
        )
    return candidates


def _parse_symbol_id(symbol_id: str) -> tuple[str, str, int, int]:
    try:
        raw_path, range_part, raw_name = symbol_id.rsplit(':', 2)
        start_raw, _, end_raw = range_part.partition('-')
        start_line = int(start_raw)
        end_line = int(end_raw)
    except Exception as exc:
        raise FunctionCallValidationError(
            f'Invalid symbol_id {symbol_id!r}; use an id returned by find_symbols or read(type="symbols").'
        ) from exc
    if not raw_path or not raw_name or start_line < 1 or end_line < start_line:
        raise FunctionCallValidationError(
            f'Invalid symbol_id {symbol_id!r}; use an id returned by find_symbols or read(type="symbols").'
        )
    return raw_path, raw_name, start_line, end_line


def _coerce_optional_int(value: object, field_name: str) -> int | None:
    if value is None or value == '':
        return None
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError) as exc:
        raise FunctionCallValidationError(f'{field_name} must be an integer.') from exc


def _filter_symbol_candidates(
    candidates: list[dict[str, Any]],
    *,
    symbol_name: str,
    parent_symbol: str | None = None,
    occurrence: int | None = None,
) -> list[dict[str, Any]]:
    filtered = [c for c in candidates if c.get('name') == symbol_name]
    if parent_symbol:
        filtered = [c for c in filtered if c.get('parent') == parent_symbol]
    if occurrence is not None:
        if occurrence < 1 or occurrence > len(filtered):
            raise FunctionCallValidationError(
                f'Occurrence {occurrence} is out of range for {symbol_name}; '
                f'{len(filtered)} candidate(s) found.'
            )
        filtered = [filtered[occurrence - 1]]
    return filtered


def _resolve_symbol_candidates(
    *,
    path: str,
    symbol_name: str,
    symbol_kind: str | None = None,
    parent_symbol: str | None = None,
    occurrence: int | None = None,
) -> tuple[Path, str, list[dict[str, Any]]]:
    safe_path = _safe_workspace_path(path, must_exist=True)
    content = _read_text_for_tool(safe_path)
    lookup_name = symbol_name
    if not parent_symbol and '.' in lookup_name:
        maybe_parent, _, maybe_name = lookup_name.rpartition('.')
        parent_symbol = maybe_parent or None
        lookup_name = maybe_name
    if parent_symbol and '.' not in lookup_name:
        lookup_name = f'{parent_symbol}.{lookup_name}'

    candidates = _find_symbol_candidates_in_file(
        safe_path,
        lookup_name.split('.')[-1],
        symbol_kind=symbol_kind,
        include_private=True,
    )
    if parent_symbol:
        candidates = [c for c in candidates if c.get('parent') == parent_symbol]
    candidates = [c for c in candidates if c.get('name') == lookup_name.split('.')[-1]]

    if occurrence is not None:
        if occurrence < 1 or occurrence > len(candidates):
            raise FunctionCallValidationError(
                f'Occurrence {occurrence} is out of range for {symbol_name}; '
                f'{len(candidates)} candidate(s) found.'
            )
        candidates = [candidates[occurrence - 1]]

    return safe_path, content, candidates


def _symbol_action_ambiguity_error(symbol_name: str, candidates: list[dict[str, Any]]) -> str:
    return (
        f"Symbol '{symbol_name}' is ambiguous. Use find_symbols or read(type=\"symbols\") output "
        f'to choose a parent_symbol or occurrence.\n'
        + json.dumps({'candidates': candidates}, indent=2)
    )


def _single_symbol_candidate(
    *,
    path: str,
    symbol_name: str,
    symbol_kind: str | None = None,
    parent_symbol: str | None = None,
    occurrence: int | None = None,
) -> tuple[Path, str, dict[str, Any]]:
    safe_path, content, candidates = _resolve_symbol_candidates(
        path=path,
        symbol_name=symbol_name,
        symbol_kind=symbol_kind,
        parent_symbol=parent_symbol,
        occurrence=occurrence,
    )
    if not candidates:
        raise FunctionCallValidationError(f"Symbol '{symbol_name}' not found in {path}.")
    if len(candidates) > 1:
        raise FunctionCallValidationError(
            _symbol_action_ambiguity_error(symbol_name, candidates)
        )
    return safe_path, content, candidates[0]


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
        _, message = tracker.update_task_status(task_id, status, result)
        full_plan = tracker.load_from_file()
        return TaskTrackingAction(
            command='update_status',
            task_list=full_plan,
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
    tool_name: str = 'edit_symbol',
) -> Action:
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
    action = _handle_read_file_command(
        str(path), {'view_range': [start_i, end_i], 'security_risk': arguments.get('security_risk')}
    )
    set_security_risk(action, arguments)
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


def _resolve_read_symbol_target(
    target: Mapping[str, Any],
    *,
    default_path: str | None,
    default_symbol_kind: str | None,
) -> dict[str, Any]:
    symbol_id = str(target.get('symbol_id') or '').strip()
    path = str(target.get('path') or default_path or '').strip()
    symbol_name = str(
        target.get('symbol_name')
        or target.get('name')
        or target.get('query')
        or ''
    ).strip()
    symbol_kind = cast(str | None, target.get('symbol_kind') or default_symbol_kind)
    parent_symbol = cast(str | None, target.get('parent_symbol'))
    occurrence = _coerce_optional_int(target.get('occurrence'), 'occurrence')
    requested_start: int | None = None
    requested_end: int | None = None

    if symbol_id:
        path, symbol_name, requested_start, requested_end = _parse_symbol_id(symbol_id)
        occurrence = None

    display_target = symbol_id or symbol_name
    if not symbol_name:
        return {
            'status': 'not_found',
            'target': display_target,
            'message': 'Symbol target requires symbol_id or symbol_name.',
        }

    if path:
        safe_path, content, candidates = _resolve_symbol_candidates(
            path=path,
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
        content = ''

    if requested_start is not None:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.get('start_line') == requested_start
            and candidate.get('end_line') == requested_end
        ]

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


def _coerce_read_symbol_targets(arguments: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw_symbols = arguments.get('symbols')
    if isinstance(raw_symbols, list):
        targets: list[Mapping[str, Any]] = []
        for index, raw in enumerate(raw_symbols):
            if isinstance(raw, str):
                if raw.strip():
                    targets.append({'symbol_name': raw.strip()})
                continue
            if isinstance(raw, Mapping):
                targets.append(raw)
                continue
            raise FunctionCallValidationError(
                f'read type=symbols symbols[{index}] must be a string or object.'
            )
        if targets:
            return targets

    symbol_id = str(arguments.get('symbol_id') or '').strip()
    symbol_name = str(arguments.get('symbol_name') or arguments.get('query') or '').strip()
    if symbol_id or symbol_name:
        return [
            {
                'symbol_id': symbol_id,
                'symbol_name': symbol_name,
                'path': arguments.get('path'),
                'symbol_kind': arguments.get('symbol_kind'),
                'parent_symbol': arguments.get('parent_symbol'),
                'occurrence': arguments.get('occurrence'),
            }
        ]
    raise FunctionCallValidationError(
        'read type=symbols requires symbols[], symbol_id, or symbol_name.'
    )


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
    validate_security_risk(arguments, FIND_SYMBOLS_TOOL_NAME)
    query = str(require_tool_argument(arguments, 'query', FIND_SYMBOLS_TOOL_NAME)).strip()
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
    validate_security_risk(arguments, READ_TOOL_NAME)
    read_type = str(require_tool_argument(arguments, 'type', READ_TOOL_NAME)).strip().lower()
    if read_type == 'file':
        path = require_tool_argument(arguments, 'path', READ_TOOL_NAME)
        action = _handle_read_file_command(str(path), {})
        set_security_risk(action, arguments)
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
            f"create type=symbol position must be one of {sorted(valid)}."
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
    target_symbol = str(require_tool_argument(arguments, 'target_symbol', CREATE_TOOL_NAME))
    content_to_insert = str(require_tool_argument(arguments, 'content', CREATE_TOOL_NAME))
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
        expected_file_hash=_sha256_text(content),
        impl_source=FileEditSource.FILE_EDITOR,
    )
    set_security_risk(action, arguments)
    return action


def _handle_create_tool(arguments: Mapping[str, Any]) -> Action:
    validate_security_risk(arguments, CREATE_TOOL_NAME)
    create_type = str(require_tool_argument(arguments, 'type', CREATE_TOOL_NAME)).strip().lower()
    normalized_args = dict(arguments)
    _guard_content_arguments(normalized_args)
    if create_type == 'file':
        path = require_tool_argument(arguments, 'path', CREATE_TOOL_NAME)
        content = require_tool_argument(arguments, 'content', CREATE_TOOL_NAME)
        safe_path = _safe_workspace_path(str(path), must_exist=False)
        if safe_path.exists():
            raise FunctionCallValidationError(
                'File already exists. Use edit_symbols or replace_string for modifications.'
            )
        normalized_args['file_text'] = str(content)
        normalized_args['overwrite_existing'] = False
        action = _handle_create_file_command(str(path), normalized_args)
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
        raise FunctionCallValidationError('replace_string old_string must not be empty.')
    _guard_content_arguments(dict(arguments))
    safe_path = _safe_workspace_path(path, must_exist=True)
    content = _read_text_for_tool(safe_path)
    action = FileEditAction(
        path=_relative_display_path(safe_path),
        command='replace_string',
        old_string=old_string,
        new_str=new_string,
        replace_all=parse_bool_argument(arguments.get('replace_all', False)),
        expected_file_hash=_sha256_text(content),
        impl_source=FileEditSource.FILE_EDITOR,
    )
    set_security_risk(action, arguments)
    return action


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
    symbol_name = str(item.get('symbol_name') or '').strip()
    symbol_kind = cast(str | None, item.get('symbol_kind'))
    parent_symbol = cast(str | None, item.get('parent_symbol'))
    occurrence = _coerce_optional_int(item.get('occurrence'), f'edits[{index}].occurrence')
    requested_start: int | None = None
    requested_end: int | None = None

    if symbol_id:
        raw_path, symbol_name, requested_start, requested_end = _parse_symbol_id(symbol_id)
        occurrence = None

    if not symbol_name:
        raise FunctionCallValidationError(
            f'edit_symbols edits[{index}] requires symbol_id or symbol_name.'
        )

    if raw_path:
        safe_path, _content, candidates = _resolve_symbol_candidates(
            path=raw_path,
            symbol_name=symbol_name,
            symbol_kind=symbol_kind,
            parent_symbol=parent_symbol,
            occurrence=occurrence,
        )
    else:
        candidates = _filter_symbol_candidates(
            _find_symbol_candidates(
                symbol_name,
                symbol_kind=symbol_kind,
                include_private=True,
            ),
            symbol_name=symbol_name,
            parent_symbol=parent_symbol,
            occurrence=occurrence,
        )
        safe_path = Path()

    if requested_start is not None:
        candidates = [
            candidate
            for candidate in candidates
            if candidate.get('start_line') == requested_start
            and candidate.get('end_line') == requested_end
        ]

    if not candidates:
        target = symbol_id or symbol_name
        raise FunctionCallValidationError(
            f"edit_symbols edits[{index}] could not find symbol {target!r}."
        )
    if len(candidates) > 1:
        raise FunctionCallValidationError(
            _symbol_action_ambiguity_error(symbol_name, candidates)
        )

    candidate = candidates[0]
    if not raw_path:
        safe_path = _safe_workspace_path(str(candidate['path']), must_exist=True)
    return {
        'path': _relative_display_path(safe_path),
        'command': 'replace_range',
        'start_line': int(candidate['start_line']),
        'end_line': int(candidate['end_line']),
        'new_code': new_content,
    }


def _normalize_edit_symbols_public_edits(
    edits: object,
    *,
    default_path: str | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(edits, list) or not edits:
        raise FunctionCallValidationError('edit_symbols requires a non-empty edits array.')
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(edits):
        if not isinstance(item, Mapping):
            raise FunctionCallValidationError(f'edit_symbols edits[{index}] must be an object.')
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


def _normalize_multiedit_operations(arguments: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_ops = arguments.get('operations')
    if not isinstance(raw_ops, list) or not raw_ops:
        raise FunctionCallValidationError('multiedit requires a non-empty operations array.')
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_ops):
        if not isinstance(raw, Mapping):
            raise FunctionCallValidationError(f'multiedit operations[{index}] must be an object.')
        command = str(raw.get('command') or '').strip().lower()
        path = raw.get('path')
        if command == 'create':
            create_type = str(raw.get('type') or '').strip().lower()
            if not isinstance(path, str) or not path.strip():
                raise FunctionCallValidationError(f'multiedit operations[{index}] create requires path.')
            content = raw.get('content')
            if not isinstance(content, str):
                raise FunctionCallValidationError(
                    f'multiedit operations[{index}] create requires content.'
                )
            if create_type == 'file':
                normalized.append({'path': path, 'command': 'create_file', 'content': content})
            elif create_type == 'symbol':
                target_symbol = raw.get('target_symbol')
                if not isinstance(target_symbol, str) or not target_symbol.strip():
                    raise FunctionCallValidationError(
                        f'multiedit operations[{index}] create type=symbol requires target_symbol.'
                    )
                normalized.append(
                    {
                        'path': path,
                        'command': 'create_symbol',
                        'target_symbol': target_symbol,
                        'target_kind': raw.get('target_kind'),
                        'parent_symbol': raw.get('parent_symbol'),
                        'occurrence': raw.get('occurrence'),
                        'position': _coerce_insert_position(raw.get('position')),
                        'content': content,
                    }
                )
            else:
                raise FunctionCallValidationError(
                    f"multiedit operations[{index}] create type must be 'file' or 'symbol'."
                )
        elif command == 'replace_string':
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
            normalized.append(
                {
                    'path': path,
                    'command': 'replace_string',
                    'old_string': old_string,
                    'new_string': new_string,
                    'replace_all': parse_bool_argument(raw.get('replace_all', False)),
                }
            )
        elif command == 'edit_symbols':
            raw_edits = raw.get('edits')
            if raw_edits is None:
                raw_edits = [
                    {
                        'symbol_id': raw.get('symbol_id'),
                        'path': raw.get('path'),
                        'symbol_name': raw.get('symbol_name'),
                        'symbol_kind': raw.get('symbol_kind'),
                        'parent_symbol': raw.get('parent_symbol'),
                        'occurrence': raw.get('occurrence'),
                        'new_content': raw.get('new_content'),
                    }
                ]
            normalized.extend(
                _normalize_edit_symbols_public_edits(
                    raw_edits,
                    default_path=str(path).strip() if isinstance(path, str) else None,
                )
            )
        else:
            raise FunctionCallValidationError(
                f"multiedit operations[{index}] command {command!r} is unsupported. "
                "Use create, replace_string, or edit_symbols."
            )
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
                "Use create_file, create_symbol, replace_string, replace_symbol, "
                "replace_file, replace_range, or edit_symbol."
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
    if item_command == 'create_file':
        content = item.get('content', item.get('file_text'))
        if not isinstance(content, str):
            raise FunctionCallValidationError(
                "multi_edit create_file requires 'content' (string)."
            )
        result = temp_editor(command='create_file', path=rel_path, file_text=content)
        if result.error:
            _multi_edit_raise(
                f'❌ multi_edit create_file failed for {rel_path}: {result.error}',
                path=rel_path,
            )
        return

    if item_command == 'replace_string':
        old_string = item.get('old_string')
        new_string = item.get('new_string')
        if not isinstance(old_string, str) or not isinstance(new_string, str):
            raise FunctionCallValidationError(
                "multi_edit replace_string requires 'old_string' and 'new_string'."
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

    if item_command == 'create_symbol':
        target_symbol = item.get('target_symbol')
        content = item.get('content')
        if not isinstance(target_symbol, str) or not isinstance(content, str):
            raise FunctionCallValidationError(
                "multi_edit create_symbol requires 'target_symbol' and 'content'."
            )
        candidates = _find_symbol_candidates_in_file(
            temp_path,
            target_symbol,
            symbol_kind=cast(str | None, item.get('target_kind')),
            include_private=True,
        )
        candidates = [c for c in candidates if c.get('name') == target_symbol]
        parent_symbol = item.get('parent_symbol')
        if isinstance(parent_symbol, str) and parent_symbol.strip():
            candidates = [
                c for c in candidates if c.get('parent') == parent_symbol.strip()
            ]
        occurrence = _coerce_optional_int(item.get('occurrence'), 'occurrence')
        if occurrence is not None:
            if occurrence < 1 or occurrence > len(candidates):
                raise FunctionCallValidationError(
                    f'Occurrence {occurrence} is out of range for {target_symbol}; '
                    f'{len(candidates)} candidate(s) found.'
                )
            candidates = [candidates[occurrence - 1]]
        if not candidates:
            raise FunctionCallValidationError(
                f"multi_edit create_symbol could not find target symbol {target_symbol!r} in {rel_path}."
            )
        if len(candidates) > 1:
            raise FunctionCallValidationError(
                _symbol_action_ambiguity_error(target_symbol, candidates)
            )
        position = _coerce_insert_position(item.get('position'))
        result = temp_editor(
            command='insert_text',
            path=rel_path,
            insert_line=_insert_line_for_symbol(candidates[0], position),
            new_str=content,
        )
        if result.error:
            _multi_edit_raise(
                f'❌ multi_edit create_symbol failed for {rel_path}: {result.error}',
                path=rel_path,
            )
        return

    if item_command == 'replace_symbol':
        symbol_name = item.get('symbol_name')
        new_content = item.get('new_content')
        if not isinstance(symbol_name, str) or not isinstance(new_content, str):
            raise FunctionCallValidationError(
                "multi_edit replace_symbol requires 'symbol_name' and 'new_content'."
            )
        candidates = _find_symbol_candidates_in_file(
            temp_path,
            symbol_name,
            symbol_kind=cast(str | None, item.get('symbol_kind')),
            include_private=True,
        )
        candidates = [c for c in candidates if c.get('name') == symbol_name]
        parent_symbol = item.get('parent_symbol')
        if isinstance(parent_symbol, str) and parent_symbol.strip():
            candidates = [
                c for c in candidates if c.get('parent') == parent_symbol.strip()
            ]
        occurrence = _coerce_optional_int(item.get('occurrence'), 'occurrence')
        if occurrence is not None:
            if occurrence < 1 or occurrence > len(candidates):
                raise FunctionCallValidationError(
                    f'Occurrence {occurrence} is out of range for {symbol_name}; '
                    f'{len(candidates)} candidate(s) found.'
                )
            candidates = [candidates[occurrence - 1]]
        if not candidates:
            raise FunctionCallValidationError(
                f"multi_edit replace_symbol could not find symbol {symbol_name!r} in {rel_path}."
            )
        if len(candidates) > 1:
            raise FunctionCallValidationError(
                _symbol_action_ambiguity_error(symbol_name, candidates)
            )
        candidate = candidates[0]
        result = temp_editor(
            command='edit',
            path=rel_path,
            edit_mode='range',
            start_line=int(candidate['start_line']),
            end_line=int(candidate['end_line']),
            new_str=new_content,
        )
        if result.error:
            _multi_edit_raise(
                f'❌ multi_edit replace_symbol failed for {rel_path}: {result.error}',
                path=rel_path,
            )
        return

    if item_command == 'replace_file':
        new_content = item.get('new_content')
        if not isinstance(new_content, str):
            raise FunctionCallValidationError(
                "multi_edit replace_file requires 'new_content' (string)."
            )
        result = temp_editor(command='write', path=rel_path, file_text=new_content)
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
        "Use create_file, create_symbol, replace_string, replace_symbol, "
        "replace_file, replace_range, or edit_symbol."
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
    _guard_content_arguments({'file_edits': raw_edits})
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
        BROWSER_TOOL_NAME: _handle_browser_tool,
    }


def response_to_actions(
    response: ModelResponse,
    mcp_tool_names: list[str] | None = None,
    mcp_tools: dict[str, Any] | None = None,
) -> list[Action]:
    """Convert LLM response to agent actions.

    Normal tools use provider-native tool calls.
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
            'The legacy file_editor tool has been removed. Use read, create, '
            'replace_string, edit_symbols, or multiedit.'
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
