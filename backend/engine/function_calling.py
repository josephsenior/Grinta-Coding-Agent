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
from backend.core.interaction_modes import (
    PLAN_MODE,
    PLAN_MODE_ALLOWED_TOOLS,
    normalize_interaction_mode,
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
    create_finish_tool,
    create_multiedit_tool,
    create_read_tool,
    create_replace_string_tool,
    create_summarize_context_tool,
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


_FINISH_STATUSES = {'completed', 'blocked', 'failed'}


def _finish_tool_name(mode: str = 'agent') -> str:
    return cast(str, create_finish_tool(mode).get('function', {}).get('name', ''))


def _require_finish_string(
    arguments: Mapping[str, Any],
    field: str,
    tool_name: str,
) -> str:
    value = require_tool_argument(arguments, field, tool_name)
    if not isinstance(value, str) or not value.strip():
        raise FunctionCallValidationError(
            f'Missing required non-empty string argument "{field}" for tool call {tool_name}'
        )
    return value.strip()


def _require_finish_list(
    arguments: Mapping[str, Any],
    field: str,
    tool_name: str,
) -> list[Any]:
    value = require_tool_argument(arguments, field, tool_name)
    if not isinstance(value, list):
        raise FunctionCallValidationError(
            f'Argument "{field}" for tool call {tool_name} must be a list.'
        )
    return value


def _require_finish_dict(
    arguments: Mapping[str, Any],
    field: str,
    tool_name: str,
) -> dict[str, Any]:
    value = require_tool_argument(arguments, field, tool_name)
    if not isinstance(value, Mapping):
        raise FunctionCallValidationError(
            f'Argument "{field}" for tool call {tool_name} must be an object.'
        )
    return dict(value)


def _require_finish_status(arguments: Mapping[str, Any], tool_name: str) -> str:
    status = _require_finish_string(arguments, 'status', tool_name).lower()
    if status not in _FINISH_STATUSES:
        allowed = ', '.join(sorted(_FINISH_STATUSES))
        raise FunctionCallValidationError(
            f'Invalid finish status {status!r}; expected one of: {allowed}.'
        )
    return status


def _handle_plan_finish_tool(arguments: Mapping[str, Any]) -> PlaybookFinishAction:
    tool_name = _finish_tool_name(PLAN_MODE)
    status = _require_finish_status(arguments, tool_name)
    summary = _require_finish_string(arguments, 'summary', tool_name)
    plan = _require_finish_list(arguments, 'plan', tool_name)
    assumptions = _require_finish_list(arguments, 'assumptions', tool_name)
    next_step = _require_finish_string(arguments, 'next_step', tool_name)

    if status == 'completed' and not any(str(step).strip() for step in plan):
        raise FunctionCallValidationError(
            'Plan Mode finish with status="completed" requires a non-empty plan.'
        )

    outputs = {
        'status': status,
        'summary': summary,
        'plan': plan,
        'assumptions': assumptions,
        'next_step': next_step,
    }
    return PlaybookFinishAction(final_thought=summary, outputs=outputs)


def _handle_agent_finish_tool(arguments: Mapping[str, Any]) -> PlaybookFinishAction:
    tool_name = _finish_tool_name('agent')
    status = _require_finish_status(arguments, tool_name)
    summary = _require_finish_string(arguments, 'summary', tool_name)
    actions_taken = _require_finish_list(arguments, 'actions_taken', tool_name)
    verification = _require_finish_dict(arguments, 'verification', tool_name)
    remaining_items = _require_finish_list(arguments, 'remaining_items', tool_name)
    next_step = _require_finish_string(arguments, 'next_step', tool_name)

    verification_status = str(verification.get('status') or '').strip()
    verification_details = str(verification.get('details') or '').strip()
    if not verification_status or not verification_details:
        raise FunctionCallValidationError(
            'Agent Mode finish verification requires non-empty status and details.'
        )
    if status == 'completed' and not any(str(item).strip() for item in actions_taken):
        raise FunctionCallValidationError(
            'Agent Mode finish with status="completed" requires non-empty actions_taken.'
        )

    outputs: dict[str, Any] = {
        'status': status,
        'summary': summary,
        'actions_taken': actions_taken,
        'verification': verification,
        'remaining_items': remaining_items,
        'next_step': next_step,
    }

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
    return PlaybookFinishAction(final_thought=summary, outputs=outputs)


def _handle_finish_tool(
    arguments: Mapping[str, Any],
    mode: str = 'agent',
) -> PlaybookFinishAction:
    """Handle the mode-aware finish tool call."""
    if normalize_interaction_mode(mode) == PLAN_MODE:
        return _handle_plan_finish_tool(arguments)
    return _handle_agent_finish_tool(arguments)


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


def _candidate_from_location(
    location: Any, content: str, display_path: str
) -> dict[str, Any]:
    name = str(getattr(location, 'symbol_name', '') or '')
    parent = getattr(location, 'parent_name', None)
    start_line = int(getattr(location, 'line_start', 0) or 0)
    end_line = int(getattr(location, 'line_end', 0) or 0)
    kind = getattr(location, 'node_type', None)
    symbol_kind = str(getattr(location, 'symbol_kind', '') or '') or _node_kind(
        str(kind or '')
    )
    qualified_name = f'{parent}.{name}' if parent else name
    preview = _symbol_preview(content, start_line, end_line)
    return {
        'symbol_id': _symbol_id(display_path, name, start_line, end_line),
        'name': name,
        'qualified_name': qualified_name,
        'kind': kind,
        'symbol_kind': symbol_kind,
        'parent': parent,
        'path': display_path,
        'start_line': start_line,
        'end_line': end_line,
        'signature': preview,
        'preview': preview,
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
                base_kind = _node_kind(str(node.type))
                kind = (
                    'method' if parent_name and base_kind == 'function' else base_kind
                )
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
                            'symbol_kind': kind,
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
    lookup_query = query.rsplit('.', 1)[-1]
    candidates: list[dict[str, Any]] = []
    for candidate_path in _candidate_paths_for_symbol_search(path):
        candidates.extend(
            _find_symbol_candidates_in_file(
                candidate_path,
                lookup_query,
                symbol_kind=symbol_kind,
                include_private=include_private,
            )
        )
    if '.' in query:
        query_lower = query.lower()
        candidates = [
            candidate
            for candidate in candidates
            if query_lower in str(candidate.get('qualified_name') or '').lower()
        ]
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
    filtered = [
        c
        for c in candidates
        if c.get('name') == symbol_name or c.get('qualified_name') == symbol_name
    ]
    if parent_symbol:
        filtered = [
            c
            for c in filtered
            if c.get('parent') == parent_symbol
            or str(c.get('qualified_name') or '').startswith(f'{parent_symbol}.')
        ]
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

    candidates = _find_symbol_candidates_in_file(
        safe_path,
        lookup_name.split('.')[-1],
        symbol_kind=symbol_kind,
        include_private=True,
    )
    candidates = _filter_symbol_candidates(
        candidates,
        symbol_name=lookup_name.split('.')[-1],
        parent_symbol=parent_symbol,
    )

    if occurrence is not None:
        if occurrence < 1 or occurrence > len(candidates):
            raise FunctionCallValidationError(
                f'Occurrence {occurrence} is out of range for {symbol_name}; '
                f'{len(candidates)} candidate(s) found.'
            )
        candidates = [candidates[occurrence - 1]]

    return safe_path, content, candidates


def _symbol_action_ambiguity_error(
    symbol_name: str, candidates: list[dict[str, Any]]
) -> str:
    return (
        f'Symbol \'{symbol_name}\' is ambiguous. Use find_symbols or read(type="symbols") output '
        f'to retry with path, qualified_name, and symbol_kind.\n'
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
        raise FunctionCallValidationError(
            f"Symbol '{symbol_name}' not found in {path}."
        )
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
            'security_risk': arguments.get('security_risk'),
        },
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
        target.get('qualified_name')
        or target.get('symbol_name')
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
            'message': 'Symbol target requires qualified_name, symbol_name, or symbol_id.',
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


def _coerce_read_symbol_targets(
    arguments: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    raw_symbols = arguments.get('symbols')
    if isinstance(raw_symbols, list):
        targets: list[Mapping[str, Any]] = []
        for index, raw in enumerate(raw_symbols):
            if isinstance(raw, str):
                if raw.strip():
                    targets.append({'qualified_name': raw.strip()})
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
    qualified_name = str(arguments.get('qualified_name') or '').strip()
    symbol_name = str(
        arguments.get('symbol_name') or arguments.get('query') or ''
    ).strip()
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
    validate_security_risk(arguments, READ_TOOL_NAME)
    read_type = (
        str(require_tool_argument(arguments, 'type', READ_TOOL_NAME)).strip().lower()
    )
    if read_type == 'file':
        path = require_tool_argument(arguments, 'path', READ_TOOL_NAME)
        action = _build_read_file_action(str(path), {})
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
        expected_file_hash=_sha256_text(content),
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
        safe_path = _safe_workspace_path(str(path), must_exist=False)
        if safe_path.exists():
            raise FunctionCallValidationError(
                'File already exists. Use edit_symbols or replace_string for modifications.'
            )
        normalized_args['file_text'] = str(content)
        normalized_args['overwrite_existing'] = False
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
        raw_path, symbol_name, requested_start, requested_end = _parse_symbol_id(
            symbol_id
        )
        occurrence = None

    if not symbol_name:
        raise FunctionCallValidationError(
            f'edit_symbols edits[{index}] requires qualified_name, symbol_name, or symbol_id.'
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
            f'edit_symbols edits[{index}] could not find symbol {target!r}.'
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
        command = str(raw.get('command') or '').strip().lower()
        path = raw.get('path')
        if command == 'create':
            create_type = str(raw.get('type') or '').strip().lower()
            if not isinstance(path, str) or not path.strip():
                raise FunctionCallValidationError(
                    f'multiedit operations[{index}] create requires path.'
                )
            content = raw.get('content')
            if not isinstance(content, str):
                raise FunctionCallValidationError(
                    f'multiedit operations[{index}] create requires content.'
                )
            if create_type == 'file':
                normalized.append(
                    {'path': path, 'operation': 'create_file', 'content': content}
                )
            elif create_type == 'symbol':
                target_symbol = raw.get('target_symbol')
                if not isinstance(target_symbol, str) or not target_symbol.strip():
                    raise FunctionCallValidationError(
                        f'multiedit operations[{index}] create type=symbol requires target_symbol.'
                    )
                normalized.append(
                    {
                        'path': path,
                        'operation': 'create_symbol',
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
                    'operation': 'replace_string',
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
                        'qualified_name': raw.get('qualified_name'),
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
                f'multiedit operations[{index}] command {command!r} is unsupported. '
                'Use create, replace_string, or edit_symbols.'
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
    operation = str(raw_item.get('operation') or '').strip().lower()
    allowed = {
        'create_file',
        'create_symbol',
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
    if operation == 'create_file':
        content = item.get('content')
        if not isinstance(content, str):
            raise FunctionCallValidationError(
                "multi_edit create_file operation requires 'content' (string)."
            )
        result = temp_editor(command='create_file', path=rel_path, file_text=content)
        if result.error:
            _multi_edit_raise(
                f'❌ multi_edit create_file failed for {rel_path}: {result.error}',
                path=rel_path,
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
            _multi_edit_raise(
                f'❌ multi_edit replace_string failed for {rel_path}: {result.error}',
                path=rel_path,
            )
        return

    if operation == 'create_symbol':
        target_symbol = item.get('target_symbol')
        content = item.get('content')
        if not isinstance(target_symbol, str) or not isinstance(content, str):
            raise FunctionCallValidationError(
                "multi_edit create_symbol operation requires 'target_symbol' and 'content'."
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
                f'multi_edit create_symbol could not find target symbol {target_symbol!r} in {rel_path}.'
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


def _handle_multi_edit_command(_path: str, arguments: Mapping[str, Any]) -> Action:
    """Apply an atomic multi-file batch edit via :class:`AtomicRefactor`.

    All edits commit together or all are rolled back from per-file backups.
    Side effects run synchronously inside this handler (same pattern as
    ``edit_symbols``); the returned ``MessageAction`` summarizes the outcome.
    """
    raw_edits = arguments.get('file_edits')
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
        original_snapshots: dict[str, str | None] = {}
        final_contents: dict[str, str] = {}
        with ExitStack() as stack:
            for item_path in sorted(seen_paths):
                stack.enter_context(_file_lock_for_path(Path(item_path)))
            with tempfile.TemporaryDirectory(
                prefix='grinta-multi-edit-'
            ) as temp_root_str:
                temp_root = Path(temp_root_str)
                temp_editor = FileEditor(workspace_root=str(temp_root))
                temp_paths: dict[str, Path] = {}

                for item_path, _display_path, operation, item in parsed:
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

            for item_path, final_content in final_contents.items():
                operation = 'modify' if Path(item_path).exists() else 'create'
                refactor.add_file_edit(
                    transaction, item_path, final_content, operation=operation
                )
            result = refactor.commit(transaction, validate=False)
    except FunctionCallValidationError:
        raise
    except Exception as e:
        # Best-effort rollback if commit raised before completion.
        try:
            refactor.rollback(transaction)
        except Exception:
            pass
        _multi_edit_raise(
            f'❌ multi_edit failed before commit: {e}. No files modified.'
        )

    if result.success:
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
    err_lines = '\n'.join(f'  - {e}' for e in (result.errors or [result.message]))
    _multi_edit_raise(
        f'❌ multi_edit transaction rolled back — no files modified.\n{err_lines}'
    )


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
    mcp_tool_names = cast(list[str] | None, getattr(tool_call, '_mcp_tool_names', None))

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
