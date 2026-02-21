"""This file contains the function calling implementation for different actions.

This is similar to the functionality of `CodeActResponseParser`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

from backend.core.exceptions import (
    FunctionCallNotExistsError,
    FunctionCallValidationError,
)
from backend.core.logger import forge_logger as logger
from backend.engines.orchestrator.tools import (
    create_apply_patch_tool,
    create_cmd_run_tool,
    create_condensation_request_tool,
    create_finish_tool,
    create_llm_based_edit_tool,
    create_note_tool,
    create_recall_tool,
    create_run_tests_tool,
    create_semantic_recall_tool,
    create_str_replace_editor_tool,
    create_structure_editor_tool,
    create_think_tool,
)
from backend.engines.orchestrator.tools.terminal import (
    TERMINAL_OPEN_TOOL_NAME,
    TERMINAL_INPUT_TOOL_NAME,
    TERMINAL_READ_TOOL_NAME,
    build_terminal_open_action,
    build_terminal_input_action,
    build_terminal_read_action,
)
from backend.engines.orchestrator.tools.apply_patch import build_apply_patch_action
from backend.engines.orchestrator.tools.batch_edit import (
    build_batch_edit_action,
    BATCH_EDIT_TOOL_NAME,
)
from backend.engines.orchestrator.tools.note import (
    build_note_action,
    build_recall_action,
)
from backend.engines.orchestrator.tools.run_tests import build_run_tests_action
from backend.engines.orchestrator.tools.search_code import (
    build_search_code_action,
    SEARCH_CODE_TOOL_NAME,
)
from backend.engines.orchestrator.tools.web_search import (
    build_web_search_action,
    WEB_SEARCH_TOOL_NAME,
)
from backend.engines.orchestrator.tools.check_tool_status import (
    build_check_tool_status_action,
)
from backend.engines.orchestrator.tools.web_reader import (
    build_web_reader_action,
    WEB_READER_TOOL_NAME,
)
from backend.engines.orchestrator.tools.workspace_status import (
    build_workspace_status_action,
    WORKSPACE_STATUS_TOOL_NAME,
)
from backend.engines.orchestrator.tools.error_patterns import (
    build_error_patterns_action,
    ERROR_PATTERNS_TOOL_NAME,
)
from backend.engines.orchestrator.tools.checkpoint import (
    build_checkpoint_action,
    CHECKPOINT_TOOL_NAME,
)
from backend.engines.orchestrator.tools.project_map import (
    build_project_map_action,
    PROJECT_MAP_TOOL_NAME,
)
from backend.engines.orchestrator.tools.session_diff import (
    build_session_diff_action,
    SESSION_DIFF_TOOL_NAME,
)
from backend.engines.orchestrator.tools.verify_state import (
    build_verify_state_action,
    VERIFY_STATE_TOOL_NAME,
)
from backend.engines.orchestrator.tools.working_memory import (
    build_working_memory_action,
    WORKING_MEMORY_TOOL_NAME,
)
from backend.engines.orchestrator.tools.revert_to_safe_state import (
    build_revert_to_safe_state_action,
    REVERT_TO_SAFE_STATE_TOOL_NAME,
)
from backend.engines.orchestrator.tools.delegate_task import (
    build_delegate_task_action,
    DELEGATE_TASK_TOOL_NAME,
)
from backend.engines.orchestrator.tools.meta_cognition import (
    UNCERTAINTY_TOOL_NAME,
    CLARIFICATION_TOOL_NAME,
    ESCALATE_TOOL_NAME,
    PROPOSAL_TOOL_NAME,
)
from backend.engines.common import (
    common_response_to_actions,
)
from backend.events.action import (
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
from backend.events.action.agent import CondensationRequestAction
from backend.events.action.mcp import MCPAction
from backend.core.enums import FileEditSource, FileReadSource
from backend.engines.orchestrator.tools.security_utils import RISK_LEVELS
from backend.events.tool import build_tool_call_metadata
from backend.llm.tool_names import TASK_TRACKER_TOOL_NAME
from backend.engines.orchestrator.tools.task_tracker import TaskTracker

ToolHandler = Callable[[dict[str, Any]], Action]

# Callback for semantic recall — set by the orchestrator at init time.
# Signature: (query: str, k: int) -> list[dict[str, Any]]
_semantic_recall_registry: dict[str, Callable[[str, int], list[dict[str, Any]]]] = {}


def register_semantic_recall(fn: Callable[[str, int], list[dict[str, Any]]]) -> None:
    """Register the vector-memory recall callback (called by orchestrator)."""
    _semantic_recall_registry["fn"] = fn


def get_semantic_recall_fn() -> Callable[[str, int], list[dict[str, Any]]] | None:
    """Return the registered semantic recall callback, or None."""
    return _semantic_recall_registry.get("fn")


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
    if not hasattr(action, "thought"):
        return action
    if thought:
        action.thought = f"{thought}\n{action.thought}" if action.thought else thought
    return action


def set_security_risk(action: Action, arguments: dict) -> None:
    """Set the security risk level for the action."""
    if "security_risk" in arguments:
        if arguments["security_risk"] in RISK_LEVELS:
            if hasattr(action, "security_risk"):
                action.security_risk = getattr(
                    ActionSecurityRisk, arguments["security_risk"]
                )
        else:
            logger.warning(
                "Invalid security_risk value: %s", arguments["security_risk"]
            )


def _handle_cmd_run_tool(arguments: dict) -> CmdRunAction:
    """Handle CmdRunTool (Bash) tool call."""
    if "command" not in arguments:
        msg = f'Missing required argument "command" in tool call {create_cmd_run_tool()["function"]["name"]}'
        raise FunctionCallValidationError(
            msg,
        )
    raw_is_input = arguments.get("is_input", False)
    is_input = raw_is_input is True or (
        isinstance(raw_is_input, str) and raw_is_input.lower() == "true"
    )
    action = CmdRunAction(command=arguments["command"], is_input=is_input)
    if "timeout" in arguments:
        try:
            action.set_hard_timeout(float(arguments["timeout"]))
        except ValueError as e:
            msg = f"Invalid float passed to 'timeout' argument: {arguments['timeout']}"
            raise FunctionCallValidationError(
                msg,
            ) from e
    set_security_risk(action, arguments)
    return action


def _handle_finish_tool(arguments: dict) -> PlaybookFinishAction:
    """Handle FinishTool tool call."""
    if "message" not in arguments:
        msg = f'Missing required argument "message" in tool call {create_finish_tool()["function"]["name"]}'
        raise FunctionCallValidationError(
            msg,
        )
    outputs: dict = {}
    if "completed" in arguments:
        outputs["completed"] = arguments["completed"]
    if "blocked_by" in arguments:
        outputs["blocked_by"] = arguments["blocked_by"]
    if "next_steps" in arguments:
        outputs["next_steps"] = arguments["next_steps"]
    if "lessons_learned" in arguments:
        outputs["lessons_learned"] = arguments["lessons_learned"]
    return PlaybookFinishAction(final_thought=arguments["message"], outputs=outputs)


def _handle_note_tool(arguments: dict) -> AgentThinkAction:
    """Handle NOTE_TOOL: store key→value in .forge/agent_notes.json (native)."""
    key = arguments.get("key", "")
    value = arguments.get("value", "")
    if not key:
        from backend.core.exceptions import FunctionCallValidationError as _E

        raise _E('Missing required argument "key" in tool call note')
    return build_note_action(key, value)


def _handle_recall_tool(arguments: dict) -> AgentThinkAction:
    """Handle RECALL_TOOL: retrieve key from .forge/agent_notes.json (native)."""
    key = arguments.get("key", "all")
    return build_recall_action(key)


def _handle_semantic_recall_tool(arguments: dict) -> AgentThinkAction:
    """Handle SEMANTIC_RECALL_TOOL: query vector memory for related context.

    Returns results tagged as [SEMANTIC_RECALL_RESULT] so the LLM can
    distinguish retrieved data from its own reasoning.
    """
    query = arguments.get("query", "")
    if not query:
        raise FunctionCallValidationError(
            'Missing required argument "query" in tool call semantic_recall'
        )
    k = min(int(arguments.get("k", 5)), 10)
    recall_fn = _semantic_recall_registry.get("fn")
    if recall_fn is None:
        return AgentThinkAction(
            thought="[SEMANTIC_RECALL_RESULT] Vector memory is not available in this session."
        )
    results = recall_fn(query, k)
    if not results:
        return AgentThinkAction(
            thought=f"[SEMANTIC_RECALL_RESULT] No results found for query: {query!r}"
        )
    parts = [f"[SEMANTIC_RECALL_RESULT] {len(results)} results for query: {query!r}\n"]
    for i, item in enumerate(results, 1):
        content = item.get("content_text", item.get("content", ""))
        role = item.get("role", "unknown")
        score = item.get("score", "")
        score_str = f" (score={score:.3f})" if isinstance(score, float) else ""
        parts.append(f"  [{i}] ({role}{score_str}) {content[:500]}")
    return AgentThinkAction(thought="\n".join(parts))


def _handle_run_tests_tool(arguments: dict) -> CmdRunAction:
    """Handle RUN_TESTS_TOOL: run pytest and return structured JSON results."""
    filter_str = arguments.get("filter", "")
    extra_flags = arguments.get("extra_flags", "")
    return build_run_tests_action(filter_str=filter_str, extra_flags=extra_flags)


def _handle_apply_patch_tool(arguments: dict) -> CmdRunAction:
    """Handle APPLY_PATCH_TOOL: apply a unified diff to the workspace."""
    if "patch" not in arguments:
        from backend.core.exceptions import FunctionCallValidationError as _E

        raise _E('Missing required argument "patch" in tool call apply_patch')
    check_only = arguments.get("check_only", "false") == "true"
    return build_apply_patch_action(patch=arguments["patch"], check_only=check_only)


def _handle_search_code_tool(arguments: dict) -> CmdRunAction:
    """Handle SEARCH_CODE_TOOL: fast code search via ripgrep/grep."""
    return build_search_code_action(
        pattern=arguments.get("pattern", ""),
        path=arguments.get("path", "."),
        file_pattern=arguments.get("file_pattern", ""),
        context_lines=arguments.get("context_lines", 2),
        case_sensitive=arguments.get("case_sensitive", "false"),
        max_results=arguments.get("max_results", 50),
    )


def _handle_web_search_tool(arguments: dict) -> CmdRunAction:
    """Handle WEB_SEARCH_TOOL: search the web for information."""
    query = arguments.get("query", "")
    if not query:
        raise FunctionCallValidationError(
            'Missing required argument "query" in tool call web_search'
        )
    num_results = int(arguments.get("num_results", 5))
    return build_web_search_action(query=query, num_results=num_results)


def _handle_web_reader_tool(arguments: dict) -> CmdRunAction:
    """Handle WEB_READER_TOOL: read webpage content."""
    url = arguments.get("url", "")
    if not url:
        raise FunctionCallValidationError(
            'Missing required argument "url" in tool call web_reader'
        )
    return build_web_reader_action(url=url)


def _handle_workspace_status_tool(arguments: dict) -> CmdRunAction:
    """Handle workspace_status tool: gather project state snapshot."""
    return build_workspace_status_action(arguments)


def _handle_error_patterns_tool(arguments: dict) -> AgentThinkAction:
    """Handle error_patterns tool: store/query error→solution patterns."""
    return build_error_patterns_action(arguments)


def _handle_checkpoint_tool(arguments: dict) -> AgentThinkAction:
    """Handle checkpoint tool: save/view progress checkpoints."""
    return build_checkpoint_action(arguments)


def _handle_project_map_tool(arguments: dict) -> CmdRunAction | AgentThinkAction:
    """Handle project_map tool: structural overview of the workspace."""
    return build_project_map_action(arguments)


def _handle_session_diff_tool(arguments: dict) -> CmdRunAction:
    """Handle session_diff tool: show cumulative changes in the session."""
    return build_session_diff_action(arguments)


def _handle_verify_state_tool(arguments: dict) -> AgentThinkAction:
    """Handle verify_state tool: validate file assertions before editing."""
    return build_verify_state_action(arguments)


def _handle_working_memory_tool(arguments: dict) -> AgentThinkAction:
    """Handle working_memory tool: structured cognitive workspace."""
    return build_working_memory_action(arguments)


def _handle_llm_based_file_edit_tool(arguments: dict) -> FileEditAction:
    """Handle LLMBasedFileEditTool tool call."""
    tool_name = create_llm_based_edit_tool()["function"]["name"]
    if "path" not in arguments:
        msg = f'Missing required argument "path" in tool call {tool_name}'
        raise FunctionCallValidationError(
            msg,
        )
    if "content" not in arguments:
        msg = f'Missing required argument "content" in tool call {tool_name}'
        raise FunctionCallValidationError(
            msg,
        )
    action = FileEditAction(
        path=arguments["path"],
        content=arguments["content"],
        start=arguments.get("start", 1),
        end=arguments.get("end", -1),
        impl_source=arguments.get("impl_source", FileEditSource.LLM_BASED_EDIT),
    )
    set_security_risk(action, arguments)
    return action


def _validate_str_replace_editor_args(arguments: dict) -> tuple[str, str]:
    """Validate required arguments for str_replace_editor tool."""
    tool_name = create_str_replace_editor_tool()["function"]["name"]
    if "command" not in arguments:
        msg = f'Missing required argument "command" in tool call {tool_name}'
        raise FunctionCallValidationError(msg)
    if "path" not in arguments:
        msg = f'Missing required argument "path" in tool call {tool_name}'
        raise FunctionCallValidationError(msg)
    return arguments["path"], arguments["command"]


def _filter_valid_editor_kwargs(other_kwargs: dict) -> dict:
    """Filter and validate kwargs for file editor."""
    str_replace_editor_tool = create_str_replace_editor_tool()
    valid_params = set(
        str_replace_editor_tool["function"]["parameters"]["properties"].keys()
    )
    valid_kwargs_for_editor = {}
    tool_name = str_replace_editor_tool["function"]["name"]

    for key, value in other_kwargs.items():
        if key not in valid_params:
            msg = f"Unexpected argument {key} in tool call {tool_name}. Allowed arguments are: {valid_params}"
            raise FunctionCallValidationError(
                msg,
            )
        if key != "security_risk":
            valid_kwargs_for_editor[key] = value
    return valid_kwargs_for_editor


def _normalize_whitespace(text: str) -> str:
    """Normalize whitespace for fuzzy matching: strip trailing spaces and unify indent chars."""
    lines = text.splitlines(keepends=True)
    normalized = []
    for line in lines:
        stripped = line.rstrip(" \t")
        stripped = stripped.replace("\t", "    ")
        normalized.append(stripped)
    return "".join(normalized)


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
        return None, "No match found even with whitespace normalization."
    if count > 1:
        return (
            None,
            f"Whitespace-normalized old_str matches {count} locations — must be unique.",
        )

    norm_start = norm_content.index(norm_old)
    norm_end = norm_start + len(norm_old)

    orig_start = _map_normalized_offset_to_original(file_content, norm_start)
    orig_end = _map_normalized_offset_to_original(file_content, norm_end)

    new_content = file_content[:orig_start] + new_str + file_content[orig_end:]
    return new_content, None


def _map_normalized_offset_to_original(original: str, norm_offset: int) -> int:
    """Map a character offset in normalized text back to the original text."""
    norm_pos = 0
    orig_pos = 0
    while norm_pos < norm_offset and orig_pos < len(original):
        ch = original[orig_pos]
        if ch == "\t":
            norm_pos += 4
        else:
            norm_pos += 1
        orig_pos += 1
        if ch in (" ", "\t"):
            while (
                orig_pos < len(original)
                and original[orig_pos] in (" ", "\t")
                and norm_pos < norm_offset
            ):
                if original[orig_pos] == "\t":
                    norm_pos += 4
                else:
                    norm_pos += 1
                orig_pos += 1
                if norm_pos >= norm_offset:
                    break
            continue
    return orig_pos


def _handle_view_and_replace(path: str, kwargs: dict) -> list[Action]:
    """Handle the compound view_and_replace command.

    Returns a list of actions: first a FileReadAction (view), then a FileEditAction (replace).
    If old_str/new_str are provided, performs the replacement; otherwise just views.
    """
    import os

    old_str = kwargs.get("old_str", "")
    new_str = kwargs.get("new_str", "")
    view_range = kwargs.get("view_range")
    normalize_ws = kwargs.get("normalize_ws", False)
    if isinstance(normalize_ws, str):
        normalize_ws = normalize_ws.lower() == "true"

    if not os.path.isfile(path):
        return [AgentThinkAction(thought=f"[VIEW_AND_REPLACE] File not found: {path}")]

    if not old_str:
        return [
            FileReadAction(
                path=path,
                impl_source=FileReadSource.FILE_EDITOR,
                view_range=view_range,
            )
        ]

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            content = f.read()
    except OSError as exc:
        return [
            AgentThinkAction(thought=f"[VIEW_AND_REPLACE] Cannot read {path}: {exc}")
        ]

    search_content = content
    if view_range and len(view_range) >= 2:
        lines = content.splitlines(keepends=True)
        start_idx = max(0, view_range[0] - 1)
        end_idx = len(lines) if view_range[1] == -1 else min(len(lines), view_range[1])
        search_content = "".join(lines[start_idx:end_idx])

    if old_str not in search_content:
        if normalize_ws:
            new_content, err = _ws_tolerant_replace(search_content, old_str, new_str)
            if err:
                return [
                    AgentThinkAction(
                        thought=f"[VIEW_AND_REPLACE] {err} Use view command to check the actual content."
                    )
                ]
        else:
            return [
                AgentThinkAction(
                    thought=f"[VIEW_AND_REPLACE] old_str not found in {path}"
                    + (
                        f" (within lines {view_range[0]}-{view_range[1]})"
                        if view_range
                        else ""
                    )
                    + ". Use view command to check the actual content."
                )
            ]

    edit_kwargs = {"old_str": old_str, "new_str": new_str}
    if normalize_ws:
        edit_kwargs["normalize_ws"] = True

    read_action = FileReadAction(
        path=path,
        impl_source=FileReadSource.FILE_EDITOR,
        view_range=view_range,
    )
    edit_action = FileEditAction(
        path=path,
        command="str_replace",
        impl_source=FileEditSource.FILE_EDITOR,
        **edit_kwargs,
    )
    return [read_action, edit_action]


def _preview_str_replace_edit(
    path: str, command: str, kwargs: dict
) -> AgentThinkAction:
    """Generate a unified diff preview of what a str_replace or insert would produce."""
    import difflib
    import os

    if not os.path.isfile(path):
        return AgentThinkAction(thought=f"[PREVIEW] File not found: {path}")

    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            original_lines = f.readlines()
    except OSError as exc:
        return AgentThinkAction(thought=f"[PREVIEW] Cannot read {path}: {exc}")

    new_lines = list(original_lines)

    if command == "str_replace":
        old_str = kwargs.get("old_str", "")
        new_str = kwargs.get("new_str", "")
        if not old_str:
            return AgentThinkAction(
                thought="[PREVIEW] old_str is required for str_replace preview"
            )
        original_text = "".join(original_lines)
        count = original_text.count(old_str)
        if count == 0:
            return AgentThinkAction(thought=f"[PREVIEW] old_str not found in {path}")
        if count > 1:
            return AgentThinkAction(
                thought=f"[PREVIEW] old_str matches {count} locations — must be unique"
            )
        new_text = original_text.replace(old_str, new_str, 1)
        new_lines = new_text.splitlines(keepends=True)
    elif command == "insert":
        insert_line = int(kwargs.get("insert_line", 0))
        new_str = kwargs.get("new_str", "")
        insert_text = new_str if new_str.endswith("\n") else new_str + "\n"
        new_lines[insert_line:insert_line] = [insert_text]

    diff = difflib.unified_diff(
        original_lines,
        new_lines,
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
        lineterm="",
    )
    diff_text = "\n".join(diff)
    if not diff_text:
        return AgentThinkAction(thought=f"[PREVIEW] No changes detected for {path}")
    return AgentThinkAction(thought=f"[PREVIEW] Dry-run diff for {path}:\n{diff_text}")


def _handle_str_replace_editor_tool(arguments: dict) -> Action | list[Action]:
    """Handle str_replace_editor tool call."""
    path, command = _validate_str_replace_editor_args(arguments)
    other_kwargs = {k: v for k, v in arguments.items() if k not in ["command", "path"]}

    # Handle confidence-based auto-preview: low confidence forces preview mode
    confidence = other_kwargs.pop("confidence", None)
    if confidence is not None and isinstance(confidence, (int, float)) and float(confidence) < 0.7:
        logger.info(
            "[confidence] Low confidence (%.2f) on %s — switching to preview mode",
            confidence,
            path,
        )
        other_kwargs.setdefault("preview", True)

    # Handle preview/dry-run mode — show what the edit would produce
    raw_preview = other_kwargs.pop("preview", False)
    preview = raw_preview is True or (
        isinstance(raw_preview, str) and raw_preview.lower() == "true"
    )
    if preview and command in ("str_replace", "insert"):
        return _preview_str_replace_edit(path, command, other_kwargs)

    # Handle compound view_and_replace command
    if command == "view_and_replace":
        actions = _handle_view_and_replace(path, other_kwargs)
        if len(actions) == 1:
            return actions[0]
        return actions[0]

    # Handle view command separately
    if command == "view":
        return FileReadAction(
            path=path,
            impl_source=FileReadSource.FILE_EDITOR,
            view_range=other_kwargs.get("view_range"),
        )

    # Remove view_range for standard edit commands (unless it's str_replace with view_range for scoping)
    view_range = other_kwargs.pop("view_range", None)

    # Filter valid editor kwargs
    valid_kwargs_for_editor = _filter_valid_editor_kwargs(other_kwargs)

    # For str_replace with view_range, pass it along for line-range scoping
    if command == "str_replace" and view_range is not None:
        valid_kwargs_for_editor["view_range"] = view_range

    # Create and configure action
    action = FileEditAction(
        path=path,
        command=command,
        impl_source=FileEditSource.FILE_EDITOR,
        **valid_kwargs_for_editor,
    )
    set_security_risk(action, arguments)
    return action


def _handle_check_tool_status_tool(
    arguments: dict, mcp_tools: dict[str, Any]
) -> AgentThinkAction:
    """Handle check_tool_status tool call."""
    return build_check_tool_status_action(arguments, mcp_tools)


def _handle_think_tool(arguments: dict) -> AgentThinkAction:
    """Handle ThinkTool tool call."""
    if "thought" not in arguments:
        msg = f'Missing required argument "thought" in tool call {create_think_tool()["function"]["name"]}'
        raise FunctionCallValidationError(
            msg,
        )
    return AgentThinkAction(thought=arguments["thought"])


def _handle_condensation_request_tool(arguments: dict) -> CondensationRequestAction:
    """Handle CondensationRequestTool tool call."""
    return CondensationRequestAction()


def _handle_task_tracker_tool(arguments: dict) -> TaskTrackingAction:
    """Handle TASK_TRACKER_TOOL tool call."""
    if "command" not in arguments:
        msg = (
            f'Missing required argument "command" in tool call {TASK_TRACKER_TOOL_NAME}'
        )
        raise FunctionCallValidationError(msg)

    command = arguments["command"]

    # Legacy command support
    if command == "plan":
        command = "update"

    if command == "update" and "task_list" not in arguments:
        msg = f'Missing required argument "task_list" for "update" command in tool call {TASK_TRACKER_TOOL_NAME}'
        raise FunctionCallValidationError(
            msg,
        )

    tracker = TaskTracker()

    # Validation/Normalization logic
    def normalize_step(s: dict, idx: int) -> dict:
        if not isinstance(s, dict):
            raise FunctionCallValidationError(
                f"Task item must be a dictionary, got {type(s)}"
            )

        # Support both old and new keys for backward compatibility during migration
        return {
            "id": s.get("id", f"step-{idx}"),
            "description": s.get("description", s.get("title", "Untitled step")),
            "status": s.get("status", "pending"),
            "result": s.get("result", s.get("notes", None)),
            "tags": s.get("tags", []),
            "subtasks": [
                normalize_step(sub, i) for i, sub in enumerate(s.get("subtasks", []))
            ],
        }

    normalized_task_list = []

    if command == "view":
        # Load from disk if viewing
        raw_task_list = tracker.load_from_file()
    else:
        # Use provided list if updating
        raw_task_list = arguments.get("task_list", [])

    if not isinstance(raw_task_list, list):
        msg = f'Invalid format for "task_list". Expected a list but got {type(raw_task_list)}.'
        raise FunctionCallValidationError(msg)

    try:
        for i, task in enumerate(raw_task_list):
            normalized_task_list.append(normalize_step(task, i + 1))
    except FunctionCallValidationError as e:
        raise e
    except Exception as e:
        logger.warning("Error normalizing task list: %s", e)
        raise FunctionCallValidationError(f"Invalid task list structure: {e}") from e

    # Persist to disk if updating
    if command == "update":
        tracker.save_to_file(normalized_task_list)

    return TaskTrackingAction(command=command, task_list=normalized_task_list)


def _handle_mcp_tool(
    tool_call_name: str, arguments: Mapping[str, Any] | None
) -> MCPAction:
    """Handle MCP tool call."""
    logger.debug(
        "Creating MCP action for tool: %s with arguments: %s", tool_call_name, arguments
    )

    # Basic validation - ensure arguments is a dict
    if isinstance(arguments, Mapping):
        normalized_args = dict(arguments)
    else:
        logger.warning("MCP tool arguments is not a mapping, got: %s", type(arguments))
        normalized_args = {}

    return MCPAction(name=tool_call_name, arguments=normalized_args)


def _validate_ultimate_editor_args(arguments: dict, tool_name: str) -> tuple[str, str]:
    """Validate required arguments for ultimate editor.

    Args:
        arguments: Tool call arguments
        tool_name: Name of the tool

    Returns:
        Tuple of (command, file_path)

    Raises:
        FunctionCallValidationError: If validation fails

    """
    if "command" not in arguments:
        raise FunctionCallValidationError(
            f'Missing required argument "command" in tool call {tool_name}'
        )

    if "file_path" not in arguments:
        raise FunctionCallValidationError(
            f'Missing required argument "file_path" in tool call {tool_name}'
        )

    return arguments["command"], arguments["file_path"]


def _handle_edit_function_command(editor, file_path: str, arguments: dict) -> Action:
    """Handle edit_function command."""
    function_name = arguments.get("function_name")
    new_body = arguments.get("new_body")

    if not function_name or not new_body:
        raise FunctionCallValidationError(
            "edit_function requires 'function_name' and 'new_body' arguments"
        )

    result = editor.edit_function(file_path, function_name, new_body)

    if result.success:
        return FileReadAction(
            path=file_path, impl_source=FileReadSource.DEFAULT, thought=result.message
        )
    return MessageAction(content=f"❌ Edit failed: {result.message}")


def _handle_rename_symbol_command(editor, file_path: str, arguments: dict) -> Action:
    """Handle rename_symbol command."""
    old_name = arguments.get("old_name")
    new_name = arguments.get("new_name")

    if not old_name or not new_name:
        raise FunctionCallValidationError(
            "rename_symbol requires 'old_name' and 'new_name' arguments"
        )

    result = editor.rename_symbol(file_path, old_name, new_name)

    if result.success:
        return FileReadAction(
            path=file_path, impl_source=FileReadSource.DEFAULT, thought=result.message
        )
    return MessageAction(content=f"❌ Rename failed: {result.message}")


def _handle_find_symbol_command(editor, file_path: str, arguments: dict) -> Action:
    """Handle find_symbol command."""
    symbol_name = arguments.get("symbol_name")
    if not symbol_name:
        raise FunctionCallValidationError("find_symbol requires 'symbol_name' argument")

    symbol_type = arguments.get("symbol_type")
    result = editor.find_symbol(file_path, symbol_name, symbol_type)

    if result:
        message = (
            f"✓ Found '{symbol_name}' in {file_path}:\n"
            f"  Type: {result.node_type}\n"
            f"  Lines: {result.line_start}-{result.line_end}"
        )
        if result.parent_name:
            message += f"\n  Parent: {result.parent_name}"
        return MessageAction(content=message)
    return MessageAction(content=f"❌ Symbol '{symbol_name}' not found in {file_path}")


def _handle_replace_range_command(editor, file_path: str, arguments: dict) -> Action:
    """Handle replace_range command."""
    start_line = arguments.get("start_line")
    end_line = arguments.get("end_line")
    new_code = arguments.get("new_code")

    if start_line is None or end_line is None or new_code is None:
        raise FunctionCallValidationError(
            "replace_range requires 'start_line', 'end_line', and 'new_code' arguments"
        )

    result = editor.replace_code_range(file_path, start_line, end_line, new_code)

    if result.success:
        return FileReadAction(
            path=file_path, impl_source=FileReadSource.DEFAULT, thought=result.message
        )
    return MessageAction(content=f"❌ Replace failed: {result.message}")


def _handle_normalize_indent_command(editor, file_path: str, arguments: dict) -> Action:
    """Handle normalize_indent command."""
    style = arguments.get("style")
    size = arguments.get("size")
    result = editor.normalize_file_indent(file_path, style, size)

    if result.success:
        return FileReadAction(
            path=file_path, impl_source=FileReadSource.DEFAULT, thought=result.message
        )
    return MessageAction(content=f"❌ Normalization failed: {result.message}")


def _handle_create_file_command(file_path: str, arguments: dict) -> Action:
    """Handle create_file command — delegates to str_replace_editor create."""
    content = arguments.get("content", "")
    return FileEditAction(
        path=file_path,
        command="create",
        file_text=content,
        impl_source=FileEditSource.FILE_EDITOR,
    )


def _handle_view_file_command(file_path: str) -> Action:
    """Handle view_file command — reads file contents."""
    return FileReadAction(path=file_path, impl_source=FileReadSource.FILE_EDITOR)


def _handle_insert_code_command(file_path: str, arguments: dict) -> Action:
    """Handle insert_code command — inserts code after a line number."""
    new_code = arguments.get("new_code")
    insert_line = arguments.get("insert_line")
    if new_code is None or insert_line is None:
        raise FunctionCallValidationError(
            "insert_code requires 'new_code' and 'insert_line' arguments"
        )
    return FileEditAction(
        path=file_path,
        command="insert",
        insert_line=int(insert_line),
        new_str=new_code,
        impl_source=FileEditSource.FILE_EDITOR,
    )


def _handle_undo_last_edit_command(file_path: str) -> Action:
    """Handle undo_last_edit command — reverts last edit to file."""
    return FileEditAction(
        path=file_path,
        command="undo_edit",
        impl_source=FileEditSource.FILE_EDITOR,
    )


def _handle_structure_editor_tool(arguments: dict) -> Action:
    """Handle StructureEditor tool call."""
    tool_name = create_structure_editor_tool()["function"]["name"]

    # Validate arguments
    command, file_path = _validate_ultimate_editor_args(arguments, tool_name)

    # Initialize editor
    try:
        from backend.engines.orchestrator.tools.structure_editor import StructureEditor

        editor = StructureEditor()
    except Exception as e:
        raise FunctionCallValidationError(
            f"Failed to initialize Structure Editor: {e}"
        ) from e

    # Command dispatch map — editor-powered commands use the StructureEditor instance
    editor_command_handlers = {
        "edit_function": _handle_edit_function_command,
        "rename_symbol": _handle_rename_symbol_command,
        "find_symbol": _handle_find_symbol_command,
        "replace_range": _handle_replace_range_command,
        "normalize_indent": _handle_normalize_indent_command,
    }
    # File I/O commands delegate directly to runtime actions (no StructureEditor needed)
    simple_command_handlers = {
        "create_file": lambda fp, args: _handle_create_file_command(fp, args),
        "view_file": lambda fp, _args: _handle_view_file_command(fp),
        "insert_code": lambda fp, args: _handle_insert_code_command(fp, args),
        "undo_last_edit": lambda fp, _args: _handle_undo_last_edit_command(fp),
    }

    # Execute command
    try:
        if command in editor_command_handlers:
            handler = editor_command_handlers[command]
            return handler(editor, file_path, arguments)
        elif command in simple_command_handlers:
            handler = simple_command_handlers[command]
            return handler(file_path, arguments)
        else:
            all_cmds = list(editor_command_handlers) + list(simple_command_handlers)
            raise FunctionCallValidationError(
                f"Unknown command '{command}' for structure_editor tool. "
                f"Valid commands: {all_cmds}"
            )

    except Exception as e:
        return MessageAction(content=f"❌ Structure Editor error: {str(e)}")


def _handle_uncertainty_tool(arguments: dict) -> Action:
    """Handle uncertainty tool — let the LLM flag doubt rather than guess."""
    from backend.events.action.agent import UncertaintyAction

    level = arguments.get("uncertainty_level", 0.5)
    thought = arguments.get("thought", "")
    concerns = arguments.get("specific_concerns", [])
    requested = arguments.get("requested_information", "")
    return UncertaintyAction(
        uncertainty_level=float(level),
        thought=thought,
        specific_concerns=list(concerns) if concerns else [],
        requested_information=requested or "",
    )


def _handle_clarification_tool(arguments: dict) -> Action:
    """Handle clarification tool — pause and surface question to user."""
    from backend.events.action.agent import ClarificationRequestAction

    question = arguments.get("question", "")
    context = arguments.get("context", "")
    options = arguments.get("options", [])
    if not question:
        raise FunctionCallValidationError(
            'Missing required argument "question" in tool call clarification'
        )
    return ClarificationRequestAction(
        question=question,
        context=context or "",
        options=list(options) if options else [],
        thought=question,
    )


def _handle_proposal_tool(arguments: dict) -> Action:
    """Handle proposal tool — present options before committing."""
    from backend.events.action.agent import ProposalAction

    options = arguments.get("options", [])
    rationale = arguments.get("rationale", "")
    recommended = arguments.get("recommended")
    if not options:
        raise FunctionCallValidationError(
            'Missing required argument "options" in tool call proposal'
        )
    return ProposalAction(
        options=list(options),
        recommended=int(recommended) if recommended is not None else 0,
        rationale=rationale or "",
        thought=rationale or "",
    )


def _handle_batch_edit_tool(arguments: dict) -> CmdRunAction:
    """Handle batch_edit tool call — atomic multi-file str_replace with rollback."""
    edits = arguments.get("edits")
    if not edits or not isinstance(edits, list):
        raise FunctionCallValidationError(
            'Missing or invalid "edits" argument in batch_edit tool call'
        )
    preview = arguments.get("preview", False)
    return build_batch_edit_action(edits, preview=bool(preview))


def _handle_escalate_tool(arguments: dict) -> Action:
    """Handle escalate_to_human tool — request human intervention."""
    from backend.events.action.agent import EscalateToHumanAction

    reason = arguments.get("reason", "")
    attempts = arguments.get("attempts_made", [])
    help_needed = arguments.get("specific_help_needed", "")
    if not reason:
        raise FunctionCallValidationError(
            'Missing required argument "reason" in tool call escalate_to_human'
        )
    return EscalateToHumanAction(
        reason=reason,
        attempts_made=list(attempts) if attempts else [],
        specific_help_needed=help_needed or "",
        thought=reason,
    )


def _create_tool_dispatch_map() -> dict[str, ToolHandler]:
    """Create dispatch map for tool handlers."""
    return {
        create_cmd_run_tool()["function"]["name"]: _handle_cmd_run_tool,
        create_finish_tool()["function"]["name"]: _handle_finish_tool,
        create_llm_based_edit_tool()["function"][
            "name"
        ]: _handle_llm_based_file_edit_tool,
        create_str_replace_editor_tool()["function"][
            "name"
        ]: _handle_str_replace_editor_tool,
        create_structure_editor_tool()["function"][
            "name"
        ]: _handle_structure_editor_tool,
        create_think_tool()["function"]["name"]: _handle_think_tool,
        create_condensation_request_tool()["function"][
            "name"
        ]: _handle_condensation_request_tool,
        TASK_TRACKER_TOOL_NAME: _handle_task_tracker_tool,
        create_note_tool()["function"]["name"]: _handle_note_tool,
        create_recall_tool()["function"]["name"]: _handle_recall_tool,
        create_semantic_recall_tool()["function"]["name"]: _handle_semantic_recall_tool,
        create_run_tests_tool()["function"]["name"]: _handle_run_tests_tool,
        create_apply_patch_tool()["function"]["name"]: _handle_apply_patch_tool,
        SEARCH_CODE_TOOL_NAME: _handle_search_code_tool,
        WEB_SEARCH_TOOL_NAME: _handle_web_search_tool,
        WEB_READER_TOOL_NAME: _handle_web_reader_tool,
        "check_tool_status": lambda args: _handle_check_tool_status_tool(
            args, {}
        ),  # Simplified for static map
        WORKSPACE_STATUS_TOOL_NAME: _handle_workspace_status_tool,
        ERROR_PATTERNS_TOOL_NAME: _handle_error_patterns_tool,
        CHECKPOINT_TOOL_NAME: _handle_checkpoint_tool,
        PROJECT_MAP_TOOL_NAME: _handle_project_map_tool,
        REVERT_TO_SAFE_STATE_TOOL_NAME: build_revert_to_safe_state_action,
        SESSION_DIFF_TOOL_NAME: _handle_session_diff_tool,
        VERIFY_STATE_TOOL_NAME: _handle_verify_state_tool,
        WORKING_MEMORY_TOOL_NAME: _handle_working_memory_tool,
        DELEGATE_TASK_TOOL_NAME: build_delegate_task_action,
        BATCH_EDIT_TOOL_NAME: _handle_batch_edit_tool,
        TERMINAL_OPEN_TOOL_NAME: build_terminal_open_action,
        TERMINAL_INPUT_TOOL_NAME: build_terminal_input_action,
        TERMINAL_READ_TOOL_NAME: build_terminal_read_action,
        # Meta-cognition tools
        UNCERTAINTY_TOOL_NAME: _handle_uncertainty_tool,
        CLARIFICATION_TOOL_NAME: _handle_clarification_tool,
        PROPOSAL_TOOL_NAME: _handle_proposal_tool,
        ESCALATE_TOOL_NAME: _handle_escalate_tool,
    }


def response_to_actions(
    response: ModelResponse,
    mcp_tool_names: list[str] | None = None,
    mcp_tools: dict[str, Any] | None = None,
) -> list[Action]:
    """Convert LLM response to agent actions."""

    def process_with_mcp_tools(tc, args):
        # Allow passing mcp_tools to specific tool handlers
        if tc.function.name == "check_tool_status":
            return _handle_check_tool_status_tool(args, mcp_tools or {})
        return _process_single_tool_call(tc, args)

    return common_response_to_actions(
        response=response,
        create_action_fn=process_with_mcp_tools,
        combine_thought_fn=combine_thought,
        mcp_tool_names=mcp_tool_names,
    )


def _process_single_tool_call(tool_call, arguments: dict[str, Any]) -> Action:
    """Process a single tool call and return the corresponding action."""
    logger.debug("Tool call in function_calling.py: %s", tool_call)
    tool_dispatch = _create_tool_dispatch_map()

    tool_name = tool_call.function.name
    mcp_tool_names = getattr(tool_call, "_mcp_tool_names", None)

    if tool_name in tool_dispatch:
        return tool_dispatch[tool_name](arguments)
    if mcp_tool_names and tool_name in mcp_tool_names:
        return _handle_mcp_tool(tool_name, arguments)
    msg = f"Tool {tool_name} is not registered. (arguments: {arguments}). Please check the tool name and retry with an existing tool."
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
    content_str = str(content) if content else ""
    return [MessageAction(content=content_str, wait_for_response=True)]
