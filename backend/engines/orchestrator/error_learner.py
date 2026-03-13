"""Session error tracking and recovery mechanisms."""

from collections import defaultdict
from dataclasses import dataclass

# ── Recovery suggestions: (tool_name, error_substring) → hint ──────────
_RECOVERY_MAP: list[tuple[str, str, str]] = [
    (
        "str_replace_editor",
        "no match",
        "Use view_file first to see current content, or use structure_editor's "
        "find_symbol to locate the target by name.",
    ),
    (
        "str_replace_editor",
        "multiple occurrences",
        "Add more surrounding context lines to make the match unique, "
        "or use structure_editor's edit_function to target by symbol name.",
    ),
    (
        "structure_editor",
        "not found",
        "Use structure_editor's find_symbol to list available symbols, "
        "or check the file path is correct.",
    ),
    (
        "cmd_run",
        "not found",
        "Check working directory and PATH. Use workspace_status() to confirm.",
    ),
    (
        "cmd_run",
        "permission denied",
        "The command lacks permissions. Try a different approach or check file ownership.",
    ),
    (
        "bash",
        "not found",
        "Check working directory and PATH. Use workspace_status() to confirm.",
    ),
    (
        "file_editor",
        "not found",
        "Use find_file or project_map to locate the correct file path.",
    ),
    (
        "web_search",
        "timeout",
        "Network may be unreliable. Try again or use local codebase search instead.",
    ),
]


@dataclass
class ToolFailure:
    """A single recorded tool call failure within the current session."""

    tool_name: str
    error_summary: str  # first 200 chars of error, lowered
    turn_index: int


class SessionErrorLearner:
    """Tracks tool failures within a conversation and generates actionable hints.

    Lives on the Planner — session-scoped, no cross-session persistence.
    Designed to be lightweight and LLM-agnostic.
    """

    def __init__(self) -> None:
        self._failures: list[ToolFailure] = []
        self._resolved: set[str] = set()  # hypothesis keys that were resolved
        self._success_after_failure: dict[str, int] = {}  # tool_name → turn of success

    def record_failure(
        self, tool_name: str, error_msg: str, turn_index: int
    ) -> None:
        """Record a tool call failure."""
        summary = error_msg[:200].lower().strip()
        self._failures.append(
            ToolFailure(tool_name=tool_name, error_summary=summary, turn_index=turn_index)
        )

    def record_success(self, tool_name: str, turn_index: int) -> None:
        """Record a tool call success — may resolve an active hypothesis."""
        key = f"repeated:{tool_name}"
        if key not in self._resolved and self._count_failures(tool_name) >= 2:
            self._resolved.add(key)
            self._success_after_failure[tool_name] = turn_index

    def get_hypotheses(self, max_hints: int = 3) -> list[str]:
        """Analyze recorded failures and return actionable hypothesis hints."""
        if not self._failures:
            return []

        hints: list[str] = []

        # Group failures by tool name
        by_tool: dict[str, list[ToolFailure]] = defaultdict(list)
        for f in self._failures:
            by_tool[f.tool_name].append(f)

        # ── Hypothesis 1: Same tool, same/similar error ≥ 2x ──────────
        for tool, fails in by_tool.items():
            key = f"repeated:{tool}"
            if key in self._resolved:
                continue
            if len(fails) < 2:
                continue

            # Check if errors are similar (share first 60 chars)
            error_groups: dict[str, int] = defaultdict(int)
            for f in fails:
                prefix = f.error_summary[:60]
                error_groups[prefix] += 1

            for prefix, count in error_groups.items():
                if count >= 2:
                    recovery = self._lookup_recovery(tool, prefix)
                    base = (
                        f"'{tool}' has failed {count}x with similar errors."
                    )
                    hint = f"LEARNED: {base} {recovery}" if recovery else f"LEARNED: {base} Try a different approach or tool."
                    hints.append(hint)
                    break  # one hint per tool

        # ── Hypothesis 2: Multiple tools fail on the same file ─────────
        file_failures: dict[str, set[str]] = defaultdict(set)
        for f in self._failures:
            # Extract file paths from error messages
            for token in f.error_summary.split():
                if "/" in token or "\\" in token:
                    cleaned = token.strip("':\"(),")
                    if cleaned:
                        file_failures[cleaned].add(f.tool_name)
        for path, tools in file_failures.items():
            if len(tools) >= 2:
                hints.append(
                    f"LEARNED: Multiple tools ({', '.join(sorted(tools))}) "
                    f"failed on '{path}'. Check if the file exists and is readable."
                )
                break  # one hint for file issues

        # ── Hypothesis 3: All command executions failing → env issue ───
        cmd_tools = {"cmd_run", "bash", "execute_bash", "run_command"}
        cmd_fails = sum(1 for f in self._failures if f.tool_name in cmd_tools)
        if cmd_fails >= 3 and "env_issue" not in self._resolved:
            hints.append(
                "LEARNED: Multiple command executions have failed. "
                "This may indicate an environment issue (wrong directory, "
                "missing dependency, network). Use workspace_status() to diagnose."
            )

        return hints[:max_hints]

    def _count_failures(self, tool_name: str) -> int:
        """Count failures for a specific tool."""
        return sum(1 for f in self._failures if f.tool_name == tool_name)

    def _lookup_recovery(self, tool_name: str, error_prefix: str) -> str:
        """Look up a recovery suggestion from the static recovery map."""
        for map_tool, map_pattern, suggestion in _RECOVERY_MAP:
            if map_tool == tool_name and map_pattern in error_prefix:
                return suggestion
        return ""
