from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from backend.llm.llm_utils import check_tools

ChatCompletionToolParam = Any

if TYPE_CHECKING:
    from backend.controller.state.state import State
    from backend.llm.llm import LLM

    from .safety import OrchestratorSafetyManager


QUESTION_PATTERNS = [
    r"\bwhy\b",
    r"\bhow does\b",
    r"\bwhat is\b",
    r"\bwhat are\b",
    r"\bexplain\b",
    r"\btell me\b",
    r"\b\?\s*$",
    r"\bcan you explain\b",
]

ACTION_PATTERNS = [
    r"\bcreate\b",
    r"\bmake\b",
    r"\bwrite\b",
    r"\bedit\b",
    r"\bmodify\b",
    r"\bdelete\b",
    r"\bremove\b",
    r"\bfix\b",
    r"\bimplement\b",
    r"\badd\b",
    r"\bupdate\b",
    r"\bchange\b",
    r"\bbuild\b",
    r"\brun\b",
    r"\binstall\b",
]


class OrchestratorPlanner:
    """Assembles tools, messages, and LLM request payloads for CodeAct."""

    def __init__(
        self,
        config,
        llm: LLM,
        safety_manager: OrchestratorSafetyManager,
    ) -> None:
        self._config = config
        self._llm = llm
        self._safety = safety_manager
        # Lazy cache for check_tools output (model-scoped)
        self._checked_tools_cache: list[ChatCompletionToolParam] | None = None
        self._checked_tools_model: str | None = None
        # Progressive tool disclosure
        from backend.engines.orchestrator.tool_selector import ToolSelector

        self._tool_selector = ToolSelector()
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

        # Invalidate cached checked-tools when toolset is rebuilt
        self._checked_tools_cache = None
        return tools

    def _should_use_short_tool_descriptions(self) -> bool:
        if not self._llm:
            return False
        model = self._llm.config.model
        return any(substr in model for substr in ("gpt-4", "o3", "o1", "o4"))

    def _add_core_tools(self, tools: list, use_short_tool_desc: bool) -> None:
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
        from backend.engines.orchestrator.tools.apply_patch import (
            create_apply_patch_tool,
        )
        from backend.engines.orchestrator.tools.task_tracker import (
            create_task_tracker_tool,
        )
        from backend.engines.orchestrator.tools.search_code import (
            create_search_code_tool,
        )
        from backend.engines.orchestrator.tools.check_tool_status import (
            create_check_tool_status_tool,
        )
        from backend.engines.orchestrator.tools.delegate_task import (
            create_delegate_task_tool,
        )
        from backend.engines.orchestrator.tools.revert_to_safe_state import (
            create_revert_to_safe_state_tool,
        )
        from backend.engines.orchestrator.tools.terminal import (
            create_terminal_open_tool,
            create_terminal_input_tool,
            create_terminal_read_tool,
        )
        from backend.engines.orchestrator.tools.meta_cognition import (
            create_uncertainty_tool,
            create_clarification_tool,
            create_escalate_tool,
            create_proposal_tool,
        )

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
        if getattr(self._config, "enable_apply_patch", True):
            tools.append(create_apply_patch_tool())
        if getattr(self._config, "enable_task_tracker", True):
            tools.append(create_task_tracker_tool())
        if getattr(self._config, "enable_search_code", True):
            tools.append(create_search_code_tool())
        if getattr(self._config, "enable_terminal", True):
            tools.append(create_terminal_open_tool())
            tools.append(create_terminal_input_tool())
            tools.append(create_terminal_read_tool())
        if getattr(self._config, "enable_check_tool_status", True):
            tools.append(create_check_tool_status_tool())
        if getattr(self._config, "enable_web_search", False):
            from backend.engines.orchestrator.tools.web_search import (
                create_web_search_tool,
            )

            tools.append(create_web_search_tool())
        if getattr(self._config, "enable_swarming", True):
            tools.append(create_delegate_task_tool())
        if getattr(self._config, "enable_rollback", True):
            tools.append(create_revert_to_safe_state_tool())
        if getattr(self._config, "enable_workspace_status", True):
            from backend.engines.orchestrator.tools.workspace_status import (
                create_workspace_status_tool,
            )

            tools.append(create_workspace_status_tool())
        if getattr(self._config, "enable_error_patterns", True):
            from backend.engines.orchestrator.tools.error_patterns import (
                create_error_patterns_tool,
            )

            tools.append(create_error_patterns_tool())
        if getattr(self._config, "enable_checkpoints", True):
            from backend.engines.orchestrator.tools.checkpoint import (
                create_checkpoint_tool,
            )

            tools.append(create_checkpoint_tool())
        if getattr(self._config, "enable_project_map", True):
            from backend.engines.orchestrator.tools.project_map import (
                create_project_map_tool,
            )

            tools.append(create_project_map_tool())
        if getattr(self._config, "enable_session_diff", True):
            from backend.engines.orchestrator.tools.session_diff import (
                create_session_diff_tool,
            )

            tools.append(create_session_diff_tool())
        if getattr(self._config, "enable_working_memory", True):
            from backend.engines.orchestrator.tools.working_memory import (
                create_working_memory_tool,
            )

            tools.append(create_working_memory_tool())
        if getattr(self._config, "enable_verify_state", True):
            from backend.engines.orchestrator.tools.verify_state import (
                create_verify_state_tool,
            )

            tools.append(create_verify_state_tool())
        if getattr(self._config, "enable_meta_cognition", True):
            tools.append(create_uncertainty_tool())
            tools.append(create_clarification_tool())
            tools.append(create_escalate_tool())
            tools.append(create_proposal_tool())

    def _add_browsing_tool(self, tools: list) -> None:
        if getattr(self._config, "enable_browsing", False):
            # We now rely on external MCP (like cursor-ide-browser or browser-use)
            pass

    def _add_editor_tools(self, tools: list, use_short_tool_desc: bool) -> None:
        if getattr(self._config, "enable_editor", True):
            from backend.engines.orchestrator.tools import create_structure_editor_tool

            tools.append(
                create_structure_editor_tool(use_short_description=use_short_tool_desc)
            )

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
        tool_choice = self._determine_tool_choice(messages, state)

        # NOTE: We inject control/status messages *after* tool selection so
        # tool selection heuristics see the original user/assistant content.

        # Progressive tool disclosure: filter tools based on context
        if getattr(self._config, "enable_progressive_tools", True):
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
        if rep_score and rep_score >= 0.3:
            parts.append(f"repetition_score={rep_score:.1f}")

        # Proactive context pressure warning at ~70% token usage
        context_pressure_warning = ""
        try:
            prompt_tok = (
                int(parts[0].split("=")[0]) if "tokens_used" in " ".join(parts) else 0
            )
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
                        "Condensation will occur soon. Save critical state NOW:\n"
                        "1. note(key, value) — persist important findings and decisions\n"
                        "2. task_tracker(update) — ensure plan reflects current progress\n"
                        "3. working_memory(update) — save current hypothesis and blockers\n"
                        "Unsaved context from early turns WILL be lost during condensation."
                    )
        except Exception:
            pass

        status = "<FORGE_CONTEXT_STATUS " + " | ".join(parts) + " />"
        if context_pressure_warning:
            status += context_pressure_warning

        # Repetition warning when approaching stuck threshold
        if rep_score >= 0.6:
            status += (
                "\n⚠️ REPETITION WARNING (score={:.1f}/1.0): You are approaching the stuck detection threshold. "
                "Your recent actions show a repeating pattern. You MUST change strategy:\n"
                "1. STOP and use think() to analyze why your current approach isn't working\n"
                "2. Try a fundamentally different approach\n"
                "3. If editing files, re-read the file first with view command"
            ).format(rep_score)
        elif rep_score >= 0.3:
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
        if current_turn <= 1:
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
            "Pick the right editor: str_replace_editor for targeted edits, ultimate_editor for function-level, edit_file for large rewrites. Use verify_state to confirm line contents before str_replace.",
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
        # Extract the last user message text
        text = ""
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "user":
                content = msg.get("content", "")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text = " ".join(
                        item.get("text", "")
                        for item in content
                        if isinstance(item, dict) and item.get("type") == "text"
                    )
                break

        if not text:
            return ""

        text_lower = text.lower()
        hints: list[str] = []
        for keywords, hint in self._TOOL_HINT_MAP:
            if any(kw in text_lower for kw in keywords):
                hints.append(hint)

        # Behavioral hints — analyze recent agent actions in the conversation
        behavioral = self._get_behavioral_hints(messages)
        if behavioral:
            hints.extend(behavioral)

        return " ".join(hints) if hints else ""

    def _get_behavioral_hints(self, messages: list) -> list[str]:
        """Analyze recent agent messages to detect behavioral patterns and generate hints.

        Looks at the last N assistant messages to detect:
        - Repeated edits to the same file (potential confusion)
        - Rising error count (suggest changing strategy)
        - Missing test runs after edits
        """
        hints: list[str] = []
        recent_assistant = []
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("role") == "assistant":
                recent_assistant.append(msg)
                if len(recent_assistant) >= 15:
                    break

        if len(recent_assistant) < 3:
            return hints

        # Analyze tool call patterns from recent messages
        edited_files: dict[str, int] = {}
        error_count = 0
        has_test_run = False

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
                    try:
                        import json as _json

                        args = (
                            _json.loads(args_raw)
                            if isinstance(args_raw, str)
                            else args_raw
                        )
                        path = args.get("path", args.get("file_path", ""))
                        if path and args.get("command") != "view":
                            edited_files[path] = edited_files.get(path, 0) + 1
                    except Exception:
                        pass

                if name == "run_tests":
                    has_test_run = True

            content = str(msg.get("content", ""))
            if "error" in content.lower() or "failed" in content.lower():
                error_count += 1

        # Pattern: editing the same file many times
        for path, count in edited_files.items():
            if count >= 3:
                hints.append(
                    f"You've edited '{path}' {count} times recently — "
                    "use verify_state to confirm line contents before your next edit."
                )
                break

        # Pattern: many edits without running tests
        total_edits = sum(edited_files.values())
        if total_edits >= 4 and not has_test_run:
            hints.append(
                "Multiple file edits without running tests — consider run_tests to verify changes."
            )

        # Pattern: rising errors suggest strategy change
        if error_count >= 3:
            hints.append(
                "Multiple errors detected — consider working_memory(update, hypothesis) "
                "to reassess, or error_patterns(query) for known fixes."
            )

        return hints

    def _determine_tool_choice(self, messages: list, state: State) -> str | dict | None:
        last_user_msg = self._get_last_user_message(messages)
        if not last_user_msg:
            return "auto"

        # Force think on the first turn of a complex task
        iter_flag = getattr(state, "iteration_flag", None)
        current_iter = getattr(iter_flag, "current_value", 0) if iter_flag else 0
        # Defensive: state objects in tests/mocks (or corrupted restore data)
        # can yield non-int values; treat those as 0.
        try:
            current_iter = int(current_iter)
        except Exception:
            current_iter = 0
        if current_iter <= 1 and self._is_complex_task(last_user_msg):
            return {"type": "function", "function": {"name": "think"}}

        if self._is_question(last_user_msg):
            return "auto"
        if self._is_action(last_user_msg):
            return "required"

        return self._safety.should_enforce_tools(
            last_user_msg, state, default="required"
        )

    def _is_complex_task(self, message: str) -> bool:
        """Heuristic: task has multiple action verbs or conjunctions indicating multi-step work."""
        msg_lower = message.lower()
        action_count = sum(1 for p in ACTION_PATTERNS if re.search(p, msg_lower))
        conjunction_count = len(
            re.findall(r"\b(and|plus|also|then|after that|additionally)\b", msg_lower)
        )
        return action_count >= 3 or conjunction_count >= 2 or len(message) > 500

    def _llm_supports_tool_choice(self) -> bool:
        model_lower = self._llm.config.model.lower()
        supported = [
            "gpt-4",
            "gpt-3.5",
            "claude-3",
            "claude-sonnet",
            "claude-opus",
            "claude-haiku",
            "gemini",
            "mistral",
            "command",
            "deepseek",
        ]
        return any(substr in model_lower for substr in supported)

    def _get_last_user_message(self, messages: list) -> str | None:
        for message in reversed(messages):
            if isinstance(message, dict) and message.get("role") == "user":
                return message.get("content", "")
        return None

    def _is_question(self, message: str) -> bool:
        return any(re.search(pattern, message.lower()) for pattern in QUESTION_PATTERNS)

    def _is_action(self, message: str) -> bool:
        return any(re.search(pattern, message.lower()) for pattern in ACTION_PATTERNS)
