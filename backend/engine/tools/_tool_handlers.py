"""Non-file tool handlers used by function-calling tool dispatch.

Pure code motion: split from ``backend.engine.function_calling`` to keep
that module under the 40 KB file-size cap. No logic changes.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, cast

import backend.engine.tools.analyze_project_structure as analyze_project_structure_tools
import backend.engine.tools.checkpoint as checkpoint_tools
from backend.core.criteria.acceptance_criteria_store import AcceptanceCriteriaStore
from backend.core.criteria.criterion_item import (
    assign_criterion_ids,
    merge_ids_from_existing,
    normalize_criteria_list,
)
from backend.core.enums import FileEditSource
from backend.core.errors import FunctionCallValidationError
from backend.core.logging.logger import app_logger as logger
from backend.core.tasks.task_tracker import TaskTracker
from backend.core.tools.tool_names import (
    ACCEPTANCE_CRITERIA_TOOL_NAME,
    TASK_TRACKER_TOOL_NAME,
    UNDO_LAST_EDIT_TOOL_NAME,
)
from backend.engine.function_calling.helpers import (
    parse_bool_argument,
    require_tool_argument,
    set_security_risk,
    validate_security_risk,
)
from backend.engine.tools import create_cmd_run_tool
from backend.engine.tools._file_ops import (
    _relative_display_path,
    _safe_workspace_path,
)
from backend.engine.tools.browser_native import (
    BROWSER_TOOL_NAME,
    build_browser_tool_action,
)
from backend.engine.tools.glob import build_glob_action
from backend.engine.tools.grep import build_grep_action
from backend.ledger.action import (
    AcceptanceCriteriaAction,
    Action,
    AnalyzeProjectStructureAction,
    BrowserToolAction,
    CheckpointAction,
    CmdRunAction,
    FileEditAction,
    MemoryPersistAction,
    MemoryRecallAction,
    TaskTrackingAction,
)
from backend.ledger.action.mcp import MCPAction
from backend.ledger.action.search import GlobAction, GrepAction
from backend.ledger.observation.memory_tools import (
    MemoryPersistObservation,
    MemoryRecallObservation,
)

ActionToolHandler = Callable[[dict[str, Any]], Action]

build_analyze_project_structure_action = cast(
    ActionToolHandler,
    cast(Any, analyze_project_structure_tools).build_analyze_project_structure_action,
)
build_checkpoint_action = cast(
    ActionToolHandler, cast(Any, checkpoint_tools).build_checkpoint_action
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


def _handle_web_search_tool(arguments: Mapping[str, Any]) -> MCPAction:
    """Handle native web_search — delegates to Exa MCP web_search_exa."""
    from backend.engine.tools.web_tools import build_web_search_action

    return build_web_search_action(dict(arguments))


def _handle_web_fetch_tool(arguments: Mapping[str, Any]) -> MCPAction:
    """Handle native web_fetch — Exa first, fetch MCP fallback (internal router)."""
    from backend.engine.tools.web_tools import build_web_fetch_action

    return build_web_fetch_action(dict(arguments))


def _handle_docs_resolve_tool(arguments: Mapping[str, Any]) -> MCPAction:
    """Handle native docs_resolve — delegates to Context7 resolve-library-id."""
    from backend.engine.tools.docs_tools import build_docs_resolve_action

    return build_docs_resolve_action(dict(arguments))


def _handle_docs_query_tool(arguments: Mapping[str, Any]) -> MCPAction:
    """Handle native docs_query — delegates to Context7 query-docs."""
    from backend.engine.tools.docs_tools import build_docs_query_action

    return build_docs_query_action(dict(arguments))


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


def execute_memory_persist(action: MemoryPersistAction) -> MemoryPersistObservation:
    """Persist a workspace memory entry."""
    from backend.engine.tools.workspace_memory import persist_entry

    inserted, message = persist_entry(
        kind=action.kind, key=action.key, value=action.value
    )
    return MemoryPersistObservation(
        content=message,
        key=action.key,
        kind=action.kind,
        inserted=inserted,
    )


def execute_memory_recall(action: MemoryRecallAction) -> MemoryRecallObservation:
    """Semantic recall over indexed conversation history."""
    query = action.query
    recall_fn = _semantic_recall_registry.get('fn')
    if recall_fn is None:
        return MemoryRecallObservation(
            content=(
                'Semantic recall is not available in this session. Install optional RAG '
                'with pip install "grinta-ai[rag]" (auto-enabled when installed) or set '
                'agent.Orchestrator.enable_vector_memory to false to hide recall.'
            ),
            query=query,
        )
    results = recall_fn(query, 5)
    if not results:
        return MemoryRecallObservation(
            content=f'No indexed memory results found for query: {query!r}',
            query=query,
        )
    parts = [f'{len(results)} results for query: {query!r}\n']
    for i, item in enumerate(results, 1):
        content = str(item.get('excerpt', ''))
        role = item.get('role', 'unknown')
        score = item.get('score', '')
        score_str = f' (score={score:.3f})' if isinstance(score, float) else ''
        excerpt = content[:500]
        if len(content) > 500:
            excerpt += ' […truncated]'
        parts.append(f'  [{i}] ({role}{score_str}) {excerpt}')
    return MemoryRecallObservation(
        content='\n'.join(parts),
        query=query,
        hits=list(results),
    )


def _handle_memory_tool(arguments: Mapping[str, Any]) -> Action:
    """Handle unified memory ops: working, persist, recall."""
    action = str(arguments.get('action', '')).strip().lower()
    if not action:
        raise FunctionCallValidationError("Missing 'action' in memory tool.")

    if action == 'recall':
        query = cast(str, arguments.get('key', ''))
        if not query:
            raise FunctionCallValidationError(
                'Missing search phrase "key" in memory(recall)'
            )
        if get_semantic_recall_fn() is None:
            raise FunctionCallValidationError(
                'memory(recall) is not available in this session. Install optional '
                'RAG support with pip install "grinta-ai[rag]" or set '
                'enable_vector_memory to false in settings.'
            )
        return MemoryRecallAction(query=query)

    if action == 'persist':
        key = cast(str, arguments.get('key', ''))
        value = cast(str, arguments.get('value', ''))
        kind = cast(str, arguments.get('kind', 'lesson'))
        if not key.strip():
            raise FunctionCallValidationError('persist requires non-empty key.')
        if not value.strip():
            raise FunctionCallValidationError('persist requires non-empty value.')
        return MemoryPersistAction(key=key, value=value, kind=kind)

    if action == 'working':
        import backend.engine.tools.working_memory as working_memory_tools

        wm_args = {
            'command': cast(str, arguments.get('update_type', 'get')),
            'section': cast(str, arguments.get('section', 'all')),
            'content': cast(str, arguments.get('content', '')),
        }
        build_wm = cast(
            ActionToolHandler,
            cast(Any, working_memory_tools).build_working_memory_action,
        )
        return build_wm(wm_args)

    raise FunctionCallValidationError(
        f'Unknown memory action: {action!r}. Use working, persist, or recall.'
    )


_handle_memory_manager_tool = _handle_memory_tool


def _handle_grep_tool(arguments: Mapping[str, Any]) -> GrepAction:
    """Handle GREP tool: regex text search across files via ripgrep/Python."""
    return build_grep_action(
        pattern=cast(str, arguments.get('pattern', '')),
        path=cast(str, arguments.get('path', '.')),
        file_pattern=cast(str, arguments.get('file_pattern', '')),
        output_mode=cast(str, arguments.get('output_mode', 'files_with_matches')),
        context_lines=cast(int, arguments.get('context_lines', 2)),
        case_sensitive=cast(bool, arguments.get('case_sensitive', False)),
        head_limit=cast(int | None, arguments.get('head_limit')),
        offset=cast(int, arguments.get('offset', 0)),
    )


def _handle_glob_tool(arguments: Mapping[str, Any]) -> GlobAction:
    """Handle GLOB tool: list files matching a glob pattern."""
    return build_glob_action(
        pattern=cast(str, arguments.get('pattern', '')),
        path=cast(str, arguments.get('path', '.')),
        head_limit=cast(int | None, arguments.get('head_limit')),
        offset=cast(int, arguments.get('offset', 0)),
    )


def _handle_undo_last_edit_tool(arguments: Mapping[str, Any]) -> Action:
    """Handle undo_last_edit tool: revert the last file-write on an existing file."""
    path = str(require_tool_argument(arguments, 'path', UNDO_LAST_EDIT_TOOL_NAME))
    safe_path = _safe_workspace_path(path)
    if not safe_path.is_file():
        raise FunctionCallValidationError(f"File '{path}' does not exist.")
    return FileEditAction(
        path=_relative_display_path(safe_path),
        command='undo_last_edit',
        impl_source=FileEditSource.FILE_EDITOR,
    )


def _handle_checkpoint_tool(arguments: Mapping[str, Any]) -> CheckpointAction:
    """Handle checkpoint tool: save/view/revert/clear progress checkpoints."""
    return cast(CheckpointAction, build_checkpoint_action(dict(arguments)))


def _handle_analyze_project_structure_tool(
    arguments: Mapping[str, Any],
) -> AnalyzeProjectStructureAction:
    """Handle analyze_project_structure tool: structural overview of the workspace."""
    return cast(
        AnalyzeProjectStructureAction,
        build_analyze_project_structure_action(dict(arguments)),
    )


def _normalize_task_tracker_step(s: Mapping[str, Any], idx: int) -> dict[str, Any]:
    """Normalize a single task step dict. Raises FunctionCallValidationError on invalid input."""
    from backend.core.tasks.plan_step import normalize_plan_step_payload

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
        current_plan = tracker.load_from_file()
        success, message, updated_plan = tracker.apply_task_status_update(
            current_plan, task_id, status, result
        )
        if not success:
            from backend.ledger.action.agent import SystemHintAction

            return SystemHintAction(
                thought=f'[TASK_TRACKER] {message}',
                source_tool=TASK_TRACKER_TOOL_NAME,
            )
        return TaskTrackingAction(
            command='update_status',
            task_list=updated_plan,
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

    return TaskTrackingAction(command=command, task_list=normalized_task_list)


def _normalize_criteria_list(
    raw_list: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Normalize criteria list. Raises FunctionCallValidationError on invalid structure."""
    try:
        return normalize_criteria_list(list(raw_list))
    except TypeError as e:
        raise FunctionCallValidationError(str(e)) from e


def _criteria_existing_normalized(
    store: AcceptanceCriteriaStore,
) -> list[dict[str, Any]]:
    try:
        return normalize_criteria_list(store.load_from_file())
    except TypeError:
        return []


def _maybe_noop_criteria_action(
    command: str,
    normalized: list[dict[str, Any]],
    existing: list[dict[str, Any]],
) -> AcceptanceCriteriaAction | None:
    if command == 'update' and normalized and normalized == existing:
        logger.info('Converting no-op acceptance_criteria update into a no-op action')
        return AcceptanceCriteriaAction(
            command=command,
            criteria_list=normalized,
            thought=(
                '[ACCEPTANCE_CRITERIA] Update skipped because the criteria list is unchanged. '
                'Continue implementation; re-audit only before the final summary.'
            ),
        )
    return None


def _validate_audit_criteria(normalized: list[dict[str, Any]]) -> None:
    missing = [
        i + 1
        for i, item in enumerate(normalized)
        if not str(item.get('evidence') or '').strip()
    ]
    if missing:
        raise FunctionCallValidationError(
            f'Audit requires evidence or an explicit gap on every criterion. '
            f'Missing on item(s): {missing}'
        )


def _normalize_audit_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(entry, Mapping):
        raise FunctionCallValidationError(
            'Each audit_entries item must be an object with criterion_id.'
        )
    criterion_id = str(entry.get('criterion_id') or '').strip()
    if not criterion_id:
        raise FunctionCallValidationError(
            'Each audit_entries item requires a non-empty criterion_id.'
        )
    evidence_ref = str(entry.get('evidence_ref') or '').strip()
    evidence = str(entry.get('evidence') or '').strip()
    unverifiable = parse_bool_argument(entry.get('unverifiable'))

    if evidence_ref:
        result: dict[str, Any] = {
            'criterion_id': criterion_id,
            'evidence_ref': evidence_ref,
        }
        if evidence:
            result['evidence_fallback'] = evidence
        return result
    if evidence:
        if not unverifiable:
            raise FunctionCallValidationError(
                f'Audit entry for {criterion_id!r} uses free-text evidence; '
                'set unverifiable=true for subjective criteria or use evidence_ref.'
            )
        return {
            'criterion_id': criterion_id,
            'evidence': evidence,
            'unverifiable': True,
        }
    raise FunctionCallValidationError(
        f'Audit entry for {criterion_id!r} requires evidence_ref or '
        'evidence with unverifiable=true.'
    )


def _validate_audit_entries(
    raw_entries: Any,
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(raw_entries, Sequence):
        raise FunctionCallValidationError(
            'Invalid format for "audit_entries". Expected a list.'
        )
    if not existing:
        raise FunctionCallValidationError(
            'Audit requires existing acceptance criteria. Call update first.'
        )
    normalized_entries = [
        _normalize_audit_entry(cast(Mapping[str, Any], item))
        for item in raw_entries
        if isinstance(item, Mapping)
    ]
    if len(normalized_entries) != len(raw_entries):
        raise FunctionCallValidationError(
            'Each audit_entries item must be an object with criterion_id.'
        )

    existing_ids = {
        str(item.get('id') or '').strip()
        for item in existing
        if str(item.get('id') or '').strip()
    }
    entry_ids = [entry['criterion_id'] for entry in normalized_entries]
    if len(set(entry_ids)) != len(entry_ids):
        raise FunctionCallValidationError(
            'audit_entries must include each criterion_id at most once.'
        )
    if set(entry_ids) != existing_ids:
        missing = sorted(existing_ids - set(entry_ids))
        extra = sorted(set(entry_ids) - existing_ids)
        parts: list[str] = []
        if missing:
            parts.append(f'missing: {", ".join(missing)}')
        if extra:
            parts.append(f'unknown: {", ".join(extra)}')
        raise FunctionCallValidationError(
            'audit_entries must cover every current criterion exactly once'
            + (f' ({"; ".join(parts)})' if parts else '')
        )
    return normalized_entries


def _handle_acceptance_criteria_tool(arguments: Mapping[str, Any]) -> Action:
    """Handle acceptance_criteria tool call."""
    command = require_tool_argument(arguments, 'command', ACCEPTANCE_CRITERIA_TOOL_NAME)
    if command not in {'view', 'update', 'append', 'refine', 'audit'}:
        raise FunctionCallValidationError(
            f'Unsupported command {command!r} for tool call {ACCEPTANCE_CRITERIA_TOOL_NAME}'
        )

    store = AcceptanceCriteriaStore()

    if command == 'view':
        raw_list = store.load_from_file()
        return AcceptanceCriteriaAction(command='view', criteria_list=raw_list)

    if command == 'refine':
        criterion_id = str(arguments.get('criterion_id') or '').strip()
        new_assertion = str(arguments.get('new_assertion') or '').strip()
        reason = str(arguments.get('reason') or '').strip()
        if not criterion_id:
            raise FunctionCallValidationError(
                'refine requires non-empty criterion_id (from view).'
            )
        if not new_assertion:
            raise FunctionCallValidationError(
                'refine requires non-empty new_assertion.'
            )
        if not reason:
            raise FunctionCallValidationError(
                'refine requires non-empty reason explaining the change.'
            )
        existing = _criteria_existing_normalized(store)
        known_ids = {
            str(item.get('id') or '').strip()
            for item in existing
            if str(item.get('id') or '').strip()
        }
        if criterion_id not in known_ids:
            raise FunctionCallValidationError(
                f'Unknown criterion_id {criterion_id!r}. Call view for current ids.'
            )
        return AcceptanceCriteriaAction(
            command='refine',
            criterion_id=criterion_id,
            new_assertion=new_assertion,
            reason=reason,
            criteria_list=existing,
        )

    if command == 'audit':
        existing = _criteria_existing_normalized(store)
        if 'audit_entries' in arguments:
            audit_entries = _validate_audit_entries(
                arguments.get('audit_entries'), existing
            )
            return AcceptanceCriteriaAction(
                command='audit',
                audit_entries=audit_entries,
                criteria_list=existing,
            )

        if 'criteria_list' not in arguments:
            raise FunctionCallValidationError(
                'Missing required argument "audit_entries" (preferred) or '
                '"criteria_list" (legacy) for "audit" command.'
            )
        raw_any = arguments.get('criteria_list', [])
        if not isinstance(raw_any, Sequence):
            raise FunctionCallValidationError(
                f'Invalid format for "criteria_list". Expected a list but got {type(raw_any)}.'
            )
        criteria_raw = cast(Sequence[Mapping[str, Any]], raw_any)
        normalized = _normalize_criteria_list(list(criteria_raw))
        _validate_audit_criteria(normalized)
        if existing and len(normalized) != len(existing):
            raise FunctionCallValidationError(
                'Audit must include every criterion in the current list with evidence filled.'
            )
        return AcceptanceCriteriaAction(command='audit', criteria_list=normalized)

    if 'criteria_list' not in arguments:
        raise FunctionCallValidationError(
            f'Missing required argument "criteria_list" for "{command}" command '
            f'in tool call {ACCEPTANCE_CRITERIA_TOOL_NAME}'
        )

    raw_any = arguments.get('criteria_list', [])
    if not isinstance(raw_any, Sequence):
        raise FunctionCallValidationError(
            f'Invalid format for "criteria_list". Expected a list but got {type(raw_any)}.'
        )
    criteria_raw = cast(Sequence[Mapping[str, Any]], raw_any)
    normalized = _normalize_criteria_list(list(criteria_raw))
    existing = _criteria_existing_normalized(store)

    if command == 'append':
        if not normalized:
            raise FunctionCallValidationError(
                'Append requires at least one new criterion in criteria_list.'
            )
        final_list = existing + assign_criterion_ids(normalized, existing=existing)
    else:
        final_list = merge_ids_from_existing(normalized, existing)
        final_list = assign_criterion_ids(final_list, existing=existing)
        noop = _maybe_noop_criteria_action(command, final_list, existing)
        if noop is not None:
            return noop

    return AcceptanceCriteriaAction(command=command, criteria_list=final_list)


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
    """Backward-compatible alias for gateway calls to resolve-library-id."""
    from backend.engine.tools.docs_tools import apply_docs_resolve_defaults

    apply_docs_resolve_defaults(inner)


def _handle_execute_mcp_tool_tool(arguments: dict[str, Any]) -> MCPAction:
    """Handle the call_mcp_tool gateway — route to the real MCP tool."""
    tool_name = require_tool_argument(arguments, 'tool_name', 'call_mcp_tool')
    inner_args = _merge_mcp_gateway_inner_arguments(arguments)
    if tool_name == 'resolve-library-id':
        _apply_context7_resolve_library_defaults(inner_args)
    logger.info('MCP gateway routing to tool: %s', tool_name)
    return MCPAction(name=tool_name, arguments=inner_args)


def _handle_ask_user_tool(arguments: Mapping[str, Any]) -> Action:
    """Handle the simplified ask_user tool."""
    from backend.engine.tools.meta_cognition import build_ask_user_action

    return build_ask_user_action(arguments)
