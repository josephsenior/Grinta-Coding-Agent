"""Non-file tool handlers used by function-calling tool dispatch.

Pure code motion: split from ``backend.engine.function_calling`` to keep
that module under the 40 KB file-size cap. No logic changes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

import backend.engine.tools.analyze_project_structure as analyze_project_structure_tools
import backend.engine.tools.checkpoint as checkpoint_tools
from backend.core.enums import FileEditSource
from backend.core.errors import FunctionCallValidationError
from backend.core.interaction_modes import PLAN_MODE, normalize_interaction_mode
from backend.core.logger import app_logger as logger
from backend.engine.function_calling_helpers import (
    parse_bool_argument,
    require_tool_argument,
    set_security_risk,
    validate_security_risk,
)
from backend.engine.tools import create_cmd_run_tool, create_finish_tool
from backend.engine.tools._file_ops import (
    _relative_display_path,
    _safe_workspace_path,
)
from backend.engine.tools.browser_native import (
    BROWSER_TOOL_NAME,
    build_browser_tool_action,
)
from backend.engine.tools.search_code import build_search_code_action
from backend.engine.tools.task_tracker import TaskTracker
from backend.inference.tool_names import (
    TASK_TRACKER_TOOL_NAME,
    UNDO_LAST_EDIT_TOOL_NAME,
)
from backend.ledger.action import (
    Action,
    AgentThinkAction,
    BrowserToolAction,
    CmdRunAction,
    FileEditAction,
    PlaybookFinishAction,
    TaskTrackingAction,
)
from backend.ledger.action.agent import CondensationRequestAction
from backend.ledger.action.mcp import MCPAction

AgentThinkToolHandler = Callable[[dict[str, Any]], AgentThinkAction]

build_analyze_project_structure_action = cast(
    AgentThinkToolHandler,
    cast(Any, analyze_project_structure_tools).build_analyze_project_structure_action,
)
build_checkpoint_action = cast(
    AgentThinkToolHandler, cast(Any, checkpoint_tools).build_checkpoint_action
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
_FINISH_EVIDENCE_STATUSES = {
    'passed',
    'failed',
    'partial',
    'not_run',
    'not_applicable',
    'planned',
}


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


def _optional_finish_string(arguments: Mapping[str, Any], field: str) -> str:
    value = arguments.get(field)
    if value is None:
        return ''
    return str(value).strip()


def _optional_finish_list(
    arguments: Mapping[str, Any],
    field: str,
    tool_name: str,
) -> list[Any]:
    if field not in arguments:
        return []
    value = arguments.get(field)
    if not isinstance(value, list):
        raise FunctionCallValidationError(
            f'Argument "{field}" for tool call {tool_name} must be a list.'
        )
    return value


def _clean_finish_items(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray)):
        return []
    return [text for item in value if (text := str(item).strip())]


def _normalize_finish_sections(
    arguments: Mapping[str, Any],
    field: str,
    tool_name: str,
) -> list[dict[str, Any]]:
    if field not in arguments:
        return []
    raw_sections = arguments.get(field)
    if not isinstance(raw_sections, list):
        raise FunctionCallValidationError(
            f'Argument "{field}" for tool call {tool_name} must be a list.'
        )

    sections: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_sections, 1):
        if not isinstance(raw, Mapping):
            raise FunctionCallValidationError(
                f'Item {index} in "{field}" for tool call {tool_name} must be an object.'
            )
        title = str(raw.get('title') or '').strip()
        items = _clean_finish_items(raw.get('items', []))
        if not title:
            raise FunctionCallValidationError(
                f'Item {index} in "{field}" for tool call {tool_name} requires a title.'
            )
        if not items:
            raise FunctionCallValidationError(
                f'Item {index} in "{field}" for tool call {tool_name} requires at least one item.'
            )
        sections.append({'title': title, 'items': items})
    return sections


def _finish_section(title: str, items: Any) -> dict[str, Any] | None:
    cleaned = _clean_finish_items(items)
    if not cleaned:
        return None
    return {'title': title, 'items': cleaned}


def _legacy_plan_sections(
    *,
    plan: list[Any],
    files_or_areas: list[Any],
    risks: list[Any],
    verification: list[Any],
    assumptions: list[Any],
) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    for section in (
        _finish_section('Recommended Plan', plan),
        _finish_section('Scope / Targets', files_or_areas),
        _finish_section('Risks / Tradeoffs', risks),
        _finish_section('Verification Strategy', verification),
        _finish_section('Assumptions / Open Questions', assumptions),
    ):
        if section is not None:
            sections.append(section)
    return sections


def _legacy_agent_sections(*, actions_taken: list[Any]) -> list[dict[str, Any]]:
    section = _finish_section('What I Did', actions_taken)
    return [section] if section is not None else []


def _normalize_finish_evidence(
    arguments: Mapping[str, Any],
    tool_name: str,
    *,
    fallback: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    raw = arguments.get('evidence')
    if raw is None:
        raw = fallback or {}
    if not isinstance(raw, Mapping):
        raise FunctionCallValidationError(
            f'Argument "evidence" for tool call {tool_name} must be an object.'
        )

    status = str(raw.get('status') or '').strip().lower()
    details = str(raw.get('details') or '').strip()
    if not status:
        status = 'not_run'
    if status not in _FINISH_EVIDENCE_STATUSES:
        allowed = ', '.join(sorted(_FINISH_EVIDENCE_STATUSES))
        raise FunctionCallValidationError(
            f'Invalid finish evidence status {status!r}; expected one of: {allowed}.'
        )
    if not details:
        raise FunctionCallValidationError(
            f'Finish evidence for tool call {tool_name} requires non-empty details.'
        )
    return {'status': status, 'details': details}


def _evidence_from_plan_verification(verification: list[Any]) -> dict[str, str] | None:
    items = _clean_finish_items(verification)
    if not items:
        return None
    return {
        'status': 'planned',
        'details': '; '.join(items),
    }


def _evidence_from_agent_verification(
    verification: Mapping[str, Any] | None,
) -> dict[str, str] | None:
    if not verification:
        return None
    status = str(verification.get('status') or '').strip()
    details = str(verification.get('details') or '').strip()
    if not status and not details:
        return None
    return {'status': status or 'not_run', 'details': details}


def _handle_plan_finish_tool(arguments: Mapping[str, Any]) -> PlaybookFinishAction:
    tool_name = _finish_tool_name(PLAN_MODE)
    status = _require_finish_status(arguments, tool_name)
    summary = _require_finish_string(arguments, 'summary', tool_name)
    response = _optional_finish_string(arguments, 'response') or summary
    plan = _optional_finish_list(arguments, 'plan', tool_name)
    files_or_areas = _optional_finish_list(arguments, 'files_or_areas', tool_name)
    risks = _optional_finish_list(arguments, 'risks', tool_name)
    verification = _optional_finish_list(arguments, 'verification', tool_name)
    assumptions = _optional_finish_list(arguments, 'assumptions', tool_name)
    next_step = _optional_finish_string(arguments, 'next_step')
    sections = _normalize_finish_sections(arguments, 'sections', tool_name)
    if not sections:
        sections = _legacy_plan_sections(
            plan=plan,
            files_or_areas=files_or_areas,
            risks=risks,
            verification=verification,
            assumptions=assumptions,
        )
    evidence = _normalize_finish_evidence(
        arguments,
        tool_name,
        fallback=_evidence_from_plan_verification(verification)
        or {'status': 'not_applicable', 'details': summary},
    )
    open_items = _optional_finish_list(arguments, 'open_items', tool_name)

    if status == 'completed' and not sections:
        raise FunctionCallValidationError(
            'Plan Mode finish with status="completed" requires non-empty sections or a non-empty plan.'
        )

    outputs: dict[str, Any] = {
        'mode': 'plan',
        'status': status,
        'response': response,
        'summary': summary,
        'sections': sections,
        'evidence': evidence,
        'open_items': open_items,
        'next_step': next_step,
        'plan': plan,
        'files_or_areas': files_or_areas,
        'risks': risks,
        'verification': verification,
        'assumptions': assumptions,
    }
    return PlaybookFinishAction(final_thought=response, outputs=outputs)


def _handle_agent_finish_tool(arguments: Mapping[str, Any]) -> PlaybookFinishAction:
    tool_name = _finish_tool_name('agent')
    status = _require_finish_status(arguments, tool_name)
    summary = _require_finish_string(arguments, 'summary', tool_name)
    response = _optional_finish_string(arguments, 'response') or summary
    actions_taken = _optional_finish_list(arguments, 'actions_taken', tool_name)
    raw_verification = arguments.get('verification')
    remaining_items = _optional_finish_list(arguments, 'remaining_items', tool_name)
    next_step = _optional_finish_string(arguments, 'next_step')
    sections = _normalize_finish_sections(arguments, 'sections', tool_name)
    if not sections:
        sections = _legacy_agent_sections(actions_taken=actions_taken)
    if status == 'completed' and not sections:
        raise FunctionCallValidationError(
            'Agent Mode finish with status="completed" requires non-empty actions_taken or sections.'
        )
    if raw_verification is None:
        verification: dict[str, Any] = {}
    elif isinstance(raw_verification, Mapping):
        verification = dict(raw_verification)
    else:
        raise FunctionCallValidationError(
            f'Argument "verification" for tool call {tool_name} must be an object.'
        )
    evidence = _normalize_finish_evidence(
        arguments,
        tool_name,
        fallback=_evidence_from_agent_verification(verification),
    )
    open_items = (
        _optional_finish_list(arguments, 'open_items', tool_name) or remaining_items
    )

    outputs: dict[str, Any] = {
        'mode': 'agent',
        'status': status,
        'response': response,
        'summary': summary,
        'sections': sections,
        'evidence': evidence,
        'open_items': open_items,
        'next_step': next_step,
        'actions_taken': actions_taken,
        'verification': verification,
        'remaining_items': remaining_items,
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
    return PlaybookFinishAction(final_thought=response, outputs=outputs)


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


def _handle_undo_last_edit_tool(arguments: Mapping[str, Any]) -> Action:
    """Handle undo_last_edit tool: revert the last file-write on an existing file."""
    path = str(require_tool_argument(arguments, 'path', UNDO_LAST_EDIT_TOOL_NAME))
    safe_path = _safe_workspace_path(path)
    if not safe_path.is_file():
        raise FunctionCallValidationError(
            f"File '{path}' does not exist. undo_last_edit only applies to existing files. "
            'To undo a file creation, delete the file instead.'
        )
    return FileEditAction(
        path=_relative_display_path(safe_path),
        command='undo_last_edit',
        impl_source=FileEditSource.FILE_EDITOR,
    )


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
