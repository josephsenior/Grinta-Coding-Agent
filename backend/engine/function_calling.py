"""This file contains the function calling implementation for different actions.

This is similar to the functionality of `OrchestratorResponseParser`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from backend.core.constants import NOTE_TOOL_NAME, RECALL_TOOL_NAME
from backend.core.enums import FileEditSource, FileReadSource
from backend.core.errors import (
    FunctionCallNotExistsError,
    FunctionCallValidationError,
)
from backend.core.logger import app_logger as logger
from backend.core.type_safety.path_validation import PathValidationError, SafePath
from backend.engine.common import (
    common_response_to_actions,
)
from backend.engine.tools import (
    create_cmd_run_tool,
    create_finish_tool,
    create_llm_based_edit_tool,
    create_str_replace_editor_tool,
    create_structure_editor_tool,
    create_summarize_context_tool,
    create_think_tool,
)
from backend.engine.tools.analyze_project_structure import (
    ANALYZE_PROJECT_STRUCTURE_TOOL_NAME,
    build_analyze_project_structure_action,
)
from backend.engine.tools.blackboard import (
    BLACKBOARD_TOOL_NAME,
    build_blackboard_action,
)
from backend.engine.tools.checkpoint import (
    CHECKPOINT_TOOL_NAME,
    build_checkpoint_action,
)
from backend.engine.tools.delegate_task import (
    DELEGATE_TASK_TOOL_NAME,
    build_delegate_task_action,
)
from backend.engine.tools.execute_mcp_tool import EXECUTE_MCP_TOOL_TOOL_NAME
from backend.engine.tools.explore_code import (
    build_explore_tree_structure_action,
    build_read_symbol_definition_action,
)
from backend.engine.tools.lsp_query import (
    CODE_INTELLIGENCE_TOOL_NAME,
    build_lsp_query_action,
)
from backend.engine.tools.memory_manager import (
    MEMORY_MANAGER_TOOL_NAME,
)
from backend.engine.tools.meta_cognition import COMMUNICATE_TOOL_NAME
from backend.engine.tools.note import build_note_action, build_recall_action
from backend.engine.tools.prompt import build_python_exec_command
from backend.engine.tools.revert_to_checkpoint import (
    REVERT_TO_CHECKPOINT_TOOL_NAME,
    build_revert_to_checkpoint_action,
)
from backend.engine.tools.search_code import (
    SEARCH_CODE_TOOL_NAME,
    build_search_code_action,
)
from backend.engine.tools.security_utils import RISK_LEVELS
from backend.engine.tools.session_diff import (
    SESSION_DIFF_TOOL_NAME,
    build_session_diff_action,
)
from backend.engine.tools.signal_progress import (
    SIGNAL_PROGRESS_TOOL_NAME,
    build_signal_progress_action,
)
from backend.engine.tools.task_tracker import TaskTracker
from backend.engine.tools.terminal_manager import (
    TERMINAL_MANAGER_TOOL_NAME,
    handle_terminal_manager_tool,
)
from backend.engine.tools.verify_file_lines import (
    VERIFY_FILE_LINES_TOOL_NAME,
    build_verify_file_lines_action,
)
from backend.engine.tools.verify_ui import (
    VERIFY_UI_CHANGE_TOOL_NAME,
    build_verify_ui_change_action,
)
from backend.engine.tools.whitespace_handler import WhitespaceHandler
from backend.inference.tool_names import TASK_TRACKER_TOOL_NAME
from backend.ledger.action import (
    Action,
    ActionSecurityRisk,
    AgentThinkAction,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    MessageAction,
    PlaybookFinishAction,
    TaskTrackingAction,
)
from backend.ledger.action.agent import CondensationRequestAction
from backend.ledger.action.mcp import MCPAction
from backend.ledger.tool import build_tool_call_metadata

ToolHandler = Callable[[dict[str, Any]], Action]

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
    if not hasattr(action, 'thought'):
        return action
    if thought:
        action.thought = f'{thought}\n{action.thought}' if action.thought else thought
    return action


def set_security_risk(action: Action, arguments: dict) -> None:
    """Set the security risk level for the action."""
    if 'security_risk' in arguments:
        if arguments['security_risk'] in RISK_LEVELS:
            if hasattr(action, 'security_risk'):
                action.security_risk = getattr(
                    ActionSecurityRisk, arguments['security_risk']
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


def _handle_cmd_run_tool(arguments: dict) -> CmdRunAction:
    """Handle CmdRunTool (Bash) tool call."""
    from backend.engine.tools.bash import (
        windows_drive_glued_hint,
        windows_drive_glued_in_command,
    )

    tool_name = create_cmd_run_tool()['function']['name']
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
        truncation_strategy=arguments.get('truncation_strategy'),
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


def _handle_finish_tool(arguments: dict) -> PlaybookFinishAction:
    """Handle FinishTool tool call."""
    tool_name = create_finish_tool()['function']['name']
    message = _require_tool_argument(arguments, 'message', tool_name)
    outputs: dict = {}
    if 'completed' in arguments:
        outputs['completed'] = arguments['completed']
    if 'blocked_by' in arguments:
        outputs['blocked_by'] = arguments['blocked_by']
    if 'next_steps' in arguments:
        outputs['next_steps'] = arguments['next_steps']
    if 'lessons_learned' in arguments:
        outputs['lessons_learned'] = arguments['lessons_learned']
    return PlaybookFinishAction(final_thought=message, outputs=outputs)


def _handle_memory_manager_tool(arguments: dict) -> AgentThinkAction:
    """Handle unified memory ops: note, recall, semantic_recall, working_memory."""
    action = arguments.get('action')
    if not action:
        raise FunctionCallValidationError("Missing 'action' in memory_manager tool.")

    if action == 'semantic_recall':
        query = arguments.get('key', '')
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
        from backend.engine.tools.working_memory import build_working_memory_action

        # Map arguments back to what build_working_memory_action expects
        wm_args = {
            'command': arguments.get('update_type', 'get'),
            'section': arguments.get('section', 'all'),
            'content': arguments.get('content', ''),
        }
        return build_working_memory_action(wm_args)

    else:
        raise FunctionCallValidationError(f'Unknown memory_manager action: {action}')


def _handle_search_code_tool(arguments: dict) -> AgentThinkAction:
    """Handle SEARCH_CODE_TOOL: fast code search via ripgrep/grep."""
    return build_search_code_action(
        pattern=arguments.get('pattern', ''),
        path=arguments.get('path', '.'),
        file_pattern=arguments.get('file_pattern', ''),
        context_lines=arguments.get('context_lines', 2),
        case_sensitive=arguments.get('case_sensitive', 'false'),
        max_results=arguments.get('max_results', 50),
    )


def _handle_checkpoint_tool(arguments: dict) -> AgentThinkAction:
    """Handle checkpoint tool: save/view progress checkpoints."""
    return build_checkpoint_action(arguments)


def _handle_analyze_project_structure_tool(
    arguments: dict,
) -> AgentThinkAction:
    """Handle analyze_project_structure tool: structural overview of the workspace."""
    return build_analyze_project_structure_action(arguments)


def _handle_session_diff_tool(arguments: dict) -> CmdRunAction:
    """Handle session_diff tool: show cumulative changes in the session."""
    return build_session_diff_action(arguments)


def _handle_verify_file_lines_tool(arguments: dict) -> AgentThinkAction:
    """Handle verify_file_lines tool: validate file assertions before editing."""
    return build_verify_file_lines_action(arguments)


def _handle_llm_based_file_edit_tool(arguments: dict) -> FileEditAction:
    """Handle LLMBasedFileEditTool tool call."""
    tool_name = create_llm_based_edit_tool()['function']['name']
    if 'path' not in arguments:
        msg = f'Missing required argument "path" in tool call {tool_name}'
        raise FunctionCallValidationError(
            msg,
        )
    if 'content' not in arguments:
        msg = f'Missing required argument "content" in tool call {tool_name}'
        raise FunctionCallValidationError(
            msg,
        )
    action = FileEditAction(
        path=arguments['path'],
        content=arguments['content'],
        start=arguments.get('start', 1),
        end=arguments.get('end', -1),
        impl_source=arguments.get('impl_source', FileEditSource.LLM_BASED_EDIT),
    )
    set_security_risk(action, arguments)
    return action


def _validate_str_replace_editor_args(arguments: dict) -> tuple[str, str]:
    """Validate required arguments for str_replace_editor tool."""
    tool_name = create_str_replace_editor_tool()['function']['name']
    command = _require_tool_argument(arguments, 'command', tool_name)
    path = arguments.get('path')
    if not path:
        msg = f'Missing required argument "path" in tool call {tool_name}'
        raise FunctionCallValidationError(msg)
    return str(path), str(command)


def _normalize_file_editor_command_and_args(
    command: str,
    arguments: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Normalize canonical file editor arguments.

    Canonical-only mode: no legacy command or field aliases are accepted.
    """
    normalized_command = str(command or '').strip().lower()
    normalized_args: dict[str, Any] = dict(arguments)
    return normalized_command, normalized_args


def _filter_valid_editor_kwargs(other_kwargs: dict) -> dict:
    """Filter and validate kwargs for file editor."""
    str_replace_editor_tool = create_str_replace_editor_tool()
    valid_params = set(
        str_replace_editor_tool['function']['parameters']['properties'].keys()
    )
    valid_kwargs_for_editor = {}
    tool_name = str_replace_editor_tool['function']['name']

    for key, value in other_kwargs.items():
        if key not in valid_params:
            msg = f'Unexpected argument {key} in tool call {tool_name}. Allowed arguments are: {valid_params}'
            raise FunctionCallValidationError(
                msg,
            )
        if key != 'security_risk':
            valid_kwargs_for_editor[key] = value
    return valid_kwargs_for_editor


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace for fuzzy matching: strip trailing spaces and unify indent chars."""
    return WhitespaceHandler.normalize_for_match(text)


def _ws_tolerant_replace(
    file_content: str, old_str: str, new_str: str
) -> tuple[str | None, str | None]:
    """Try whitespace-normalized matching to find and replace old_str in file_content.

    Returns (new_content, None) on success, or (None, error_message) on failure.
    """
    norm_content = _normalize_whitespace(file_content)
    norm_old = _normalize_whitespace(old_str)

    count = norm_content.count(norm_old)
    if count == 0:
        return None, 'No match found even with whitespace normalization.'
    if count > 1:
        return (
            None,
            f'Whitespace-normalized old_str matches {count} locations — must be unique.',
        )

    norm_start = norm_content.index(norm_old)
    norm_end = norm_start + len(norm_old)

    orig_start = _map_normalized_offset_to_original(file_content, norm_start)
    orig_end = _map_normalized_offset_to_original(file_content, norm_end)

    new_content = file_content[:orig_start] + new_str + file_content[orig_end:]
    return new_content, None


def _map_normalized_offset_to_original(original: str, norm_offset: int) -> int:
    """Map a character offset in normalized text back to the original text."""
    return WhitespaceHandler.map_normalized_offset_to_original(original, norm_offset)


def _extract_view_replace_params(kwargs: dict) -> tuple[str, str, Any]:
    """Extract old_str, new_str, and view_range from kwargs."""
    old_str = kwargs.get('old_str', '')
    new_str = kwargs.get('new_str', '')
    view_range = kwargs.get('view_range')
    return old_str, new_str, view_range


def _get_search_content_by_range(content: str, view_range: Any) -> str:
    """Slice content to the given line range. Returns full content if range invalid."""
    if not view_range or len(view_range) < 2:
        return content
    lines = content.splitlines(keepends=True)
    start_val = view_range[0] if view_range[0] is not None else 1
    end_val = view_range[1]
    try:
        start_idx = max(0, int(start_val) - 1)
        end_idx = len(lines) if end_val in (-1, None) else min(len(lines), int(end_val))
    except (TypeError, ValueError):
        start_idx, end_idx = 0, len(lines)
    return ''.join(lines[start_idx:end_idx])


def _old_str_not_found_action(path: str, view_range: Any) -> AgentThinkAction:
    """Build AgentThinkAction for 'old_str not found' error."""
    range_suffix = ''
    if (
        view_range
        and len(view_range) >= 2
        and view_range[0] is not None
        and view_range[1] is not None
    ):
        range_suffix = f' (within lines {view_range[0]}-{view_range[1]})'
    return AgentThinkAction(
        thought=f'[VIEW_AND_REPLACE] old_str not found in {path}{range_suffix}. '
        'Use view_file command to check the actual content.'
    )


def _handle_view_and_replace(path: str, kwargs: dict) -> list[Action]:
    """Handle the compound view_and_replace command.

    Returns a list of actions: first a FileReadAction (view_file), then a FileEditAction (replace_text).
    If old_str/new_str are provided, performs the replacement; otherwise just views.
    """
    import os

    old_str, new_str, view_range = _extract_view_replace_params(kwargs)

    if not os.path.isfile(path):
        return [AgentThinkAction(thought=f'[VIEW_AND_REPLACE] File not found: {path}')]

    if not old_str:
        return [
            FileReadAction(
                path=path,
                impl_source=FileReadSource.FILE_EDITOR,
                view_range=view_range,
            )
        ]

    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            content = f.read()
    except OSError as exc:
        return [
            AgentThinkAction(thought=f'[VIEW_AND_REPLACE] Cannot read {path}: {exc}')
        ]

    search_content = _get_search_content_by_range(content, view_range)

    if old_str not in search_content:
        _, err = _ws_tolerant_replace(search_content, old_str, new_str)
        if err:
            return [
                AgentThinkAction(
                    thought=f'[VIEW_AND_REPLACE] {err} Use view_file command to check the actual content.'
                )
            ]

    edit_kwargs: dict = {'old_str': old_str, 'new_str': new_str}

    return [
        FileReadAction(
            path=path,
            impl_source=FileReadSource.FILE_EDITOR,
            view_range=view_range,
        ),
        FileEditAction(
            path=path,
            command='replace_text',
            impl_source=FileEditSource.FILE_EDITOR,
            **edit_kwargs,
        ),
    ]


def _preview_str_replace_edit(path: str, command: str, kwargs: dict) -> AgentThinkAction:
    """Generate a unified diff preview of what a replace_text or insert_text would produce."""
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

    if command == 'replace_text':
        old_str = kwargs.get('old_str', '')
        new_str = kwargs.get('new_str', '')
        if not old_str:
            return AgentThinkAction(
                thought='[PREVIEW] old_str is required for replace_text preview'
            )
        original_text = ''.join(original_lines)
        count = original_text.count(old_str)
        if count == 0:
            return AgentThinkAction(thought=f'[PREVIEW] old_str not found in {path}')
        if count > 1:
            return AgentThinkAction(
                thought=f'[PREVIEW] old_str matches {count} locations — must be unique'
            )
        new_text = original_text.replace(old_str, new_str, 1)
        new_lines = new_text.splitlines(keepends=True)
    elif command == 'insert_text':
        insert_line = int(kwargs.get('insert_line', 0))
        new_str = kwargs.get('new_str', '')
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


def _apply_confidence_preview_override(kwargs: dict, path: str) -> None:
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


def _handle_str_replace_editor_tool(arguments: dict) -> Action:
    """Handle str_replace_editor tool call."""
    command = arguments.get('command', '')

    # batch_replace is handled separately — it doesn't need path validation
    if command == 'batch_replace':
        return _handle_batch_replace_command(arguments)

    path, command = _validate_str_replace_editor_args(arguments)
    command, normalized_args = _normalize_file_editor_command_and_args(
        command, arguments
    )
    valid_commands = {
        'view_file',
        'create_file',
        'replace_text',
        'insert_text',
        'undo_last_edit',
        'view_and_replace',
    }
    if command not in valid_commands:
        raise FunctionCallValidationError(
            f"Unknown command '{command}' for str_replace_editor tool. "
            f"Valid commands: {sorted(valid_commands)}"
        )
    path = str(normalized_args.get('path', path))
    other_kwargs = {
        k: v for k, v in normalized_args.items() if k not in ['command', 'path']
    }

    _apply_confidence_preview_override(other_kwargs, path)

    raw_preview = other_kwargs.pop('preview', False)
    if _is_preview_enabled(raw_preview) and command in ('replace_text', 'insert_text'):
        return _preview_str_replace_edit(path, command, other_kwargs)

    if command == 'view_and_replace':
        actions = _handle_view_and_replace(path, other_kwargs)
        if len(actions) == 1:
            return actions[0]
        # Execute the replacement action; returning the first action would drop edits.
        return actions[1]

    if command == 'view_file':
        return FileReadAction(
            path=path,
            impl_source=FileReadSource.FILE_EDITOR,
            view_range=other_kwargs.get('view_range'),
        )

    view_range = other_kwargs.pop('view_range', None)
    valid_kwargs = _filter_valid_editor_kwargs(other_kwargs)
    if command == 'replace_text' and view_range is not None:
        valid_kwargs['view_range'] = view_range

    action = FileEditAction(
        path=path,
        command=command,
        impl_source=FileEditSource.FILE_EDITOR,
        **valid_kwargs,
    )
    set_security_risk(action, arguments)
    return action


def _handle_batch_replace_command(arguments: dict) -> CmdRunAction:
    """Handle batch_replace command — atomic multi-file edits with rollback.

    The entire Python script is base64-encoded so the shell command contains no
    nested quotes, newlines, or special characters.  This makes it safe for
    PowerShell ``-Command``, bash ``-c``, and cmd ``/c`` alike.
    """
    import base64
    import json as _json

    edits = arguments.get('edits')
    if not edits or not isinstance(edits, list):
        raise FunctionCallValidationError(
            'batch_replace requires "edits" array of {path, old_str, new_str}'
        )
    normalized_edits: list[dict[str, str]] = []
    workspace_root = Path.cwd()
    for idx, edit in enumerate(edits):
        if not isinstance(edit, dict):
            raise FunctionCallValidationError(
                f'batch_replace edit at index {idx} must be an object'
            )
        path_val = edit.get('path')
        old_val = edit.get('old_str')
        new_val = edit.get('new_str')
        if not isinstance(path_val, str) or not isinstance(old_val, str) or not isinstance(
            new_val, str
        ):
            raise FunctionCallValidationError(
                f'batch_replace edit at index {idx} must include string path/old_str/new_str'
            )
        try:
            safe_path = SafePath.validate(
                path_val,
                workspace_root=str(workspace_root),
                must_be_relative=True,
            )
        except PathValidationError as exc:
            raise FunctionCallValidationError(
                f'batch_replace invalid path at index {idx}: {exc.message}'
            ) from exc
        normalized_edits.append(
            {
                'path': str(safe_path.path),
                'old_str': old_val,
                'new_str': new_val,
            }
        )
    preview = arguments.get('preview', False)
    edits_json = _json.dumps(normalized_edits)
    preview_flag = 'True' if preview else 'False'

    # --- readable Python source that will be base64-transported -----------
    script = f"""\
import json, re, sys
from collections import defaultdict

def _strip_trailing_newlines(s):
    return re.sub(r'\\n+$', '', s)

edits = json.loads({edits_json!r})
preview = {preview_flag}
errors = []

by_path = defaultdict(list)
for i, edit in enumerate(edits):
    by_path[edit['path']].append((i, edit))

for path, seq in by_path.items():
    for a in range(len(seq)):
        for b in range(a + 1, len(seq)):
            oa, ob = seq[a][1], seq[b][1]
            old_b = _strip_trailing_newlines(ob['old_str'])
            new_a = oa['new_str']
            if old_b and old_b in new_a:
                ia, ib = seq[a][0], seq[b][0]
                errors.append(
                    f'Edit ordering guard: edit {{ib}} old_str is contained in edit {{ia}} new_str (path {{path}})'
                )
                break
        if errors:
            break
    if errors:
        break

buffers = {{}}
if not errors:
    for i, edit in enumerate(edits):
        path, old, new = edit['path'], edit['old_str'], edit['new_str']
        try:
            if path not in buffers:
                with open(path, 'r', encoding='utf-8') as f:
                    buffers[path] = f.read()
            content = buffers[path]
            count = content.count(old)
            if count == 0:
                errors.append(f'Edit {{i}}: old_str not found in {{path}}')
                break
            if count > 1:
                errors.append(
                    f'Edit {{i}}: old_str matches {{count}} locations in {{path}} — must be unique'
                )
                break
            buffers[path] = content.replace(old, new, 1)
        except Exception as e:
            errors.append(f'Edit {{i}}: {{e}}')
            break

if not errors and not preview:
    originals = {{}}
    for path in buffers:
        with open(path, 'r', encoding='utf-8') as f:
            originals[path] = f.read()
    for path, final in buffers.items():
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(final)
            print(f'  [OK] {{path}}')
        except Exception as e:
            errors.append(f'Write failed for {{path}}: {{e}}')
            for opath, ocontent in originals.items():
                try:
                    with open(opath, 'w', encoding='utf-8') as f:
                        f.write(ocontent)
                except OSError as err:
                    sys.stderr.write(
                        f'[batch_replace] Rollback failed for {{opath!r}}: {{err}}\\n'
                    )
            break

if errors:
    print('BATCH EDIT FAILED — all changes rolled back.')
    print('Error:', errors[0])
    sys.exit(1)
else:
    if preview:
        print('DRY RUN: all', len(edits), 'edits would apply cleanly.')
    else:
        print('BATCH EDIT OK:', len(edits), 'files updated atomically.')
"""
    script_b64 = base64.b64encode(script.encode()).decode()
    label = 'dry-run' if preview else 'applying'
    return CmdRunAction(
        command=build_python_exec_command(
            f"import base64;exec(base64.b64decode(b'{script_b64}').decode())"
        ),
        thought=f'[BATCH REPLACE] {label} {len(normalized_edits)} edit(s) atomically',
    )


def _handle_think_tool(arguments: dict) -> AgentThinkAction:
    """Handle ThinkTool tool call."""
    tool_name = create_think_tool()['function']['name']
    thought = _require_tool_argument(arguments, 'thought', tool_name)
    return AgentThinkAction(thought=thought)


def _handle_summarize_context_tool(arguments: dict) -> CondensationRequestAction:
    """Handle Summarize Context tool call."""
    return CondensationRequestAction()


def _normalize_task_tracker_step(s: dict, idx: int) -> dict:
    """Normalize a single task step dict. Raises FunctionCallValidationError on invalid input."""
    from backend.orchestration.state.state import normalize_plan_step_payload

    if not isinstance(s, dict):
        raise FunctionCallValidationError(
            f'Task item must be a dictionary, got {type(s)}'
        )
    try:
        return normalize_plan_step_payload(s, idx)
    except TypeError as e:
        raise FunctionCallValidationError(str(e)) from e


def _normalize_task_tracker_list(raw_list: list) -> list[dict]:
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


def _handle_task_tracker_tool(arguments: dict) -> Action:
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

    existing_normalized_task_list: list[dict] = []
    if command == 'view':
        raw_task_list = tracker.load_from_file()
    else:
        # Capture the current persisted plan so we can detect no-op updates
        # that otherwise create tool-call loops without advancing execution.
        existing_raw = tracker.load_from_file()
        if isinstance(existing_raw, list):
            try:
                existing_normalized_task_list = _normalize_task_tracker_list(
                    existing_raw
                )
            except FunctionCallValidationError:
                existing_normalized_task_list = []
        raw_task_list = arguments.get('task_list', [])

    if not isinstance(raw_task_list, list):
        raise FunctionCallValidationError(
            f'Invalid format for "task_list". Expected a list but got {type(raw_task_list)}.'
        )

    normalized_task_list = _normalize_task_tracker_list(raw_task_list)

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
    if isinstance(arguments, Mapping):
        normalized_args = dict(arguments)
    else:
        logger.warning('MCP tool arguments is not a mapping, got: %s', type(arguments))
        normalized_args = {}

    return MCPAction(name=tool_call_name, arguments=normalized_args)


def _handle_execute_mcp_tool_tool(arguments: dict[str, Any]) -> MCPAction:
    """Handle the call_mcp_tool gateway — route to the real MCP tool."""
    tool_name = _require_tool_argument(arguments, 'tool_name', 'call_mcp_tool')
    inner_args = arguments.get('arguments', {})
    if not isinstance(inner_args, Mapping):
        inner_args = {}
    logger.info('MCP gateway routing to tool: %s', tool_name)
    return MCPAction(name=tool_name, arguments=dict(inner_args))


def _validate_ast_code_editor_args(arguments: dict, tool_name: str) -> tuple[str, str]:
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


def _normalize_ast_code_editor_alias(
    command: str,
    arguments: dict,
) -> tuple[str, dict[str, Any]]:
    """Normalize ast_code_editor command casing.

    Canonical-only mode: no legacy command or field aliases are accepted.
    """
    normalized_args: dict[str, Any] = dict(arguments)
    normalized_command = str(command or '').strip().lower()
    return normalized_command, normalized_args


def _handle_edit_symbol_body_command(editor, path: str, arguments: dict) -> Action:
    """Handle edit_symbol_body command."""
    function_name = arguments.get('function_name')
    new_body = arguments.get('new_body')

    if not function_name or not new_body:
        raise FunctionCallValidationError(
            "edit_symbol_body requires 'function_name' and 'new_body' arguments"
        )

    result = editor.edit_function(path, function_name, new_body)

    if result.success:
        return FileReadAction(
            path=path, impl_source=FileReadSource.DEFAULT, thought=result.message
        )
    return MessageAction(content=f'❌ Edit failed: {result.message}')


def _handle_rename_symbol_command(editor, path: str, arguments: dict) -> Action:
    """Handle rename_symbol command."""
    old_name = arguments.get('old_name')
    new_name = arguments.get('new_name')

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


def _handle_find_symbol_command(editor, path: str, arguments: dict) -> Action:
    """Handle find_symbol command."""
    symbol_name = arguments.get('symbol_name')
    if not symbol_name:
        raise FunctionCallValidationError("find_symbol requires 'symbol_name' argument")

    symbol_type = arguments.get('symbol_type')
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


def _handle_replace_range_command(editor, path: str, arguments: dict) -> Action:
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


def _handle_normalize_indent_command(editor, path: str, arguments: dict) -> Action:
    """Handle normalize_indent command."""
    style = arguments.get('style')
    size = arguments.get('size')
    result = editor.normalize_file_indent(path, style, size)

    if result.success:
        return FileReadAction(
            path=path, impl_source=FileReadSource.DEFAULT, thought=result.message
        )
    return MessageAction(content=f'❌ Normalization failed: {result.message}')


def _handle_create_file_command(path: str, arguments: dict) -> Action:
    """Handle create_file command — delegates to str_replace_editor create_file."""
    file_text = arguments.get('file_text', '')
    return FileEditAction(
        path=path,
        command='create_file',
        file_text=file_text,
        impl_source=FileEditSource.FILE_EDITOR,
    )


def _handle_view_file_command(path: str, _arguments: dict | None = None) -> Action:
    """Handle view_file command — reads file contents."""
    return FileReadAction(path=path, impl_source=FileReadSource.FILE_EDITOR)


def _handle_insert_text_command(path: str, arguments: dict) -> Action:
    """Handle insert_text command — inserts text after a line number."""
    new_str = arguments.get('new_str')
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


def _handle_undo_last_edit_command(path: str, _arguments: dict | None = None) -> Action:
    """Handle undo_last_edit — restores last snapshot for *path* in runtime FileEditor."""
    return FileEditAction(
        path=path,
        command='undo_last_edit',
        impl_source=FileEditSource.FILE_EDITOR,
    )


def _handle_ast_code_editor_tool(arguments: dict) -> Action:
    """Handle StructureEditor tool call."""
    tool_name = create_structure_editor_tool()['function']['name']

    # Validate arguments
    command, path = _validate_ast_code_editor_args(arguments, tool_name)
    command, normalized_args = _normalize_ast_code_editor_alias(command, arguments)

    file_editor_commands = {
        'create_file',
        'view_file',
        'replace_text',
        'insert_text',
        'view_and_replace',
        'undo_last_edit',
    }
    if command in file_editor_commands:
        passthrough_args: dict[str, Any] = {
            'command': command,
            'path': path,
        }
        for key in (
            'file_text',
            'old_str',
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
        return _handle_str_replace_editor_tool(passthrough_args)

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
        'rename_symbol': _handle_rename_symbol_command,
        'find_symbol': _handle_find_symbol_command,
        'replace_range': _handle_replace_range_command,
        'normalize_indent': _handle_normalize_indent_command,
    }
    # File I/O commands delegate directly to runtime actions (no StructureEditor needed)
    simple_command_handlers = {
        'create_file': _handle_create_file_command,
        'view_file': _handle_view_file_command,
        'insert_text': _handle_insert_text_command,
        'undo_last_edit': _handle_undo_last_edit_command,
    }

    # Execute command
    try:
        if command in editor_command_handlers:
            handler = editor_command_handlers[command]
            return handler(editor, path, normalized_args)
        elif command in simple_command_handlers:
            simple_handler = cast(
                Callable[[str, dict[str, Any]], Action],
                simple_command_handlers[command],
            )
            return simple_handler(path, normalized_args)
        else:
            all_cmds = list(editor_command_handlers) + list(simple_command_handlers)
            raise FunctionCallValidationError(
                f"Unknown command '{command}' for ast_code_editor tool. "
                f"Valid commands: {all_cmds}"
            )

    except Exception as e:
        return MessageAction(content=f'❌ Structure Editor error: {str(e)}')


def _handle_communicate_tool(arguments: dict) -> Action:
    """Route the unified communicate tool to the specific Action class based on intent."""
    intent = arguments.get('intent', 'clarification')
    message = arguments.get('message', '')
    options = arguments.get('options', [])
    context = arguments.get('context', '')
    thought = arguments.get('thought', '')

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
        formatted_options = (
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
            options=options,
            context=context,
            thought=thought,
        )


def _create_tool_dispatch_map() -> dict[str, ToolHandler]:
    """Create dispatch map for tool handlers."""
    return {
        create_cmd_run_tool()['function']['name']: _handle_cmd_run_tool,
        create_finish_tool()['function']['name']: _handle_finish_tool,
        create_llm_based_edit_tool()['function'][
            'name'
        ]: _handle_llm_based_file_edit_tool,
        create_str_replace_editor_tool()['function'][
            'name'
        ]: _handle_str_replace_editor_tool,
        create_structure_editor_tool()['function'][
            'name'
        ]: _handle_ast_code_editor_tool,
        create_think_tool()['function']['name']: _handle_think_tool,
        create_summarize_context_tool()['function'][
            'name'
        ]: _handle_summarize_context_tool,
        TASK_TRACKER_TOOL_NAME: _handle_task_tracker_tool,
        MEMORY_MANAGER_TOOL_NAME: _handle_memory_manager_tool,
        NOTE_TOOL_NAME: lambda args: build_note_action(args['key'], args['value']),
        RECALL_TOOL_NAME: lambda args: build_recall_action(args['key']),
        SEARCH_CODE_TOOL_NAME: _handle_search_code_tool,
        ANALYZE_PROJECT_STRUCTURE_TOOL_NAME: _handle_analyze_project_structure_tool,
        VERIFY_FILE_LINES_TOOL_NAME: _handle_verify_file_lines_tool,
        DELEGATE_TASK_TOOL_NAME: build_delegate_task_action,
        CODE_INTELLIGENCE_TOOL_NAME: build_lsp_query_action,
        SIGNAL_PROGRESS_TOOL_NAME: build_signal_progress_action,
        BLACKBOARD_TOOL_NAME: build_blackboard_action,
        TERMINAL_MANAGER_TOOL_NAME: handle_terminal_manager_tool,
        'explore_tree_structure': build_explore_tree_structure_action,
        'read_symbol_definition': build_read_symbol_definition_action,
        COMMUNICATE_TOOL_NAME: _handle_communicate_tool,
        EXECUTE_MCP_TOOL_TOOL_NAME: _handle_execute_mcp_tool_tool,
        CHECKPOINT_TOOL_NAME: _handle_checkpoint_tool,
        REVERT_TO_CHECKPOINT_TOOL_NAME: build_revert_to_checkpoint_action,
        SESSION_DIFF_TOOL_NAME: _handle_session_diff_tool,
        VERIFY_UI_CHANGE_TOOL_NAME: build_verify_ui_change_action,
    }


def response_to_actions(
    response: ModelResponse,
    mcp_tool_names: list[str] | None = None,
    mcp_tools: dict[str, Any] | None = None,
) -> list[Action]:
    """Convert LLM response to agent actions."""

    def process_with_mcp_tools(tc, args):
        return _process_single_tool_call(tc, args)

    return common_response_to_actions(
        response=response,
        create_action_fn=process_with_mcp_tools,
        combine_thought_fn=combine_thought,
        mcp_tool_names=mcp_tool_names,
    )


# Lazily-initialized dispatch map — built once per process to avoid
# re-creating tool definition dicts on every tool call.
_TOOL_DISPATCH_MAP: dict[str, ToolHandler] | None = None


def _get_tool_dispatch_map() -> dict[str, ToolHandler]:
    global _TOOL_DISPATCH_MAP
    if _TOOL_DISPATCH_MAP is None:
        _TOOL_DISPATCH_MAP = _create_tool_dispatch_map()
    return _TOOL_DISPATCH_MAP


def _process_single_tool_call(tool_call, arguments: dict[str, Any]) -> Action:
    """Process a single tool call and return the corresponding action."""
    logger.debug('Tool call in function_calling.py: %s', tool_call)
    tool_dispatch = _get_tool_dispatch_map()

    tool_name = tool_call.function.name
    mcp_tool_names = getattr(tool_call, '_mcp_tool_names', None)

    if tool_name in tool_dispatch:
        return tool_dispatch[tool_name](arguments)
    if mcp_tool_names and tool_name in mcp_tool_names:
        return _handle_mcp_tool(tool_name, arguments)
    msg = f'Tool {tool_name} is not registered. (arguments: {arguments}). Please check the tool name and retry with an existing tool.'
    raise FunctionCallNotExistsError(
        msg,
    )


def _set_tool_call_metadata(
    action: Action, tool_call, response: ModelResponse, total_calls: int
) -> None:
    """Set tool call metadata for the action.

    Falls back to direct construction if the patched ToolCallMetadata lacks
    the `from_sdk` classmethod (used in certain unit tests that monkeypatch
    the class).
    """
    action.tool_call_metadata = build_tool_call_metadata(
        function_name=tool_call.function.name,
        tool_call_id=tool_call.id,
        response_obj=response,
        total_calls_in_response=total_calls,
    )


def _create_message_action_from_content(content) -> list[Action]:
    """Create message action from content when no tool calls are present."""
    from backend.engine.common import (
        extract_redacted_thinking_inner,
        strip_thinking_tags,
    )

    raw = str(content) if content else ''
    cot = extract_redacted_thinking_inner(raw).strip()
    content_str = strip_thinking_tags(raw)
    return [
        MessageAction(
            content=content_str,
            thought=cot,
            wait_for_response=bool(content_str.strip()),
        )
    ]
