"""Progressive tool disclosure — dynamically filter tools based on context.

Instead of presenting all ~20+ tools to the LLM on every turn, the
ToolSelector classifies tools into *core* (always present) and *contextual*
(unlocked by conditions like error count, turn number, or task complexity).

This reduces prompt token usage, prevents decision paralysis, and improves
the LLM's tool selection accuracy.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from backend.core.logger import forge_logger as logger

if TYPE_CHECKING:
    from backend.controller.state.state import State

# Tool names (must match the function names in tool definitions)
_CORE_TOOLS = frozenset(
    {
        # Execution
        "execute_bash",
        "bash",
        # File editing — all editing tools are essential for productive work
        "str_replace_editor",
        "structure_editor",
        "apply_patch",
        "batch_edit",
        # Search & navigation
        "search_code",
        "explore_tree_structure",
        "get_entity_contents",
        "project_map",
        # Reasoning
        "think",
        "finish",
        # Memory — both flat and structured memory survive condensation
        "note",
        "recall",
        "semantic_recall",
        "working_memory",
        # Testing
        "run_tests",
        # Verification
        "verify_state",
        "verify_ui_change",
        # Meta-cognition — always available for expressing uncertainty
        "uncertainty",
        "clarification",
        "proposal",
        "escalate_to_human",
        # Progress signaling for long-running tasks
        "signal_progress",
        # MCP gateway
        "call_mcp_tool",
    }
)

# Research keywords that unlock web tools
_RESEARCH_KEYWORDS = re.compile(
    r"\b(research|search|find|look up|google|documentation|docs|how to|what is|api|library|package|tutorial)\b",
    re.IGNORECASE,
)

# Multi-file edit keywords
_MULTI_FILE_KEYWORDS = re.compile(
    r"\b(refactor|rename|move|across files|multiple files|all files|project.wide|codebase)\b",
    re.IGNORECASE,
)


def _get_tool_name(tool: dict) -> str | None:
    """Extract the tool name from a ChatCompletionToolParam dict."""
    fn = tool.get("function", {})
    return fn.get("name")


def _count_recent_errors(state: State) -> int:
    """Count error observations in the last 10 events."""
    history = getattr(state, "history", [])
    if not isinstance(history, list):
        history = []
    count = 0
    for event in reversed(list(history)):
        if count >= 10:
            break
        cls_name = type(event).__name__
        if cls_name in ("ErrorObservation",):
            count += 1
        content = str(getattr(event, "content", ""))
        if "error" in content.lower() or "traceback" in content.lower():
            count += 1
    return min(count, 20)


def _count_file_edits(state: State) -> int:
    """Count file edit actions in recent history."""
    history = getattr(state, "history", [])
    if not isinstance(history, list):
        history = []
    count = 0
    for event in reversed(list(history)):
        cls_name = type(event).__name__
        if cls_name in ("FileEditAction", "FileWriteAction"):
            count += 1
    return count


def _get_current_turn(state: State) -> int:
    """Get the current iteration/turn number."""
    iter_flag = getattr(state, "iteration_flag", None)
    if iter_flag is None:
        return 0
    value = getattr(iter_flag, "current_value", 0) or 0
    try:
        return int(value)
    except Exception:
        return 0


def _get_token_usage_pct(state: State) -> float:
    """Get token usage as percentage of context window (0.0–1.0)."""
    metrics = getattr(state, "metrics", None)
    if not metrics:
        return 0.0
    # Use last turn's prompt_tokens (= actual current context size) rather
    # than accumulated totals which sum every turn and quickly exceed 1.0.
    token_usages = getattr(metrics, "token_usages", None)
    if not token_usages:
        return 0.0
    last = token_usages[-1]
    prompt_tok = getattr(last, "prompt_tokens", 0)
    ctx_window = getattr(last, "context_window", 0)
    if not ctx_window:
        return 0.0
    try:
        return float(prompt_tok) / float(ctx_window)
    except Exception:
        return 0.0


def _get_user_message_text(messages: list) -> str:
    """Extract the text of the first user message from the message list."""
    for msg in messages:
        if isinstance(msg, dict) and msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(
                    item.get("text", "")
                    for item in content
                    if isinstance(item, dict) and item.get("type") == "text"
                )
    return ""


def _compute_allowed_tools(
    *,
    turn: int,
    error_count: int,
    edit_count: int,
    token_pct: float,
    user_text: str,
    post_condensation: bool,
    is_complex_task: bool,
) -> set[str]:
    """Compute the set of tool names to include based on context."""
    allowed: set[str] = set(_CORE_TOOLS)
    allowed.add("browser")

    # Terminal tools — always available when terminal is enabled
    allowed.update(["terminal_open", "terminal_input", "terminal_read"])

    # LSP query — always available for code intelligence
    allowed.add("lsp_query")

    unlocks: list[tuple[bool, list[str]]] = [
        # Contextual tools — unlocked by specific conditions
        (turn >= 3 or is_complex_task, ["delegate_task", "blackboard"]),
        (turn >= 5, ["task_tracker"]),
        (error_count >= 2, ["error_patterns", "revert_to_safe_state"]),
        (turn >= 5, ["checkpoint"]),
        (edit_count >= 3, ["session_diff"]),
        (turn <= 1 or post_condensation, ["workspace_status"]),
        (token_pct > 0.5, ["condensation_request"]),
        (bool(_MULTI_FILE_KEYWORDS.search(user_text)), ["apply_patch"]),
        (error_count >= 1, ["check_tool_status", "query_toolbox"]),
        (
            bool(_RESEARCH_KEYWORDS.search(user_text)),
            ["web_search"],
        ),
    ]
    for condition, names in unlocks:
        if condition:
            allowed.update(names)

    return allowed


def _filter_tools_by_allowed(
    all_tools: list[dict[str, Any]], allowed: set[str]
) -> list[dict[str, Any]]:
    """Filter tools to only those in allowed set (or with unknown name), and remove duplicates."""
    selected = []
    excluded_names = []
    seen_names = set()
    for tool in all_tools:
        name = _get_tool_name(tool)
        
        # Deduplicate tools by name
        if name is not None:
            if name in seen_names:
                continue
            seen_names.add(name)
            
        if name is None or name in allowed:
            selected.append(tool)
        else:
            excluded_names.append(name)
    if excluded_names:
        logger.debug(
            "ToolSelector: excluded %d contextual tools: %s",
            len(excluded_names),
            excluded_names,
        )
    return selected


class ToolSelector:
    """Dynamically filter tools based on task context.

    Core tools are always included. Contextual tools are unlocked when
    specific conditions are met (error count, turn number, task complexity,
    keyword matches, etc.).
    """

    def __init__(self) -> None:
        self._post_condensation = False

    def notify_condensation(self) -> None:
        """Signal that condensation just occurred."""
        self._post_condensation = True

    def select_tools(
        self,
        all_tools: list[dict[str, Any]],
        state: State,
        messages: list | None = None,
    ) -> list[dict[str, Any]]:
        """Filter the full toolset to only include relevant tools.

        Args:
            all_tools: Complete list of ChatCompletionToolParam dicts
            state: Current agent state
            messages: Optional conversation messages for keyword analysis

        Returns:
            Filtered list of tool dicts
        """
        turn = _get_current_turn(state)
        error_count = _count_recent_errors(state)
        edit_count = _count_file_edits(state)
        token_pct = _get_token_usage_pct(state)
        user_text = _get_user_message_text(messages or [])

        allowed = _compute_allowed_tools(
            turn=turn,
            error_count=error_count,
            edit_count=edit_count,
            token_pct=token_pct,
            user_text=user_text,
            post_condensation=self._post_condensation,
            is_complex_task=self._is_complex_task(user_text),
        )
        if turn <= 1 or self._post_condensation:
            self._post_condensation = False

        return _filter_tools_by_allowed(all_tools, allowed)

    @staticmethod
    def _is_complex_task(text: str) -> bool:
        """Heuristic: task has multiple action verbs indicating multi-step work."""
        action_verbs = re.findall(
            r"\b(create|write|edit|modify|delete|remove|fix|implement"
            r"|add|update|change|build|run|install|refactor|test|debug)\b",
            text,
            re.IGNORECASE,
        )
        return len(action_verbs) >= 3
