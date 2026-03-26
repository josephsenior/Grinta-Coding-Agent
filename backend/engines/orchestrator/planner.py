from __future__ import annotations
import logging
import os
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


def _shorten_tool_description(desc: str, max_len: int = 80) -> str:
    """Trim long tool descriptions without splitting on the first period (avoids Dr., URLs, versions)."""
    text = desc.strip()
    if len(text) <= max_len:
        return text
    window = text[: max_len + 1]
    last_space = window.rfind(" ")
    cut = last_space if last_space > max_len // 2 else max_len
    out = text[:cut].rstrip(".,;:")
    return f"{out}…" if out else text[:max_len]


def _maybe_log_prompt_metrics(messages: list) -> None:
    """Log system-message character counts when FORGE_DEBUG_PROMPT_METRICS is set."""
    flag = os.environ.get("FORGE_DEBUG_PROMPT_METRICS", "").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return
    sizes: list[int] = []
    for m in messages:
        if not isinstance(m, dict) or m.get("role") != "system":
            continue
        c = m.get("content", "")
        if isinstance(c, str):
            sizes.append(len(c))
        elif isinstance(c, list):
            sizes.append(sum(len(str(part)) for part in c))
        else:
            sizes.append(len(str(c)))
    if not sizes:
        logger.info("FORGE_DEBUG_PROMPT_METRICS: no system messages")
        return
    logger.info(
        "FORGE_DEBUG_PROMPT_METRICS: system_messages=%s chars_each=%s chars_total=%s",
        len(sizes),
        sizes,
        sum(sizes),
    )


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
        self._tools_used_this_session: set[str] = set()

    # ------------------------------------------------------------------ #
    # Tool assembly
    # ------------------------------------------------------------------ #
    def build_toolset(self) -> list[ChatCompletionToolParam]:
        use_short_desc = self._should_use_short_tool_descriptions()
        tools: list[ChatCompletionToolParam] = []

        self._add_core_tools(tools, use_short_desc)
        self._add_browsing_tool(tools)
        self._add_editor_tools(tools, use_short_desc)
        self._add_execute_mcp_tool_tool(tools)

        # Invalidate cached checked-tools when toolset is rebuilt
        self._checked_tools_cache = None
        return tools

    def _should_use_short_tool_descriptions(self) -> bool:
        if not self._llm:
            return False
        try:
            model = (self._llm.config.model or "").strip()
            if not model:
                return False
            return prefers_short_tool_descriptions(model)
        except Exception:
            return False

    def _add_core_tools(self, tools: list, use_short_tool_desc: bool) -> None:
        self._add_basic_tools(tools, use_short_tool_desc)
        self._add_edit_and_search_tools(tools)
        self._add_terminal_and_special_tools(tools)

    def _add_basic_tools(self, tools: list, use_short_tool_desc: bool) -> None:
        """Add cmd, think, finish, summarize_context, memory tools."""
        from backend.engines.orchestrator.tools.bash import create_cmd_run_tool
        from backend.engines.orchestrator.tools.condensation_request import (
            create_summarize_context_tool,
        )
        from backend.engines.orchestrator.tools.finish import create_finish_tool
        from backend.engines.orchestrator.tools.think import create_think_tool
        from backend.engines.orchestrator.tools.memory_manager import (
            create_memory_manager_tool,
        )

        if getattr(self._config, "enable_cmd", True):
            tools.append(create_cmd_run_tool(use_short_description=use_short_tool_desc))
        if getattr(self._config, "enable_think", True):
            tools.append(create_think_tool())
        if getattr(self._config, "enable_finish", True):
            tools.append(create_finish_tool())
        if getattr(self._config, "enable_condensation_request", False):
            tools.append(create_summarize_context_tool())
        if getattr(self._config, "enable_working_memory", True):
            tools.append(create_memory_manager_tool())

    def _add_edit_and_search_tools(self, tools: list) -> None:
        """Add apply_patch, batch_edit, task_tracker, search_code, explore_code tools."""
        from backend.engines.orchestrator.tools.apply_patch import (
            create_apply_patch_tool,
        )
        from backend.engines.orchestrator.tools.batch_edit import create_batch_edit_tool
        from backend.engines.orchestrator.tools.task_tracker import (
            create_task_tracker_tool,
        )
        from backend.engines.orchestrator.tools.search_available_tools import (
            create_search_available_tools_tool,
        )
        from backend.engines.orchestrator.tools.search_code import (
            create_search_code_tool,
        )
        from backend.engines.orchestrator.tools.explore_code import (
            create_explore_tree_structure_tool,
            create_read_symbol_definition_tool,
        )

        if getattr(self._config, "enable_apply_patch", True):
            tools.append(create_apply_patch_tool())
            tools.append(create_batch_edit_tool())
        if getattr(self._config, "enable_internal_task_tracker", True):
            tools.append(create_search_available_tools_tool())
            tools.append(create_task_tracker_tool())
        if getattr(self._config, "enable_search_code", True):
            tools.append(create_search_code_tool())
            tools.append(create_explore_tree_structure_tool())
            tools.append(create_read_symbol_definition_tool())

    def _add_terminal_and_special_tools(self, tools: list) -> None:
        """Add terminal, optional feature tools (web search, delegate, etc.), and meta-cognition tools."""
        self._add_terminal_tools(tools)
        self._add_optional_feature_tools(tools)
        self._add_meta_cognition_tools(tools)

    def _add_terminal_tools(self, tools: list) -> None:
        """Add terminal manager tool when terminal support is enabled."""
        if getattr(self._config, "enable_terminal", True):
            from backend.engines.orchestrator.tools.terminal_manager import (
                create_terminal_manager_tool,
            )

            tools.append(create_terminal_manager_tool())

    def _add_optional_feature_tools(self, tools: list) -> None:
        """Add check_tool_status, delegate, rollback, workspace_status, etc."""
        from backend.engines.orchestrator.tools.check_tool_status import (
            create_check_tool_status_tool,
        )
        from backend.engines.orchestrator.tools.delegate_task import (
            create_delegate_task_tool,
        )
        from backend.engines.orchestrator.tools.revert_to_checkpoint import (
            create_revert_to_checkpoint_tool,
        )
        from backend.engines.orchestrator.tools.lsp_query import create_lsp_query_tool
        from backend.engines.orchestrator.tools.signal_progress import (
            create_signal_progress_tool,
        )
        from backend.engines.orchestrator.tools.error_recovery_memory import (
            create_error_recovery_memory_tool,
        )

        if getattr(self._config, "enable_check_tool_status", False):
            tools.append(create_check_tool_status_tool())

        tools.append(create_error_recovery_memory_tool())

        # Optional feature tools remain flag-gated; note that enable_lsp_query
        # currently defaults to True in AgentConfig while the others below are
        # mostly default-off.
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
            tools.append(create_revert_to_checkpoint_tool())
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
                    "enable_checkpoints",
                    False,
                    "checkpoint",
                    "create_checkpoint_tool",
                ),
                ("enable_analyze_project_structure", False, "analyze_project_structure", "create_analyze_project_structure_tool"),
                (
                    "enable_session_diff",
                    False,
                    "session_diff",
                    "create_session_diff_tool",
                ),
                (
                    "enable_verify_file_lines",
                    False,
                    "verify_file_lines",
                    "create_verify_file_lines_tool",
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
                create_communicate_tool,
            )

            tools.append(create_communicate_tool())

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

    def _add_execute_mcp_tool_tool(self, tools: list) -> None:
        """Add the MCP gateway proxy tool when MCP is enabled.

        The gateway replaces injecting 50+ individual MCP tool schemas.
        Available MCP tool names are listed in the system prompt instead.
        """
        if getattr(self._config, "enable_mcp", True):
            from backend.engines.orchestrator.tools.execute_mcp_tool import (
                create_execute_mcp_tool_tool,
            )
            tools.append(create_execute_mcp_tool_tool())

    def record_tool_used(self, tool_name: str) -> None:
        """Record that a tool was used this session (for description tiers)."""
        self._tools_used_this_session.add(tool_name)

    def build_llm_params(
        self,
        messages: list,
        state: State,
        tools: list[ChatCompletionToolParam],
    ) -> dict:
        tool_choice = self._determine_tool_choice(messages, state)

        # NOTE: We inject control/status messages *after* tool selection so
        # tool selection heuristics see the original user/assistant content.

        # Apply three-tier tool descriptions
        tools = self._apply_description_tiers(tools)

        # Cache check_tools output — only recompute when tools or model changes
        # Invalidate cache when tool selection changes the list
        current_model = self._llm.config.model if self._llm else ""
        # Stringify names so cache keys work with MagicMock-based tests and odd payloads.
        tool_fingerprint = ",".join(
            str((t.get("function") or {}).get("name", "") if isinstance(t, dict) else "")
            for t in tools
        )
        cache_key = f"{current_model}:{tool_fingerprint}"
        if self._checked_tools_cache is None or self._checked_tools_model != cache_key:
            self._checked_tools_cache = check_tools(tools, self._llm.config)
            self._checked_tools_model = cache_key

        messages = self._inject_turn_status(messages, state)
        _maybe_log_prompt_metrics(messages)

        params: dict[str, Any] = {
            "messages": messages,
            "tools": self._checked_tools_cache,
            "stream": True,
        }

        if tool_choice and self._llm_supports_tool_choice():
            params["tool_choice"] = tool_choice

        params["extra_body"] = {
            "metadata": state.to_llm_metadata(
                model_name=(self._llm.config.model or "").strip() or "unknown",
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
                    trimmed_desc = _shorten_tool_description(desc, max_len=80)
                    trimmed = {
                        **tool,
                        "function": {**fn, "description": trimmed_desc},
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

        parts = self._build_turn_context_parts(state)
        planning_directive, memory_pressure, rep_score = self._extract_turn_signals(
            state
        )
        parts = self._append_signal_parts(parts, memory_pressure, rep_score)

        status = "<FORGE_CONTEXT_STATUS " + " | ".join(parts) + " />"
        status += self._build_context_pressure_warning(parts, memory_pressure)
        status += self._build_repetition_warning(rep_score)
        status += self._build_first_turn_orientation(state)
        status += self._build_active_plan_section(state)
        if planning_directive:
            status += f"\n<FORGE_DIRECTIVE>\n{planning_directive}\n</FORGE_DIRECTIVE>"

        return self._apply_control_message(messages, status)

    def _build_turn_context_parts(self, state: State) -> list[str]:
        """Build the core context status parts (turn, tokens, budget, history)."""
        iter_flag = getattr(state, "iteration_flag", None)
        max_val = getattr(iter_flag, "max_value", None) if iter_flag else None
        current = getattr(iter_flag, "current_value", None) if iter_flag else None
        parts = [f"turn={current}" + (f"/{max_val}" if max_val else "")]

        metrics = getattr(state, "metrics", None)
        if metrics:
            self._append_token_usage_parts(metrics, parts)
            self._append_budget_parts(metrics, parts)

        history = getattr(state, "history", [])
        if history:
            parts.append(f"history_events={len(history)}")
        return parts

    def _append_token_usage_parts(self, metrics: Any, parts: list[str]) -> None:
        """Append token usage and context window to parts."""
        atu = getattr(metrics, "accumulated_token_usage", None)
        if not atu:
            return
        prompt_tok = self._safe_int(getattr(atu, "prompt_tokens", 0))
        comp_tok = self._safe_int(getattr(atu, "completion_tokens", 0))
        ctx_window = self._safe_int(getattr(atu, "context_window", 0))
        if prompt_tok or comp_tok:
            parts.append(f"tokens_used={prompt_tok + comp_tok}")
        if ctx_window:
            parts.append(f"context_window={ctx_window}")

    def _append_budget_parts(self, metrics: Any, parts: list[str]) -> None:
        """Append cost/budget info to parts."""
        cost = self._safe_float(getattr(metrics, "accumulated_cost", 0.0)) or 0.0
        if cost <= 0:
            return
        budget = getattr(metrics, "max_budget_per_task", None)
        budget_val = self._safe_float(budget) if budget is not None else None
        budget_str = f"cost=${cost:.4f}"
        if budget_val is not None:
            budget_str += f"/${budget_val:.2f}"
        parts.append(budget_str)

    @staticmethod
    def _safe_int(val: Any) -> int:
        try:
            return int(val)
        except Exception:
            return 0

    @staticmethod
    def _safe_float(val: Any) -> float | None:
        if val is None:
            return None
        try:
            return float(val)
        except Exception:
            return None

    def _extract_turn_signals(
        self, state: State
    ) -> tuple[Any, Any, float]:
        """Extract planning_directive, memory_pressure, and repetition_score."""
        ts = getattr(state, "turn_signals", None)
        planning_directive = getattr(ts, "planning_directive", None) if ts else None
        memory_pressure = getattr(ts, "memory_pressure", None) if ts else None

        extra_data = getattr(state, "extra_data", {}) or {}
        if planning_directive is None:
            planning_directive = extra_data.get("planning_directive")
        if memory_pressure is None:
            memory_pressure = extra_data.get("memory_pressure")

        rep_score = getattr(ts, "repetition_score", 0.0) if ts else 0.0
        return planning_directive, memory_pressure, rep_score

    def _append_signal_parts(
        self, parts: list[str], memory_pressure: Any, rep_score: float
    ) -> list[str]:
        """Append memory_pressure and repetition_score to parts."""
        if memory_pressure:
            parts.append(f"memory_pressure={memory_pressure}")
        if rep_score and rep_score >= 0.45:
            parts.append(f"repetition_score={rep_score:.1f}")
        return parts

    def _build_context_pressure_warning(
        self, parts: list[str], memory_pressure: Any
    ) -> str:
        """Build context pressure warning at ~70% token usage."""
        if memory_pressure:
            return ""
        prompt_tok, ctx_window = 0, 0
        for p in parts:
            if p.startswith("tokens_used="):
                prompt_tok = self._safe_int(p.split("=", 1)[1])
            elif p.startswith("context_window="):
                ctx_window = self._safe_int(p.split("=", 1)[1])
        if not ctx_window or not prompt_tok:
            return ""
        usage_pct = prompt_tok / ctx_window
        if usage_pct >= 0.85:
            return (
                "\n🔴 CRITICAL: Consider calling summarize_context() NOW to control "
                "what context survives before automatic condensation forces a reset."
            )
        if usage_pct >= 0.70:
            remaining_pct = round((1.0 - usage_pct) * 100)
            return (
                f"\n⚠️ CONTEXT PRESSURE: ~{remaining_pct}% of context window left; "
                "condensation is coming. Persist essentials with memory_manager (note / "
                "working_memory), avoid redundant file re-reads, and stay concise. "
                "Follow **Execution discipline** (EFFICIENCY + TASK_MANAGEMENT) in the "
                "system prompt for search/read patterns."
            )
        return ""

    def _build_repetition_warning(self, rep_score: float) -> str:
        """Build repetition warning when approaching stuck threshold."""
        if rep_score >= 0.7:
            return (
                f"\n⚠️ REPETITION WARNING (score={rep_score:.1f}/1.0): You are approaching the stuck detection threshold. "
                "Your recent actions show a repeating pattern. You MUST change strategy:\n"
                "1. STOP and use think() to analyze why your current approach isn't working\n"
                "2. Try a fundamentally different approach\n"
                "3. If editing files, re-read the file first with view command\n"
                "4. Do not repeat unchanged tracking updates\n"
                "5. Optional: error_recovery_memory(query) to retrieve stored fixes for similar errors"
            )
        if rep_score >= 0.45:
            return (
                f"\n📊 Mild repetition detected (score={rep_score:.1f}/1.0). Consider varying your approach."
            )
        return ""

    def _build_first_turn_orientation(self, state: State) -> str:
        """Build first-turn workspace orientation block."""
        if not getattr(self._config, "enable_first_turn_orientation_prompt", True):
            return ""
        iter_flag = getattr(state, "iteration_flag", None)
        current_turn = getattr(iter_flag, "current_value", 0) if iter_flag else 0
        current_turn = self._safe_int(current_turn)
        if current_turn <= 1:
            return (
                "\n<FIRST_TURN_ORIENTATION>\n"
                "Optional: call workspace_status() if you lack repo/git context; "
                "then proceed (think/plan as needed).\n"
                "</FIRST_TURN_ORIENTATION>"
            )
        return ""

    def _build_active_plan_section(self, state: State) -> str:
        """Build active plan injection section."""
        plan = getattr(state, "plan", None)
        if not plan or not hasattr(plan, "steps") or not plan.steps:
            return ""
        title = getattr(plan, "title", "Current Plan")
        lines = [f"Title: {title}\n"]
        for step in plan.steps:
            lines.append(self._format_plan_step(step))
        return f"\n<ACTIVE_PLAN>\n{''.join(lines)}</ACTIVE_PLAN>"

    def _format_plan_step(self, step: Any) -> str:
        """Format a single plan step for injection."""
        icon = self._step_status_icon(step.status)
        out = f"{step.id} [{icon}] {step.description} ({step.status})\n"
        if step.result:
            out += f"   Result: {str(step.result)[:200]}...\n"
        for sub in step.subtasks:
            sub_icon = "✓" if sub.status == "completed" else "-"
            out += f"    {sub.id} [{sub_icon}] {sub.description}\n"
        return out

    @staticmethod
    def _step_status_icon(status: str) -> str:
        """Map step status to display icon."""
        return {"completed": "✓", "failed": "X", "in_progress": "O"}.get(status, "-")

    def _apply_control_message(self, messages: list, status: str) -> list:
        """Attach turn control either as a second system message or merged into primary."""
        if getattr(self._config, "merge_control_system_into_primary", False):
            return self._merge_control_into_primary_system(messages, status)
        return self._insert_control_message(messages, status)

    def _merge_control_into_primary_system(self, messages: list, status: str) -> list:
        """Append control/status to the first string system message; else fall back."""
        msgs = list(messages)
        for i, msg in enumerate(msgs):
            if not isinstance(msg, dict) or msg.get("role") != "system":
                continue
            content = msg.get("content", "")
            if not isinstance(content, str):
                return self._insert_control_message(messages, status)
            sep = "\n\n" if content.strip() else ""
            msgs[i] = {**msg, "content": f"{content}{sep}{status}"}
            return msgs
        return self._insert_control_message(messages, status)

    @staticmethod
    def _insert_control_message(messages: list, status: str) -> list:
        """Insert control message just before the last user message."""
        msgs = list(messages)
        insert_at = len(msgs)
        for i in range(len(msgs) - 1, -1, -1):
            if isinstance(msgs[i], dict) and msgs[i].get("role") == "user":
                insert_at = i
                break
        msgs.insert(insert_at, {"role": "system", "content": status})
        return msgs

    def _determine_tool_choice(self, messages: list, state: State) -> str | dict | None:
        last_user_msg = self._get_last_user_message(messages)
        if not last_user_msg:
            return "auto"

        # Let the LLM decide whether to use tools — "auto" is more robust
        # than brittle regex-based question/action classification.
        return "auto"

    def _llm_supports_tool_choice(self) -> bool:
        try:
            model = (self._llm.config.model or "").strip()
            if not model:
                return False
            return supports_tool_choice(model)
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
