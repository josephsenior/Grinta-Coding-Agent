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

from backend.core.logger import FORGE_logger as logger

if TYPE_CHECKING:
    from backend.controller.state.state import State

# Tool names (must match the function names in tool definitions)
_CORE_TOOLS = frozenset({
    # Execution
    "execute_bash",
    "bash",
    # File editing
    "str_replace_editor",
    "structure_editor",
    # Search & navigation
    "search_code",
    "project_map",
    # Reasoning
    "think",
    "finish",
    # Memory — lightweight
    "note",
    "recall",
    "semantic_recall",
    # Testing
    "run_tests",
    # Verification
    "verify_state",
    # Task tracking
    "task_tracker",
})

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
    atu = getattr(metrics, "accumulated_token_usage", None)
    if not atu:
        return 0.0
    prompt_tok = getattr(atu, "prompt_tokens", 0)
    ctx_window = getattr(atu, "context_window", 0)
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

        # Build the set of tool names to include
        allowed: set[str] = set(_CORE_TOOLS)

        # --- Contextual unlocks ---

        # Working memory: unlock after 3+ turns or on complex tasks
        if turn >= 3 or self._is_complex_task(user_text):
            allowed.add("working_memory")

        # Error patterns: unlock after 2+ errors
        if error_count >= 2:
            allowed.add("error_patterns")

        # Checkpoint: unlock after 5+ turns
        if turn >= 5:
            allowed.add("checkpoint")

        # Session diff: unlock after 3+ file edits
        if edit_count >= 3:
            allowed.add("session_diff")

        # Workspace status: unlock on first turn or after condensation
        if turn <= 1 or self._post_condensation:
            allowed.add("workspace_status")
            self._post_condensation = False

        # Condensation request: unlock when token budget is >50% (early access prevents surprise condensation)
        if token_pct > 0.5:
            allowed.add("condensation_request")

        # Apply patch: unlock on multi-file edit tasks
        if _MULTI_FILE_KEYWORDS.search(user_text):
            allowed.add("apply_patch")

        # Web tools: unlock when task has research keywords
        if _RESEARCH_KEYWORDS.search(user_text):
            allowed.add("web_search")
            allowed.add("web_reader")

        # Always unlock browsing tool if the full toolset has it
        allowed.add("browser")

        # --- Filter the actual tool list ---
        selected = []
        excluded_names = []
        for tool in all_tools:
            name = _get_tool_name(tool)
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
