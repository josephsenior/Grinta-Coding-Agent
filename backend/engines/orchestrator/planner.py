from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from backend.core.logger import FORGE_logger as logger
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
        from backend.engines.orchestrator.tools.note import create_note_tool, create_recall_tool, create_semantic_recall_tool
        from backend.engines.orchestrator.tools.run_tests import create_run_tests_tool
        from backend.engines.orchestrator.tools.apply_patch import create_apply_patch_tool
        from backend.engines.orchestrator.tools.task_tracker import create_task_tracker_tool
        from backend.engines.orchestrator.tools.search_code import create_search_code_tool

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
        if getattr(self._config, "enable_web_search", False):
            from backend.engines.orchestrator.tools.web_search import create_web_search_tool
            tools.append(create_web_search_tool())
        if getattr(self._config, "enable_workspace_status", True):
            from backend.engines.orchestrator.tools.workspace_status import create_workspace_status_tool
            tools.append(create_workspace_status_tool())
        if getattr(self._config, "enable_error_patterns", True):
            from backend.engines.orchestrator.tools.error_patterns import create_error_patterns_tool
            tools.append(create_error_patterns_tool())
        if getattr(self._config, "enable_checkpoints", True):
            from backend.engines.orchestrator.tools.checkpoint import create_checkpoint_tool
            tools.append(create_checkpoint_tool())
        if getattr(self._config, "enable_project_map", True):
            from backend.engines.orchestrator.tools.project_map import create_project_map_tool
            tools.append(create_project_map_tool())
        if getattr(self._config, "enable_session_diff", True):
            from backend.engines.orchestrator.tools.session_diff import create_session_diff_tool
            tools.append(create_session_diff_tool())
        if getattr(self._config, "enable_working_memory", True):
            from backend.engines.orchestrator.tools.working_memory import create_working_memory_tool
            tools.append(create_working_memory_tool())
        if getattr(self._config, "enable_verify_state", True):
            from backend.engines.orchestrator.tools.verify_state import create_verify_state_tool
            tools.append(create_verify_state_tool())

    def _add_browsing_tool(self, tools: list) -> None:
        if not getattr(self._config, "enable_browsing", False):
            return
        import sys

        platform_name = getattr(sys, "platform", "")
        if platform_name == "win32":
            logger.warning("Windows runtime does not support browsing yet")
            return
        from backend.engines.orchestrator.tools import create_browser_tool

        tools.append(create_browser_tool())

    def _add_editor_tools(self, tools: list, use_short_tool_desc: bool) -> None:
        if getattr(self._config, "enable_editor", True):
            from backend.engines.orchestrator.tools import create_structure_editor_tool

            tools.append(
                create_structure_editor_tool(use_short_description=use_short_tool_desc)
            )

    def build_llm_params(
        self,
        messages: list,
        state: State,
        tools: list[ChatCompletionToolParam],
    ) -> dict:
        tool_choice = self._determine_tool_choice(messages, state)
        messages = self._inject_turn_status(messages, state)

        # Cache check_tools output — only recompute when tools or model changes
        current_model = self._llm.config.model if self._llm else ""
        if (
            self._checked_tools_cache is None
            or self._checked_tools_model != current_model
        ):
            self._checked_tools_cache = check_tools(tools, self._llm.config)
            self._checked_tools_model = current_model

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

    def _inject_turn_status(self, messages: list, state: State) -> list:
        """Append a <CONTEXT_STATUS> block to the last user message.

        Gives the LLM visibility into iteration progress, token budget,
        history size, and scratchpad keys so it can plan accordingly.
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
                if prompt_tok or comp_tok:
                    parts.append(f"tokens_used={prompt_tok + comp_tok}")
                if ctx_window:
                    parts.append(f"context_window={ctx_window}")

            # Budget info
            cost = getattr(metrics, "accumulated_cost", 0.0)
            budget = getattr(metrics, "max_budget_per_task", None)
            if cost > 0:
                budget_str = f"cost=${cost:.4f}"
                if budget:
                    budget_str += f"/${budget:.2f}"
                parts.append(budget_str)

        # History event count
        history = getattr(state, "history", [])
        if history:
            parts.append(f"history_events={len(history)}")

        status = "\n\n<CONTEXT_STATUS " + " | ".join(parts) + " />"

        # Append planning directive if set by PlanningMiddleware
        extra_data = getattr(state, "extra_data", {})
        planning_directive = extra_data.pop("planning_directive", None)
        if planning_directive:
            status += f"\n{planning_directive}"

        # Context-aware tool hints based on task keywords
        tool_hints = self._get_tool_hints(messages)
        if tool_hints:
            status += f"\n<TOOL_HINTS>{tool_hints}</TOOL_HINTS>"

        # Shallow-copy the list so we don’t mutate the caller’s slice
        msgs = list(messages)
        for i in range(len(msgs) - 1, -1, -1):
            msg = msgs[i]
            if not (isinstance(msg, dict) and msg.get("role") == "user"):
                continue
            content = msg.get("content", "")
            if isinstance(content, str):
                msgs[i] = {**msg, "content": content + status}
            elif isinstance(content, list):
                content = list(content)
                for j in range(len(content) - 1, -1, -1):
                    item = content[j]
                    if isinstance(item, dict) and item.get("type") == "text":
                        content[j] = {**item, "text": item["text"] + status}
                        msgs[i] = {**msg, "content": content}
                        break
            break
        return msgs

    # Tool-keyword mapping for context-aware hints
    _TOOL_HINT_MAP: list[tuple[list[str], str]] = [
        (["debug", "error", "traceback", "exception", "fails", "broken"],
         "Consider error_patterns(query) to check for known fixes."),
        (["search", "find", "grep", "locate", "where"],
         "Use search_code for codebase search, or web_search for external info."),
        (["edit", "fix", "change", "modify", "update", "refactor"],
         "Pick the right editor: str_replace_editor for targeted edits, ultimate_editor for function-level, edit_file for large rewrites. Use verify_state to confirm line contents before str_replace."),
        (["test", "testing", "pytest", "unittest"],
         "Use run_tests to execute tests with structured output."),
        (["git", "commit", "branch", "merge", "diff"],
         "Use workspace_status for a quick git overview before git operations."),
        (["remember", "note", "save", "persist"],
         "Use working_memory(update) for structured cognitive state, note(record) for quick key-value pairs."),
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
                        item.get("text", "") for item in content
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
                        args = _json.loads(args_raw) if isinstance(args_raw, str) else args_raw
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
        action_count = sum(
            1 for p in ACTION_PATTERNS if re.search(p, msg_lower)
        )
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
