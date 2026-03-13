from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from backend.llm.llm_utils import check_tools
from backend.llm.catalog_loader import (
    prefers_short_tool_descriptions,
    supports_tool_choice,
)
from backend.engines.orchestrator.tools.verify_ui import create_verify_ui_change_tool

ChatCompletionToolParam = Any

if TYPE_CHECKING:
    from backend.controller.state.state import State
    from backend.llm.llm import LLM

    from .safety import OrchestratorSafetyManager


PLAIN_CHAT_PATTERNS = [
    r"^\s*(hi|hello|hey)\b",
    r"\b(say|reply with)\s+(hello|hi|hey)\b",
    r"\b(thanks|thank you)\b",
    r"\bhow are you\b",
    r"\bwho are you\b",
]

# Markers that appear only in system-injected user messages (workspace context,
# playbook knowledge, knowledge-base results) — never in human-typed messages.
_INJECTED_MSG_MARKERS = (
    "<RUNTIME_INFORMATION>",
    "<REPOSITORY_INFO>",
    "<REPOSITORY_INSTRUCTIONS>",
    "<CONVERSATION_INSTRUCTIONS>",
    "<EXTRA_INFO>",
)

logger = logging.getLogger(__name__)

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


def _get_last_user_text_from_messages(messages: list) -> str:
    """Extract text from the last user message."""
    for msg in reversed(messages):
        if not isinstance(msg, dict) or msg.get("role") != "user":
            continue
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


class OrchestratorPlanner:
    """Assembles tools, messages, and LLM request payloads for Orchestrator."""

    def __init__(
        self,
        config,
        llm: LLM,
        safety_manager: OrchestratorSafetyManager,
        agent: Any = None,
    ) -> None:
        self._config = config
        self._llm = llm
        self._safety = safety_manager
        self._agent = agent
        # Lazy cache for check_tools output (model-scoped)
        self._checked_tools_cache: list[ChatCompletionToolParam] | None = None
        self._checked_tools_model: str | None = None
        # Progressive tool disclosure
        from backend.engines.orchestrator.tool_selector import ToolSelector

        self._tool_selector = ToolSelector()
        self._tools_used_this_session: set[str] = set()
        # Within-conversation error learning
        self._error_learner = SessionErrorLearner()

    # ------------------------------------------------------------------ #
    # Tool assembly
    # ------------------------------------------------------------------ #
    def build_toolset(self) -> list[ChatCompletionToolParam]:
        use_short_desc = self._should_use_short_tool_descriptions()
        tools: list[ChatCompletionToolParam] = []

        self._add_core_tools(tools, use_short_desc)
        self._add_browsing_tool(tools)
        self._add_editor_tools(tools, use_short_desc)
        self._add_mcp_gateway_tool(tools)

        # Invalidate cached checked-tools when toolset is rebuilt
        self._checked_tools_cache = None
        return tools

    def _should_use_short_tool_descriptions(self) -> bool:
        if not self._llm:
            return False
        try:
            return prefers_short_tool_descriptions(self._llm.config.model)
        except Exception:
            return False

    def _add_core_tools(self, tools: list, use_short_tool_desc: bool) -> None:
        self._add_basic_tools(tools, use_short_tool_desc)
        self._add_edit_and_search_tools(tools)
        self._add_terminal_and_special_tools(tools)

    def _add_basic_tools(self, tools: list, use_short_tool_desc: bool) -> None:
        """Add cmd, think, finish, condensation_request, note, recall, run_tests tools."""
        from backend.engines.orchestrator.tools.bash import create_cmd_run_tool
        from backend.engines.orchestrator.tools.condensation_request import (
            create_condensation_request_tool,
        )
        from backend.engines.orchestrator.tools.finish import create_finish_tool
        from backend.engines.orchestrator.tools.think import create_think_tool
        from backend.engines.orchestrator.tools.note import (
            create_note_tool,
            create_recall_tool,
            create_semantic_recall_tool,
        )
        from backend.engines.orchestrator.tools.run_tests import create_run_tests_tool

        if getattr(self._config, "enable_cmd", True):
            tools.append(create_cmd_run_tool(use_short_description=use_short_tool_desc))
        if getattr(self._config, "enable_think", True):
            tools.append(create_think_tool())
        if getattr(self._config, "enable_finish", True):
            tools.append(create_finish_tool())
        if getattr(self._config, "enable_condensation_request", False):
            tools.append(create_condensation_request_tool())
        if getattr(self._config, "enable_note", True):
            tools.append(create_note_tool())
            tools.append(create_recall_tool())
            tools.append(create_semantic_recall_tool())
        if getattr(self._config, "enable_run_tests", True):
            tools.append(create_run_tests_tool())

    def _add_edit_and_search_tools(self, tools: list) -> None:
        """Add apply_patch, batch_edit, task_tracker, search_code, explore_code tools."""
        from backend.engines.orchestrator.tools.apply_patch import (
            create_apply_patch_tool,
        )
        from backend.engines.orchestrator.tools.batch_edit import create_batch_edit_tool
        from backend.engines.orchestrator.tools.task_tracker import (
            create_task_tracker_tool,
        )
        from backend.engines.orchestrator.tools.query_toolbox import (
            create_query_toolbox_tool,
        )
        from backend.engines.orchestrator.tools.search_code import (
            create_search_code_tool,
        )
        from backend.engines.orchestrator.tools.explore_code import (
            create_explore_tree_structure_tool,
            create_get_entity_contents_tool,
        )

        if getattr(self._config, "enable_apply_patch", True):
            tools.append(create_apply_patch_tool())
            tools.append(create_batch_edit_tool())
        if getattr(self._config, "enable_internal_task_tracker", True):
            tools.append(create_query_toolbox_tool())
            tools.append(create_task_tracker_tool())
        if getattr(self._config, "enable_search_code", True):
            tools.append(create_search_code_tool())
            tools.append(create_explore_tree_structure_tool())
            tools.append(create_get_entity_contents_tool())

    def _add_terminal_and_special_tools(self, tools: list) -> None:
        """Add terminal, optional feature tools (web search, delegate, etc.), and meta-cognition tools."""
        self._add_terminal_tools(tools)
        self._add_optional_feature_tools(tools)
        self._add_meta_cognition_tools(tools)

    def _add_terminal_tools(self, tools: list) -> None:
        """Add terminal open/input/read tools when terminal support is enabled."""
        if getattr(self._config, "enable_terminal", True):
            from backend.engines.orchestrator.tools.terminal import (
                create_terminal_open_tool,
                create_terminal_input_tool,
                create_terminal_read_tool,
            )

            tools.append(create_terminal_open_tool())
            tools.append(create_terminal_input_tool())
            tools.append(create_terminal_read_tool())

    def _add_optional_feature_tools(self, tools: list) -> None:
        """Add check_tool_status, web_search, delegate, rollback, workspace_status, etc."""
        from backend.engines.orchestrator.tools.check_tool_status import (
            create_check_tool_status_tool,
        )
        from backend.engines.orchestrator.tools.delegate_task import (
            create_delegate_task_tool,
        )
        from backend.engines.orchestrator.tools.revert_to_safe_state import (
            create_revert_to_safe_state_tool,
        )
        from backend.engines.orchestrator.tools.lsp_query import create_lsp_query_tool
        from backend.engines.orchestrator.tools.signal_progress import (
            create_signal_progress_tool,
        )

        if getattr(self._config, "enable_check_tool_status", False):
            tools.append(create_check_tool_status_tool())
        if getattr(self._config, "enable_web_search", False):
            from backend.engines.orchestrator.tools.web_search import (
                create_web_search_tool,
            )

            tools.append(create_web_search_tool())

        # New core tools — gated by flags (default off to reduce tool bloat)
        if getattr(self._config, "enable_lsp_query", False):
            tools.append(create_lsp_query_tool())
        if getattr(self._config, "enable_signal_progress", False):
            tools.append(create_signal_progress_tool())
        if getattr(self._config, "enable_swarming", False):
            tools.append(create_delegate_task_tool())

        from backend.engines.orchestrator.tools.blackboard import create_blackboard_tool
        if getattr(self._config, "enable_blackboard", False):
            tools.append(create_blackboard_tool())
        if getattr(self._config, "enable_rollback", False):
            tools.append(create_revert_to_safe_state_tool())
        self._add_lazy_import_tools(
            tools,
            [
                (
                    "enable_workspace_status",
                    False,
                    "workspace_status",
                    "create_workspace_status_tool",
                ),
                (
                    "enable_error_patterns",
                    False,
                    "error_patterns",
                    "create_error_patterns_tool",
                ),
                ("enable_checkpoints", False, "checkpoint", "create_checkpoint_tool"),
                ("enable_project_map", False, "project_map", "create_project_map_tool"),
                (
                    "enable_session_diff",
                    False,
                    "session_diff",
                    "create_session_diff_tool",
                ),
                (
                    "enable_working_memory",
                    False,
                    "working_memory",
                    "create_working_memory_tool",
                ),
                (
                    "enable_verify_state",
                    False,
                    "verify_state",
                    "create_verify_state_tool",
                ),
            ],
        )

    def _add_lazy_import_tools(
        self, tools: list, specs: list[tuple[str, bool, str, str]]
    ) -> None:
        """Add tools from module/factory pairs when config enables them.

        specs: list of (config_key, default, module_name, factory_name).
        """
        for config_key, default, module_name, factory_name in specs:
            if getattr(self._config, config_key, default):
                mod = __import__(
                    f"backend.engines.orchestrator.tools.{module_name}",
                    fromlist=[factory_name],
                )
                tools.append(getattr(mod, factory_name)())

    def _add_meta_cognition_tools(self, tools: list) -> None:
        """Add uncertainty, clarification, escalate, proposal tools when meta-cognition is enabled."""
        if getattr(self._config, "enable_meta_cognition", False):
            from backend.engines.orchestrator.tools.meta_cognition import (
                create_uncertainty_tool,
                create_clarification_tool,
                create_escalate_tool,
                create_proposal_tool,
            )

            tools.append(create_uncertainty_tool())
            tools.append(create_clarification_tool())
            tools.append(create_escalate_tool())
            tools.append(create_proposal_tool())

    def _add_browsing_tool(self, tools: list) -> None:
        if getattr(self._config, "enable_browsing", False):
            # We now rely on external MCP (like browser-use)
            pass

        if getattr(self._config, "enable_verify_ui_change", False):
            tools.append(create_verify_ui_change_tool())

    def _add_editor_tools(self, tools: list, use_short_tool_desc: bool) -> None:
        if getattr(self._config, "enable_editor", True):
            from backend.engines.orchestrator.tools import (
                create_str_replace_editor_tool,
                create_structure_editor_tool,
            )

            # Primary editor: str_replace_editor for targeted line-level edits
            tools.append(
                create_str_replace_editor_tool(
                    use_short_description=use_short_tool_desc
                )
            )
            # Advanced editor: structure_editor (tree-sitter AST) for symbol-level refactoring
            tools.append(
                create_structure_editor_tool(use_short_description=use_short_tool_desc)
            )

    def _add_mcp_gateway_tool(self, tools: list) -> None:
        """Add the MCP gateway proxy tool when MCP is enabled.

        The gateway replaces injecting 50+ individual MCP tool schemas.
        Available MCP tool names are listed in the system prompt instead.
        """
        if getattr(self._config, "enable_mcp", True):
            from backend.engines.orchestrator.tools.mcp_gateway import (
                create_mcp_gateway_tool,
            )
            tools.append(create_mcp_gateway_tool())

    def record_tool_used(self, tool_name: str) -> None:
        """Record that a tool was used this session (for description tiers)."""
        self._tools_used_this_session.add(tool_name)

    @property
    def tool_selector(self):
        """Expose the tool selector for external notification (e.g. condensation)."""
        return self._tool_selector

    def build_llm_params(
        self,
        messages: list,
        state: State,
        tools: list[ChatCompletionToolParam],
    ) -> dict:
        last_user_msg = self._get_last_user_message(messages) or ""
        tool_choice = self._determine_tool_choice(messages, state)
        disable_tools_for_turn = self._is_plain_chat_request(last_user_msg)

        # NOTE: We inject control/status messages *after* tool selection so
        # tool selection heuristics see the original user/assistant content.

        # Progressive tool disclosure: filter tools based on context
        if disable_tools_for_turn:
            tools = []
        elif getattr(self._config, "enable_progressive_tools", True):
            tools = self._tool_selector.select_tools(tools, state, messages)

        # Apply three-tier tool descriptions
        tools = self._apply_description_tiers(tools)

        # Cache check_tools output — only recompute when tools or model changes
        # Invalidate cache when tool selection changes the list
        current_model = self._llm.config.model if self._llm else ""
        tool_fingerprint = ",".join(
            t.get("function", {}).get("name", "") for t in tools
        )
        cache_key = f"{current_model}:{tool_fingerprint}"
        if self._checked_tools_cache is None or self._checked_tools_model != cache_key:
            self._checked_tools_cache = check_tools(tools, self._llm.config)
            self._checked_tools_model = cache_key

        messages = self._inject_turn_status(messages, state)

        params: dict[str, Any] = {
            "messages": messages,
            "tools": self._checked_tools_cache,
            "stream": True,
        }

        if tool_choice and self._llm_supports_tool_choice():
            params["tool_choice"] = tool_choice

        params["extra_body"] = {
            "metadata": state.to_llm_metadata(
                model_name=self._llm.config.model,
                agent_name=getattr(state, "agent_name", "Orchestrator"),
            )
        }
        return params

    def _apply_description_tiers(self, tools: list) -> list:
        """Apply three-tier tool descriptions to reduce prompt tokens.

        - Tier 1 (minimal): Tool was used this session — trim description
        - Tier 2 (short):   Tool is available but not used — keep one-line
        - Tier 3 (full):    Default — full description (no change)

        For now, tools that have been used get a trimmed description since
        the LLM already knows what they do from prior invocations.
        """
        if not self._tools_used_this_session:
            return tools

        result = []
        for tool in tools:
            fn = tool.get("function", {})
            name = fn.get("name", "")
            if name in self._tools_used_this_session:
                # Tier 1: minimal description for already-used tools
                desc = fn.get("description", "")
                if len(desc) > 80:
                    # Keep only the first sentence
                    first_sentence = desc.split(".")[0] + "."
                    trimmed = {
                        **tool,
                        "function": {**fn, "description": first_sentence},
                    }
                    result.append(trimmed)
                    continue
            result.append(tool)
        return result

    def _inject_turn_status(self, messages: list, state: State) -> list:
        """Inject a dedicated control/status message for the current turn.

        High-quality behavior:
        - Does not mutate user message content.
        - Retry-safe: does not destructively consume signals while building prompts.
        - Structured tags allow stable parsing/heuristics.
        """
        iter_flag = getattr(state, "iteration_flag", None)
        if iter_flag is None:
            return messages
        current = getattr(iter_flag, "current_value", None)
        if current is None:
            return messages
        max_val = getattr(iter_flag, "max_value", None)

        # Build context status block
        parts = [f"turn={current}" + (f"/{max_val}" if max_val else "")]

        # Token usage from metrics
        metrics = getattr(state, "metrics", None)
        if metrics:
            atu = getattr(metrics, "accumulated_token_usage", None)
            if atu:
                prompt_tok = getattr(atu, "prompt_tokens", 0)
                comp_tok = getattr(atu, "completion_tokens", 0)
                ctx_window = getattr(atu, "context_window", 0)
                try:
                    prompt_tok = int(prompt_tok)
                except Exception:
                    prompt_tok = 0
                try:
                    comp_tok = int(comp_tok)
                except Exception:
                    comp_tok = 0
                try:
                    ctx_window = int(ctx_window)
                except Exception:
                    ctx_window = 0
                if prompt_tok or comp_tok:
                    parts.append(f"tokens_used={prompt_tok + comp_tok}")
                if ctx_window:
                    parts.append(f"context_window={ctx_window}")

            # Budget info
            cost = getattr(metrics, "accumulated_cost", 0.0)
            budget = getattr(metrics, "max_budget_per_task", None)
            try:
                cost = float(cost)
            except Exception:
                cost = 0.0
            try:
                budget_val = float(budget) if budget is not None else None
            except Exception:
                budget_val = None

            if cost > 0:
                budget_str = f"cost=${cost:.4f}"
                if budget_val is not None:
                    budget_str += f"/${budget_val:.2f}"
                parts.append(budget_str)

        # History event count
        history = getattr(state, "history", [])
        if history:
            parts.append(f"history_events={len(history)}")

        # Turn signals (typed), with fallbacks for older sessions.
        planning_directive = None
        memory_pressure = None

        ts = getattr(state, "turn_signals", None)
        if ts is not None:
            planning_directive = getattr(ts, "planning_directive", None)
            memory_pressure = getattr(ts, "memory_pressure", None)

        extra_data = getattr(state, "extra_data", {})
        if planning_directive is None:
            planning_directive = extra_data.get("planning_directive")
        if memory_pressure is None:
            memory_pressure = extra_data.get("memory_pressure")

        if memory_pressure:
            parts.append(f"memory_pressure={memory_pressure}")

        # Repetition score — proactive stuck proximity signal
        rep_score = 0.0
        if ts is not None:
            rep_score = getattr(ts, "repetition_score", 0.0)
        if rep_score and rep_score >= 0.45:
            parts.append(f"repetition_score={rep_score:.1f}")

        # Proactive context pressure warning at ~70% token usage
        context_pressure_warning = ""
        try:
            prompt_tok = (
                int(parts[0].split("=")[0]) if "tokens_used" in " ".join(parts) else 0
            )
            ctx_window = 0
            for p in parts:
                if p.startswith("tokens_used="):
                    prompt_tok = int(p.split("=")[1])
                elif p.startswith("context_window="):
                    ctx_window = int(p.split("=")[1])
            if ctx_window and prompt_tok:
                usage_pct = prompt_tok / ctx_window
                if usage_pct >= 0.70 and not memory_pressure:
                    remaining_pct = round((1.0 - usage_pct) * 100)
                    context_pressure_warning = (
                        f"\n⚠️ CONTEXT PRESSURE: {remaining_pct}% of context window remaining. "
                        "Condensation will occur soon. To preserve context AND work efficiently:\n"
                        "1. note(key, value) — persist important findings and decisions\n"
                        "2. task_tracker(update) — ensure plan reflects current progress\n"
                        "3. working_memory(update) — save current hypothesis and blockers\n"
                        "4. Prefer targeted reads: use view_range instead of reading full files\n"
                        "5. Prefer search_code over cat/grep for lookups — it returns only relevant lines\n"
                        "6. Keep responses concise — avoid restating what the code does\n"
                        "Unsaved context from early turns WILL be lost during condensation."
                    )
                elif usage_pct >= 0.85 and not memory_pressure:
                    context_pressure_warning += (
                        "\n🔴 CRITICAL: Consider calling condensation_request() NOW to control "
                        "what context survives before automatic condensation forces a reset."
                    )
        except Exception:
            pass

        status = "<FORGE_CONTEXT_STATUS " + " | ".join(parts) + " />"
        if context_pressure_warning:
            status += context_pressure_warning

        # Repetition warning when approaching stuck threshold.
        # Thresholds are raised from the original 0.3/0.6 to 0.45/0.7 to
        # avoid false positives on legitimate edit-test-edit debug cycles.
        if rep_score >= 0.7:
            status += (
                "\n⚠️ REPETITION WARNING (score={:.1f}/1.0): You are approaching the stuck detection threshold. "
                "Your recent actions show a repeating pattern. You MUST change strategy:\n"
                "1. STOP and use think() to analyze why your current approach isn't working\n"
                "2. Try a fundamentally different approach\n"
                "3. If editing files, re-read the file first with view command"
            ).format(rep_score)
        elif rep_score >= 0.45:
            status += (
                "\n📊 Mild repetition detected (score={:.1f}/1.0). Consider varying your approach."
            ).format(rep_score)

        # First-turn workspace orientation: give the LLM awareness of the
        # project structure so it doesn't waste a turn exploring blindly.
        iter_flag = getattr(state, "iteration_flag", None)
        current_turn = getattr(iter_flag, "current_value", 0) if iter_flag else 0
        try:
            current_turn = int(current_turn)
        except Exception:
            current_turn = 0
        if current_turn <= 1 and not self._is_plain_chat_request(
            self._get_last_user_message(messages) or ""
        ):
            status += (
                "\n<FIRST_TURN_ORIENTATION>"
                "\nThis is the first turn. Before diving in:"
                "\n1. Use workspace_status() to see git branch, modified files, and working directory"
                "\n2. Use project_map() to understand the repository structure"
                "\n3. Then plan your approach with think()"
                "\n</FIRST_TURN_ORIENTATION>"
            )

        # Active Plan Injection
        plan = getattr(state, "plan", None)
        if plan and hasattr(plan, "steps") and plan.steps:
            active_plan_str = f"Title: {getattr(plan, 'title', 'Current Plan')}\n"
            for step in plan.steps:
                status_icon = (
                    "✓"
                    if step.status == "completed"
                    else "X"
                    if step.status == "failed"
                    else "O"
                    if step.status == "in_progress"
                    else "-"
                )
                active_plan_str += (
                    f"{step.id} [{status_icon}] {step.description} ({step.status})\n"
                )
                if step.result:
                    active_plan_str += f"   Result: {str(step.result)[:200]}...\n"
                for sub in step.subtasks:
                    status_icon = "✓" if sub.status == "completed" else "-"
                    active_plan_str += (
                        f"    {sub.id} [{status_icon}] {sub.description}\n"
                    )

            status += f"\n<ACTIVE_PLAN>\n{active_plan_str}</ACTIVE_PLAN>"

        if planning_directive:
            status += f"\n<FORGE_DIRECTIVE>\n{planning_directive}\n</FORGE_DIRECTIVE>"

        # Context-aware tool hints based on task keywords
        tool_hints = self._get_tool_hints(messages)
        if tool_hints:
            status += f"\n<TOOL_HINTS>{tool_hints}</TOOL_HINTS>"

        # Insert a dedicated system message just before the last user message.
        msgs = list(messages)
        insert_at = len(msgs)
        for i in range(len(msgs) - 1, -1, -1):
            msg = msgs[i]
            if isinstance(msg, dict) and msg.get("role") == "user":
                insert_at = i
                break

        control_message = {
            "role": "system",
            "content": status,
        }
        msgs.insert(insert_at, control_message)
        return msgs

    # Tool-keyword mapping for context-aware hints
    _TOOL_HINT_MAP: list[tuple[list[str], str]] = [
        (
            ["debug", "error", "traceback", "exception", "fails", "broken"],
            "Consider error_patterns(query) to check for known fixes.",
        ),
        (
            ["search", "find", "grep", "locate", "where"],
            "Use search_code for codebase search, or web_search for external info.",
        ),
        (
            ["edit", "fix", "change", "modify", "update", "refactor"],
            "Prefer structure_editor for function/class-level edits (edit_function, rename_symbol). Use str_replace_editor only for single-line fixes or file creation. Use verify_state to confirm line contents before str_replace.",
        ),
        (
            ["test", "testing", "pytest", "unittest"],
            "Use run_tests to execute tests with structured output.",
        ),
        (
            ["git", "commit", "branch", "merge", "diff"],
            "Use workspace_status for a quick git overview before git operations.",
        ),
        (
            ["remember", "note", "save", "persist"],
            "Use working_memory(update) for structured cognitive state, note(record) for quick key-value pairs.",
        ),
    ]

    def _get_tool_hints(self, messages: list) -> str:
        """Generate context-specific tool suggestions based on keywords AND agent behavior."""
        text = _get_last_user_text_from_messages(messages)
        if not text:
            return ""

        text_lower = text.lower()
        hints = [
            hint
            for keywords, hint in self._TOOL_HINT_MAP
            if any(kw in text_lower for kw in keywords)
        ]
        behavioral = self._get_behavioral_hints(messages)
        if behavioral:
            hints.extend(behavioral)

        return " ".join(hints) if hints else ""

    def _get_behavioral_hints(self, messages: list) -> list[str]:
        """Analyze recent agent messages to detect behavioral patterns and generate hints."""
        # Scan tool results for error learning (full message list)
        self._scan_tool_results_for_learning(messages)

        recent = self._collect_recent_assistant_messages(messages, max_messages=15)
        if len(recent) < 3:
            return []

        edited_files, error_count, has_test_run = self._extract_tool_patterns(recent)
        return self._build_behavioral_hints(edited_files, error_count, has_test_run)

    def _collect_recent_assistant_messages(
        self, messages: list, max_messages: int = 15
    ) -> list:
        """Collect last N assistant messages in chronological order."""
        recent: list = []
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                recent.append(msg)
                if len(recent) >= max_messages:
                    break
        recent.reverse()
        return recent

    def _scan_tool_results_for_learning(self, messages: list) -> None:
        """Scan tool response messages to record failures/successes for error learning."""
        if not hasattr(self, "_error_learner"):
            return
        seen: set[str] = getattr(self, "_seen_tool_call_ids", set())

        for i, msg in enumerate(messages):
            if not isinstance(msg, dict) or msg.get("role") != "tool":
                continue
            tc_id = msg.get("tool_call_id", "")
            if not tc_id or tc_id in seen:
                continue
            seen.add(tc_id)
            tool_name = msg.get("name", "")
            content = str(msg.get("content", ""))
            content_lower = content.lower()
            is_error = "[error" in content_lower or "error occurred" in content_lower
            if is_error:
                self._error_learner.record_failure(tool_name, content, i)
            else:
                self._error_learner.record_success(tool_name, i)

        self._seen_tool_call_ids = seen

    def _extract_tool_patterns(
        self, recent_assistant: list
    ) -> tuple[dict[str, int], int, bool]:
        """Extract edit counts, error count, and test-run flag from assistant messages."""
        edited_files: dict[str, int] = {}
        error_count = 0
        has_test_run = False
        self._str_replace_count = 0

        for msg in recent_assistant:
            tc_list = msg.get("tool_calls", [])
            if not isinstance(tc_list, list):
                continue
            for tc in tc_list:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get("function", {})
                name = fn.get("name", "")
                args_raw = fn.get("arguments", "{}")

                if name in ("str_replace_editor", "edit_file", "structure_editor"):
                    path = self._extract_edit_path(args_raw)
                    if path:
                        edited_files[path] = edited_files.get(path, 0) + 1
                    if name == "str_replace_editor":
                        self._str_replace_count += 1
                elif name == "run_tests":
                    has_test_run = True

            content = str(msg.get("content", ""))
            if "error" in content.lower() or "failed" in content.lower():
                error_count += 1

        return edited_files, error_count, has_test_run

    def _extract_edit_path(self, args_raw: str | dict) -> str | None:
        """Extract file path from tool call args if it's an edit (not view)."""
        try:
            import json as _json

            args = _json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            path = args.get("path", args.get("file_path", ""))
            return path if path and args.get("command") != "view" else None
        except Exception:
            return None

    def _build_behavioral_hints(
        self, edited_files: dict[str, int], error_count: int, has_test_run: bool
    ) -> list[str]:
        """Build hint strings from detected patterns.

        Includes: repeated edits to same file, many edits without tests,
        multiple errors suggesting strategy change, cross-file impact warnings,
        and think() usage reminders.
        """
        hints: list[str] = []

        for path, count in edited_files.items():
            if count >= 3:
                hints.append(
                    f"You've edited '{path}' {count} times recently — "
                    "use verify_state to confirm line contents before your next edit."
                )
                break

        str_replace_count = getattr(self, "_str_replace_count", 0)
        if str_replace_count >= 2:
            hints.append(
                "You've used str_replace_editor multiple times. Consider switching to "
                "structure_editor (edit_function, rename_symbol) for function/class-level edits — "
                "it targets by symbol name and avoids context-matching issues."
            )

        total_edits = sum(edited_files.values())
        if total_edits >= 4 and not has_test_run:
            hints.append(
                "Multiple file edits without running tests — consider run_tests to verify changes."
            )

        if error_count >= 3:
            hints.append(
                "Multiple errors detected — consider working_memory(update, hypothesis) "
                "to reassess, or error_patterns(query) for known fixes."
            )

        # Cross-file impact warning: when any file was edited, suggest checking callers
        if edited_files and total_edits >= 2:
            hints.append(
                "You have edited multiple files. If you changed a function or class signature, "
                'use explore_tree_structure(start_entities=["<file>:<Symbol>"], direction="upstream") '
                "to find callers that may need updating."
            )

        # Within-conversation error learning hypotheses
        if hasattr(self, "_error_learner"):
            learned = self._error_learner.get_hypotheses(max_hints=3)
            hints.extend(learned)

        # Cap total hints to prevent prompt bloat
        return hints[:5]

    def _determine_tool_choice(self, messages: list, state: State) -> str | dict | None:
        last_user_msg = self._get_last_user_message(messages)
        if not last_user_msg:
            return "auto"

        if self._is_plain_chat_request(last_user_msg):
            return "none"

        # Let the LLM decide whether to use tools — "auto" is more robust
        # than brittle regex-based question/action classification.
        return "auto"

    def _llm_supports_tool_choice(self) -> bool:
        try:
            return supports_tool_choice(self._llm.config.model)
        except Exception:
            return False

    def _get_last_user_message(self, messages: list) -> str | None:
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "user":
                content = message.get("content", "")
                # Skip workspace-context / knowledge-recall injections so that
                # simple greetings like "hello" are still recognized even after
                # the recall observation inserts a long synthetic user message.
                if isinstance(content, str) and any(
                    marker in content for marker in _INJECTED_MSG_MARKERS
                ):
                    continue
                return content
        return None

    def _is_plain_chat_request(self, message: str) -> bool:
        text = (message or "").strip().lower()
        if not text:
            return False
        # Semantic check: matches a conversational pattern AND has no action verbs.
        # This replaces the old brittle 120-char length cutoff.
        action_patterns = [
            r"\bcreate\b", r"\bmake\b", r"\bwrite\b", r"\bedit\b", r"\bmodify\b",
            r"\bdelete\b", r"\bremove\b", r"\bfix\b", r"\bimplement\b", r"\badd\b",
            r"\bupdate\b", r"\bchange\b", r"\bbuild\b", r"\brun\b", r"\binstall\b"
        ]
        if any(re.search(pattern, text) for pattern in PLAIN_CHAT_PATTERNS):
            if not any(re.search(p, text) for p in action_patterns):
                return True
        return False
