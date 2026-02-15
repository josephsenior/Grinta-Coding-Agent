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

        if getattr(self._config, "enable_cmd", True):
            tools.append(create_cmd_run_tool(use_short_description=use_short_tool_desc))
        if getattr(self._config, "enable_think", True):
            tools.append(create_think_tool())
        if getattr(self._config, "enable_finish", True):
            tools.append(create_finish_tool())
        if getattr(self._config, "enable_condensation_request", False):
            tools.append(create_condensation_request_tool())

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

            tools.append(create_structure_editor_tool(use_short_description=use_short_tool_desc))

    def build_llm_params(
        self,
        messages: list,
        state: State,
        tools: list[ChatCompletionToolParam],
    ) -> dict:
        tool_choice = self._determine_tool_choice(messages, state)

        # Cache check_tools output — only recompute when tools or model changes
        current_model = self._llm.config.model if self._llm else ""
        if self._checked_tools_cache is None or self._checked_tools_model != current_model:
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

    def _determine_tool_choice(self, messages: list, state: State) -> str | None:
        last_user_msg = self._get_last_user_message(messages)
        if not last_user_msg:
            return "auto"

        if self._is_question(last_user_msg):
            return "auto"
        if self._is_action(last_user_msg):
            return "required"

        return self._safety.should_enforce_tools(last_user_msg, state, default="required")

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
