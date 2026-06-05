"""Orchestrator agent entrypoint wired to modular planner, executor, and memory subsystems.

Architecture notes (preserve these strengths):
- Protocol-first design: Orchestrator depends on ``PlannerProtocol``,
  ``ExecutorProtocol``, ``SafetyManagerProtocol``, ``MemoryManagerProtocol``
  — never on concrete classes.
- Each subsystem is independently testable and swappable.
- Error recovery follows a typed cascade: ContextLimitError → auto-condense
  → retry → ToolExecutionError → diagnostic think → generic → AgentRuntimeError.
- The event stream is the sole communication channel between controller and agent.

Implementation layout
--------------------
The class is a thin coordinator. Each concern lives in its own module:

* :mod:`backend.engine._orchestrator_helpers`    — top-level utility functions
* :mod:`backend.engine._orchestrator_actions`    — pending/deferred queue
* :mod:`backend.engine._orchestrator_prompts`    — prompt manager + MCP wiring
* :mod:`backend.engine._orchestrator_condensation` — condensation events
* :mod:`backend.engine._orchestrator_recovery`  — step / tool-error recovery
* :mod:`backend.engine._orchestrator_protocol`  — protocol-mode fallbacks
* :mod:`backend.engine._orchestrator_step`      — step(), astep(), LLM step
"""

from __future__ import annotations

import asyncio  # noqa: F401
import contextlib
from collections import deque
from typing import TYPE_CHECKING, Any

from backend.core.config import AgentConfig
from backend.core.interaction_modes import normalize_interaction_mode
from backend.core.logger import app_logger as logger
from backend.engine import function_calling as orchestrator_function_calling
from backend.engine.contracts import (
    ExecutorProtocol,
    MemoryManagerProtocol,
    PlannerProtocol,
    SafetyManagerProtocol,
)
from backend.engine.executor import OrchestratorExecutor
from backend.engine.memory_manager import ContextMemoryManager
from backend.engine.planner import OrchestratorPlanner
from backend.engine.safety import OrchestratorSafetyManager
from backend.execution.plugins import (
    PluginRequirement,
)
from backend.execution.plugins.agent_skills import AgentSkillsRequirement
from backend.inference.llm_registry import LLMRegistry
from backend.orchestration.agent import Agent
from backend.utils.prompt import PromptManager

if TYPE_CHECKING:
    from backend.core.contracts.state import State
    from backend.ledger.action import Action
    from backend.ledger.stream import EventStream


class Orchestrator(Agent):
    """Production orchestrator agent with modular planner–executor–memory architecture."""

    VERSION = '2.2'
    _MAX_QUEUED_ACTIONS_PER_RESPONSE = 2
    runtime_plugins: list[PluginRequirement] = [
        AgentSkillsRequirement(name='agent_skills'),
    ]

    def __init__(
        self,
        config: AgentConfig,
        llm_registry: LLMRegistry,
        plugin_requirements: list[PluginRequirement] | None = None,
    ) -> None:
        super().__init__(config=config, llm_registry=llm_registry)
        self.plugin_requirements = plugin_requirements or []

        self.pending_actions: deque[Action] = deque(maxlen=1000)
        self.deferred_actions: deque[Action] = deque()
        self._consecutive_context_errors = 0
        self._current_delimiter_token: str | None = None
        self._consecutive_invalid_protocol_outputs = 0
        self.event_stream: EventStream | None = None

        # Safety / hallucination systems
        self.safety_manager: SafetyManagerProtocol = OrchestratorSafetyManager()

        # Prompt manager + memory subsystems
        self._prompt_manager: PromptManager = self._create_prompt_manager()
        self._memory_manager_impl = ContextMemoryManager(config, llm_registry)
        self._memory_manager_impl.initialize(self.prompt_manager)
        # Expose conversation_memory for direct test and utility access
        self.conversation_memory = self._memory_manager_impl.conversation_memory
        # Protocol-typed reference for step() logic
        self.memory_manager: MemoryManagerProtocol = self._memory_manager_impl

        # Register vector-memory callback for the semantic_recall tool
        if self.conversation_memory is not None:
            orchestrator_function_calling.register_semantic_recall(
                self.conversation_memory.recall_from_memory
            )

        # Planner/executor wiring
        self.planner: PlannerProtocol = OrchestratorPlanner(
            config=self.config,
            llm=self.llm,
            safety_manager=self.safety_manager,
            agent=self,
        )
        self.tools = self.planner.build_toolset()

        # Tool registry self-check: ensure every tool exposed to the LLM has a
        # corresponding dispatch handler.
        from backend.engine.tool_registry import validate_internal_toolset

        validate_internal_toolset(
            self.tools,
            strict=bool(getattr(self.config, 'strict_tool_registry_check', True)),
        )
        self.executor: ExecutorProtocol = OrchestratorExecutor(
            llm=self.llm,
            safety_manager=self.safety_manager,
            planner=self.planner,
            mcp_tools_provider=lambda: self.mcp_tools,  # pylint: disable=unnecessary-lambda
        )

        # Production health checks
        self.production_health_check_enabled = bool(
            getattr(self.config, 'production_health_check', False)
            and getattr(self.config, 'health_check_prompts', None)
        )
        self._last_llm_latency: float = 0.0
        self._recoverable_tool_error_signature: str = ''
        self._recoverable_tool_error_count: int = 0
        self._reflection_interval: int = int(
            getattr(self.config, 'reflection_interval', 8)
        )
        self._run_production_health_check()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def reset(self, state: State | None = None) -> None:  # type: ignore[override]
        super().reset()
        self.pending_actions.clear()
        self.deferred_actions.clear()
        self._consecutive_context_errors = 0

    def step(self, state: State) -> Action:  # type: ignore[override]
        from backend.engine._orchestrator_step import _step_sync

        return _step_sync(self, state)

    async def astep(self, state: State) -> Action:  # type: ignore[override]
        from backend.engine._orchestrator_step import astep as _astep

        return await _astep(self, state)

    def response_to_actions(self, response) -> list[Action]:
        """Convert an LLM response into executable actions."""
        return orchestrator_function_calling.response_to_actions(
            response,
            mcp_tool_names=list(self.mcp_tools.keys()),
            mcp_tools=self.mcp_tools,
            mode=normalize_interaction_mode(getattr(self.config, 'mode', 'agent')),
        )

    def set_llm(self, llm) -> None:  # pragma: no cover - used in tests
        """Replace the active LLM and propagate to planner/executor/compactor.

        Some unit tests inject a mock LLM after agent construction. The
        executor, planner, and compactor capture the original reference at init
        time, so we provide an explicit helper to keep their internal references
        in sync to avoid unintended real network calls.
        """
        self.llm = llm
        if hasattr(self, 'planner') and hasattr(self.planner, '_llm'):
            with contextlib.suppress(Exception):
                self.planner._llm = llm  # type: ignore[attr-defined]  # pylint: disable=protected-access
        if hasattr(self, 'executor') and hasattr(self.executor, '_llm'):
            with contextlib.suppress(Exception):
                self.executor._llm = llm  # type: ignore[attr-defined]  # pylint: disable=protected-access
        # Also update the memory manager's compactor's LLM reference so
        # token budget calculations use the correct model after a swap.
        if hasattr(self, 'memory_manager'):
            mm = self.memory_manager
            if hasattr(mm, 'compactor') and hasattr(mm.compactor, 'llm'):
                with contextlib.suppress(Exception):
                    mm.compactor.llm = llm

    def set_mcp_tools(self, mcp_tools: list[dict]) -> None:
        """Set MCP tools and sync names to prompt manager for dynamic discovery."""
        super().set_mcp_tools(mcp_tools)
        from backend.engine._orchestrator_prompts import _apply_mcp_tools

        _apply_mcp_tools(self, mcp_tools)

    def clear_queued_actions(self, reason: str = '') -> int:
        from backend.engine._orchestrator_actions import _clear_queued_actions

        return _clear_queued_actions(self, reason)

    def iter_queued_actions(self) -> list[Action]:
        from backend.engine._orchestrator_actions import _iter_queued_actions

        return list(_iter_queued_actions(self))

    # ------------------------------------------------------------------ #
    # Forwarders — each private method delegates to a focused module.
    # Read the class once for the table of contents; follow the import
    # for the implementation.
    # ------------------------------------------------------------------ #
    def _create_prompt_manager(self) -> PromptManager:
        from backend.engine._orchestrator_prompts import _create_prompt_manager as _impl

        return _impl(self)

    def _run_production_health_check(self) -> None:
        try:
            from backend.engine.tools.health_check import (
                run_production_health_check,
            )

            run_production_health_check(raise_on_failure=True)
        except ImportError:
            logger.warning(
                'Health check module not found - skipping dependency validation'
            )
        except RuntimeError as exc:
            logger.error('Production health check failed: %s', exc)
            raise

    def _emit_compaction_status(self) -> None:
        from backend.engine._orchestrator_condensation import (
            _emit_compaction_status as _impl,
        )

        _impl(self)

    def _emit_compaction_status_if_needed(self, state: State) -> bool:  # type: ignore[override]
        from backend.engine._orchestrator_condensation import (
            _emit_compaction_status_if_needed as _impl,
        )

        return _impl(self, state)

    def _reset_step_recovery_counters(self) -> None:
        from backend.engine._orchestrator_recovery import (
            _reset_step_recovery_counters as _impl,
        )

        _impl(self)

    def _astep_handle_tool_execution_error(self, e) -> Action:
        from backend.engine._orchestrator_recovery import (
            _astep_handle_tool_execution_error as _impl,
        )

        return _impl(self, e)

    def _astep_handle_recoverable_tool_call_shape_error(self, e) -> Action:
        from backend.engine._orchestrator_recovery import (
            _astep_handle_recoverable_tool_call_shape_error as _impl,
        )

        return _impl(self, e)

    async def _astep_normal_path(self, state: State) -> Action:
        from backend.engine._orchestrator_step import _astep_normal_path as _impl

        return await _impl(self, state)

    def _consume_pending_action(self) -> Action | None:
        from backend.engine._orchestrator_actions import (
            _consume_pending_action as _impl,
        )

        return _impl(self)

    def _queue_additional_actions(self, actions: list[Action]) -> None:
        from backend.engine._orchestrator_actions import (
            _queue_additional_actions as _impl,
        )

        _impl(self, actions)

    def _promote_deferred_actions(self) -> None:
        from backend.engine._orchestrator_actions import (
            _promote_deferred_actions as _impl,
        )

        _impl(self)

    def _sync_executor_llm(self) -> None:
        from backend.engine._orchestrator_actions import _sync_executor_llm as _impl

        _impl(self)

    def _active_run_mode_for_state(self, state: State) -> str:  # type: ignore[override]
        from backend.engine._orchestrator_actions import (
            _active_run_mode_for_state as _impl,
        )

        return _impl(self, state)

    @staticmethod
    def _has_active_tasks_in_state(state: State) -> bool:
        from backend.engine._orchestrator_actions import (
            _has_active_tasks_in_state as _impl,
        )

        return _impl(state)

    def _set_prompt_tier_from_recent_history(self, state: State) -> None:  # type: ignore[override]
        from backend.engine._orchestrator_prompts import (
            _set_prompt_tier_from_recent_history as _impl,
        )

        _impl(self, state)

    def _mcp_server_prompt_hints(self) -> list[dict[str, str]]:
        from backend.engine._orchestrator_prompts import (
            _mcp_server_prompt_hints as _impl,
        )

        return _impl(self)

    @staticmethod
    def _mcp_tool_descriptions_from_specs(mcp_tools: list[dict]) -> dict[str, str]:
        from backend.engine._orchestrator_prompts import (
            _mcp_tool_descriptions_from_specs as _impl,
        )

        return _impl(mcp_tools)

    def _queue_post_condensation_recovery(self, task_text: str = '') -> None:
        from backend.engine._orchestrator_condensation import (
            _queue_post_condensation_recovery as _impl,
        )

        _impl(self, task_text)

    def _handle_pending_action_from_condensation(
        self, state: State, condensed: Any
    ) -> Action | None:
        from backend.engine._orchestrator_condensation import (
            _handle_pending_action_from_condensation as _impl,
        )

        return _impl(self, state, condensed)

    @staticmethod
    def _is_noop_condensation_action(action: object | None) -> bool:
        from backend.engine._orchestrator_condensation import (
            _is_noop_condensation_action as _impl,
        )

        return _impl(action)

    def _build_fallback_action(self, result) -> Action:
        from backend.engine._orchestrator_protocol import (
            _build_fallback_action as _impl,
        )

        return _impl(self, result)

    @staticmethod
    def _visible_fallback_message_text(message_text: str) -> str:
        from backend.engine._orchestrator_protocol import (
            _visible_fallback_message_text as _impl,
        )

        return _impl(message_text)

    def _protocol_mode_fallback_message(
        self,
        message_text: str,
        reasoning: str,
        state: object | None,
        *,
        mode: str,
    ) -> Action:
        from backend.engine._orchestrator_protocol import (
            _protocol_mode_fallback_message as _impl,
        )

        return _impl(self, message_text, reasoning, state, mode=mode)

    @staticmethod
    def _synthesize_plain_text_finish(
        message_text: str, *, mode: str
    ) -> Any:
        from backend.engine._orchestrator_protocol import (
            _synthesize_plain_text_finish as _impl,
        )

        return _impl(message_text, mode=mode)

    def _generate_delimiter_token(self) -> str:
        from backend.engine._orchestrator_step import _generate_delimiter_token as _impl

        return _impl(self)

    def _check_exit_command(self, state: State) -> Action | None:
        from backend.engine._orchestrator_step import _check_exit_command as _impl

        return _impl(self, state)

    def _execute_llm_step(self, state: State, condensed: Any) -> Action:  # type: ignore[override]
        from backend.engine._orchestrator_step import _execute_llm_step as _impl

        return _impl(self, state, condensed)

    async def _execute_llm_step_async(self, state: State, condensed: Any) -> Action:  # type: ignore[override]
        from backend.engine._orchestrator_step import _execute_llm_step_async as _impl

        return await _impl(self, state, condensed)

    async def _attempt_graceful_context_degradation(
        self, state: State
    ) -> Action | None:
        from backend.engine._orchestrator_step import (
            _attempt_graceful_context_degradation as _impl,
        )

        return await _impl(self, state)
