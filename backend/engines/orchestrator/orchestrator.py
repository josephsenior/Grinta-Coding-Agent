"""Orchestrator agent entrypoint wired to modular planner, executor, and memory subsystems.

Architecture notes (preserve these strengths):
- Protocol-first design: Orchestrator depends on ``PlannerProtocol``,
  ``ExecutorProtocol``, ``SafetyManagerProtocol``, ``MemoryManagerProtocol``
  — never on concrete classes.
- Each subsystem is independently testable and swappable.
- Error recovery follows a typed cascade: ContextLimitError → auto-condense
  → retry → ToolExecutionError → diagnostic think → generic → AgentRuntimeError.
- The event stream is the sole communication channel between controller and agent.
"""

from __future__ import annotations

import os
from collections import deque
from typing import TYPE_CHECKING, Any

import backend.engines.orchestrator.function_calling as codeact_function_calling
from backend.controller.agent import Agent
from backend.controller.state.state import State
from backend.core.config import AgentConfig
from backend.core.errors import (
    AgentRuntimeError,
    ContextLimitError,
    ToolExecutionError,
)
from backend.core.logger import FORGE_logger as logger
from backend.core.message import Message
from backend.events.action import AgentThinkAction, MessageAction, PlaybookFinishAction
from backend.events.event import EventSource
from backend.llm.llm_registry import LLMRegistry
from backend.runtime.plugins import (
    PluginRequirement,
)
from backend.runtime.plugins.agent_skills import AgentSkillsRequirement
from backend.utils.prompt import OrchestratorPromptManager, PromptManager

from .contracts import (
    ExecutorProtocol,
    MemoryManagerProtocol,
    PlannerProtocol,
    SafetyManagerProtocol,
)
from .executor import OrchestratorExecutor
from .memory_manager import ConversationMemoryManager
from .planner import OrchestratorPlanner
from .safety import OrchestratorSafetyManager

if TYPE_CHECKING:
    from backend.events.action import Action
    from backend.events.stream import EventStream


class Orchestrator(Agent):
    """Production orchestrator agent with modular planner–executor–memory architecture."""

    VERSION = "2.2"
    runtime_plugins: list[PluginRequirement] = [
        AgentSkillsRequirement(name="agent_skills"),
    ]

    def __init__(
        self,
        config: AgentConfig,
        llm_registry: LLMRegistry,
        plugin_requirements: list[PluginRequirement] | None = None,
    ) -> None:
        super().__init__(config=config, llm_registry=llm_registry)
        self.plugin_requirements = plugin_requirements or []

        self.pending_actions: deque[Action] = deque()
        self.event_stream: EventStream | None = None

        # Safety / hallucination systems
        from backend.engines.orchestrator.file_verification_guard import (
            FileVerificationGuard,
        )
        from backend.engines.orchestrator.hallucination_detector import (
            HallucinationDetector,
        )

        self.hallucination_detector = HallucinationDetector()
        self.anti_hallucination = FileVerificationGuard()
        self.safety_manager: SafetyManagerProtocol = OrchestratorSafetyManager(
            anti_hallucination=self.anti_hallucination,
            hallucination_detector=self.hallucination_detector,
        )

        # Prompt manager + memory subsystems
        self._prompt_manager: PromptManager = self._create_prompt_manager()
        self._memory_manager_impl = ConversationMemoryManager(config, llm_registry)
        self._memory_manager_impl.initialize(self.prompt_manager)
        # Expose conversation_memory for direct test and utility access
        self.conversation_memory = self._memory_manager_impl.conversation_memory
        # Protocol-typed reference for step() logic
        self.memory_manager: MemoryManagerProtocol = self._memory_manager_impl

        # Planner/executor wiring
        self.planner: PlannerProtocol = OrchestratorPlanner(
            config=self.config,
            llm=self.llm,
            safety_manager=self.safety_manager,
        )
        self.tools = self.planner.build_toolset()
        self.executor: ExecutorProtocol = OrchestratorExecutor(
            llm=self.llm,
            safety_manager=self.safety_manager,
            planner=self.planner,
            mcp_tool_name_provider=lambda: self.mcp_tools.keys(),
        )

        # Production health checks
        self.production_health_check_enabled = bool(
            getattr(self.config, "production_health_check", False)
            and getattr(self.config, "health_check_prompts", None)
        )
        self._last_llm_latency: float = 0.0
        self._run_production_health_check()

    # ------------------------------------------------------------------ #
    # Initialization helpers
    # ------------------------------------------------------------------ #
    def _create_prompt_manager(self) -> PromptManager:
        prompt_dir = os.path.join(os.path.dirname(__file__), "prompts")
        system_prompt = self.config.resolved_system_prompt_filename
        if not os.path.exists(os.path.join(prompt_dir, system_prompt)):
            system_prompt = "system_prompt.j2"

        return OrchestratorPromptManager(
            prompt_dir=prompt_dir,
            system_prompt_filename=system_prompt,
            config=self.config,
        )

    def _run_production_health_check(self) -> None:
        try:
            from backend.engines.orchestrator.tools.health_check import (
                run_production_health_check,
            )

            run_production_health_check(raise_on_failure=True)
        except ImportError:
            logger.warning(
                "Health check module not found - skipping dependency validation"
            )
        except RuntimeError as exc:
            logger.error("Production health check failed: %s", exc)
            raise

    # ------------------------------------------------------------------ #
    # Core agent operations
    # ------------------------------------------------------------------ #
    def reset(self, state: State | None = None) -> None:
        super().reset()
        self.pending_actions.clear()

    def step(self, state: State) -> Action:
        try:
            exit_action = self._check_exit_command(state)
            if exit_action:
                return exit_action

            pending = self._consume_pending_action()
            if pending:
                return pending

            condensed = self.memory_manager.condense_history(state)
            return self._execute_llm_step(state, condensed)

        except ContextLimitError:
            # Auto-heal: condense once and retry before giving up
            logger.warning(
                "Auto-Healing: Context limit reached. Attempting condensation + retry."
            )
            try:
                condensed = self.memory_manager.condense_history(state)
                return self._execute_llm_step(state, condensed)
            except Exception:
                logger.warning(
                    "Auto-Healing retry failed after condensation. Falling back to think action."
                )
                return AgentThinkAction(
                    thought="I have reached the context limit. I must condense my memory before proceeding.",
                )

        except ToolExecutionError as e:
            logger.warning("Auto-Healing: Tool Execution Error: %s", e)
            return AgentThinkAction(
                thought=f"I encountered a tool error: {str(e)}. I will analyze the last tool call and retry.",
            )

        except Exception as e:
            logger.error("Critical Failure in Orchestrator.step: %s", e, exc_info=True)
            # Wrap generic exceptions in AgentRuntimeError for standardized handling upstream
            raise AgentRuntimeError(f"Critical agent failure: {str(e)}") from e

    def _execute_llm_step(self, state: State, condensed: Any) -> Action:
        """Core logic to prepare messages, call LLM, and return the first action."""
        if condensed.pending_action:
            return condensed.pending_action

        initial_user_message = self.memory_manager.get_initial_user_message(
            state.history
        )
        messages = self.memory_manager.build_messages(
            condensed_history=condensed.events,
            initial_user_message=initial_user_message,
            llm_config=self.llm.config,
        )
        serialized_messages = self._serialize_messages(messages)
        params = self.planner.build_llm_params(serialized_messages, state, self.tools)
        self._sync_executor_llm()

        result = self.executor.execute(params, self.event_stream)

        # Track LLM latency for adaptive rate governing
        self._last_llm_latency = result.execution_time

        actions = result.actions or []
        if not actions:
            return self._build_fallback_action(result)

        self._queue_additional_actions(actions[1:])
        return actions[0]

    # ------------------------------------------------------------------ #
    # Test/mocking helpers
    # ------------------------------------------------------------------ #
    def set_llm(self, llm) -> None:  # pragma: no cover - used in tests
        """Replace the active LLM and propagate to planner/executor.

        Some unit tests inject a mock LLM after agent construction. The
        executor and planner capture the original reference at init time,
        so we provide an explicit helper to keep their internal references
        in sync to avoid unintended real network calls.
        """
        self.llm = llm
        if hasattr(self, "planner") and hasattr(self.planner, "_llm"):
            try:
                self.planner._llm = llm  # type: ignore[attr-defined]
            except Exception:
                pass
        if hasattr(self, "executor") and hasattr(self.executor, "_llm"):
            try:
                self.executor._llm = llm  # type: ignore[attr-defined]
            except Exception:
                pass

    def _consume_pending_action(self) -> Action | None:
        if self.pending_actions:
            return self.pending_actions.popleft()
        return None

    def _serialize_messages(self, messages: list[Message]) -> list[dict]:
        serialized: list[dict] = []
        for msg in messages:
            serialized.append(self._serialize_single_message(msg))
        return serialized

    def _serialize_single_message(self, msg: Message) -> dict:
        raw = self._serialize_message_with_fallback(msg)
        content_val = raw.get("content", "")
        if isinstance(content_val, list):
            raw["content"] = self._flatten_content_list(content_val)
        return raw

    def _serialize_message_with_fallback(self, msg: Message) -> dict:
        try:
            return msg.serialize_model()  # type: ignore[attr-defined]
        except Exception:
            fallback_lines = self._extract_text_chunks(msg)
            return {
                "role": msg.role,
                "content": "\n".join(fallback_lines),
            }

    def _extract_text_chunks(self, msg: Message) -> list[str]:
        fallback_lines: list[str] = []
        for chunk in getattr(msg, "content", []) or []:
            value = getattr(chunk, "text", None)
            if value is None and isinstance(chunk, dict):
                value = chunk.get("text")
            if value:
                fallback_lines.append(str(value))
        return fallback_lines

    def _flatten_content_list(self, content_val: list[Any]) -> str:
        texts = [
            str(item["text"])
            for item in content_val
            if isinstance(item, dict) and "text" in item
        ]
        return "\n".join(texts)

    def _sync_executor_llm(self) -> None:
        if (
            hasattr(self, "executor")
            and getattr(self.executor, "_llm", None) is not self.llm
        ):
            try:  # pragma: no cover - defensive assignment
                self.executor._llm = self.llm  # type: ignore[attr-defined]
            except Exception:
                pass

    def _build_fallback_action(self, result) -> Action:
        """Create a fallback action when the LLM produces no tool calls.

        This typically means the LLM returned pure-text (e.g. a final answer
        or a refusal).  We surface it as a ``MessageAction`` so the
        controller can decide whether to continue or stop.

        If the LLM returned an entirely empty response we inject a
        diagnostic ``AgentThinkAction`` so the loop doesn't silently
        stall.
        """
        message_text = ""
        if result.response and getattr(result.response, "choices", None):
            first_choice = result.response.choices[0]
            message = getattr(first_choice, "message", None)
            if message is not None:
                message_text = getattr(message, "content", "") or ""

        if not message_text.strip():
            logger.warning(
                "LLM returned an empty response with no tool calls — injecting diagnostic think action"
            )
            return AgentThinkAction(
                thought=(
                    "The LLM returned an empty response with no actions. "
                    "I will re-evaluate the current state and try again."
                )
            )

        fallback = MessageAction(content=message_text)
        fallback.source = EventSource.AGENT
        return fallback

    def _queue_additional_actions(self, actions: list[Action]) -> None:
        for pending in actions:
            self.pending_actions.append(pending)

    # ------------------------------------------------------------------ #
    # Convenience helpers
    # ------------------------------------------------------------------ #
    def _check_exit_command(self, state: State) -> Action | None:
        latest_user_message = state.get_last_user_message()
        if latest_user_message and latest_user_message.content.strip() == "/exit":
            return PlaybookFinishAction()
        return None

    def response_to_actions(self, response) -> list[Action]:
        """Convert an LLM response into executable actions."""
        return codeact_function_calling.response_to_actions(
            response, mcp_tool_names=list(self.mcp_tools.keys())
        )
