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

import backend.engine.function_calling as orchestrator_function_calling
from backend.core.config import AgentConfig
from backend.core.errors import (
    AgentRuntimeError,
    ContextLimitError,
    ModelProviderError,
    ToolExecutionError,
)
from backend.core.logger import app_logger as logger
from backend.execution.plugins import (
    PluginRequirement,
)
from backend.execution.plugins.agent_skills import AgentSkillsRequirement
from backend.inference.exceptions import LLMError
from backend.inference.llm_registry import LLMRegistry
from backend.ledger.action import AgentThinkAction, MessageAction, PlaybookFinishAction
from backend.ledger.action.agent import CondensationAction
from backend.ledger.event import EventSource
from backend.orchestration.agent import Agent
from backend.orchestration.state.state import State
from backend.utils.prompt import OrchestratorPromptManager, PromptManager

from . import message_serializer
from .contracts import (
    ExecutorProtocol,
    MemoryManagerProtocol,
    PlannerProtocol,
    SafetyManagerProtocol,
)
from .executor import OrchestratorExecutor
from .memory_manager import ContextMemoryManager
from .planner import OrchestratorPlanner
from .safety import OrchestratorSafetyManager

if TYPE_CHECKING:
    from backend.ledger.action import Action
    from backend.ledger.stream import EventStream


class Orchestrator(Agent):
    """Production orchestrator agent with modular planner–executor–memory architecture."""

    VERSION = '2.2'
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

        self.pending_actions: deque[Action] = deque()
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
        self._reflection_interval: int = int(
            getattr(self.config, 'reflection_interval', 8)
        )
        self._run_production_health_check()

    # ------------------------------------------------------------------ #
    # Initialization helpers
    # ------------------------------------------------------------------ #
    def _create_prompt_manager(self) -> PromptManager:
        prompt_dir = os.path.join(os.path.dirname(__file__), 'prompts')
        system_prompt = self.config.resolved_system_prompt_filename
        if not os.path.exists(os.path.join(prompt_dir, system_prompt)):
            system_prompt = 'system_prompt'

        resolved_model = ''
        try:
            resolved_model = (self.llm.config.model or '').strip()
        except Exception:
            pass
        if not resolved_model and self.llm_registry:
            try:
                llm_cfg = self.llm_registry.config.get_llm_config_from_agent_config(
                    self.config
                )
                if llm_cfg and getattr(llm_cfg, 'model', None):
                    resolved_model = str(llm_cfg.model).strip()
            except Exception:
                pass

        return OrchestratorPromptManager(
            prompt_dir=prompt_dir,
            system_prompt_filename=system_prompt,
            config=self.config,
            resolved_llm_model_id=resolved_model or None,
            app_config=self.llm_registry.config if self.llm_registry else None,
        )

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

    # ------------------------------------------------------------------ #
    # Core agent operations
    # ------------------------------------------------------------------ #
    def reset(self, state: State | None = None) -> None:
        super().reset()
        self.pending_actions.clear()
        self._consecutive_context_errors = 0

    def step(self, state: State) -> Action:
        """Thin synchronous wrapper around astep() to avoid maintaining duplicate logic."""
        import asyncio
        import concurrent.futures

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, create and run a new one
            return asyncio.run(self.astep(state))
        else:
            # Already in an async context; create a task and run in a new thread
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, self.astep(state))
                return future.result()

    async def astep(self, state: State) -> Action:
        """Async version of step() with hard circuit breaker for consecutive ContextLimitErrors."""
        try:
            exit_action = self._check_exit_command(state)
            if exit_action:
                self._consecutive_context_errors = 0
                return exit_action

            pending = self._consume_pending_action()
            if pending:
                self._consecutive_context_errors = 0
                return pending

            condensed = self.memory_manager.condense_history(state)
            action = await self._execute_llm_step_async(state, condensed)
            # Successful step: reset the circuit breaker counter
            self._consecutive_context_errors = 0
            return action

        except ContextLimitError:
            self._consecutive_context_errors = (
                getattr(self, '_consecutive_context_errors', 0) + 1
            )
            logger.warning(
                'ContextLimitError encountered (%d/6). Attempting condensation + retry.',
                self._consecutive_context_errors,
            )

            # Circuit breaker: fail hard if we hit >6 consecutive ContextLimitErrors.
            # Previous threshold of 3 was too aggressive — transient tokenizer
            # errors or single-message overflows can cause short bursts that
            # resolve after condensation.
            if self._consecutive_context_errors > 6:
                raise AgentRuntimeError(
                    'Circuit breaker: continuous ContextLimitErrors'
                ) from None

            # Try auto-heal: condense once and retry
            try:
                condensed = self.memory_manager.condense_history(state)
                action = await self._execute_llm_step_async(state, condensed)
                # Successful retry: reset the counter
                self._consecutive_context_errors = 0
                return action
            except ContextLimitError:
                # Re-raise to trigger circuit breaker check on next attempt
                raise
            except Exception:
                logger.warning(
                    'Auto-Healing retry failed after condensation. Falling back to think action.'
                )
                return AgentThinkAction(
                    thought='I have reached the context limit. I must condense my memory before proceeding.',
                )

        except ToolExecutionError as e:
            self._consecutive_context_errors = 0
            logger.warning('Auto-Healing: Tool Execution Error: %s', e)
            return AgentThinkAction(
                thought=f'I encountered a tool error: {str(e)}. I will analyze the last tool call and retry.',
            )

        except (ModelProviderError, LLMError):
            self._consecutive_context_errors = 0
            raise

        except Exception as e:
            self._consecutive_context_errors = 0
            logger.error('Critical Failure in Orchestrator.astep: %s', e, exc_info=True)
            raise AgentRuntimeError(f'Critical agent failure: {str(e)}') from e

    def _handle_pending_action_from_condensation(
        self, state: State, condensed: Any
    ) -> Action | None:
        """If condensed has pending_action, queue recovery and return it. Else None."""
        if not condensed.pending_action:
            return None
        if self._is_noop_condensation_action(condensed.pending_action):
            return condensed.pending_action
        task_text = ''
        try:
            initial_msg = self.memory_manager.get_initial_user_message(state.history)
            task_text = (getattr(initial_msg, 'content', '') or '')[:200]
        except Exception:
            pass
        self._queue_post_condensation_recovery(task_text=task_text)
        return condensed.pending_action

    @staticmethod
    def _is_noop_condensation_action(action: object | None) -> bool:
        if not isinstance(action, CondensationAction):
            return False
        if action.summary is not None:
            return False
        return len(action.pruned) == 0

    def _set_prompt_tier_from_recent_history(self, state: State) -> None:
        """Escalate to debug tier on recent errors or elevated-risk file operations."""
        try:
            from backend.core.enums import ActionSecurityRisk
            from backend.ledger.action import FileEditAction, FileWriteAction
            from backend.ledger.observation import ErrorObservation

            recent = state.history[-12:] if len(state.history) > 12 else state.history
            if any(isinstance(e, ErrorObservation) for e in recent):
                self.prompt_manager.set_prompt_tier('debug')
                return
            for e in recent:
                if isinstance(e, (FileEditAction, FileWriteAction)):
                    risk = getattr(e, 'security_risk', ActionSecurityRisk.UNKNOWN)
                    if risk in (ActionSecurityRisk.MEDIUM, ActionSecurityRisk.HIGH):
                        self.prompt_manager.set_prompt_tier('debug')
                        return
            self.prompt_manager.set_prompt_tier('base')
        except Exception:
            pass

    def _execute_llm_step(self, state: State, condensed: Any) -> Action:
        """Core logic to prepare messages, call LLM, and return the first action."""
        pending = self._handle_pending_action_from_condensation(state, condensed)
        if pending is not None:
            return pending

        initial_user_message = self.memory_manager.get_initial_user_message(
            state.history
        )
        self._set_prompt_tier_from_recent_history(state)

        messages = self.memory_manager.build_messages(
            condensed_history=condensed.events,
            initial_user_message=initial_user_message,
            llm_config=self.llm.config,
        )
        serialized_messages = message_serializer.serialize_messages(messages)
        params = self.planner.build_llm_params(serialized_messages, state, self.tools)
        self._sync_executor_llm()

        result = self.executor.execute(params, self.event_stream)

        try:
            if hasattr(state, 'ack_planning_directive'):
                state.ack_planning_directive(source='Orchestrator')
            if hasattr(state, 'ack_memory_pressure'):
                state.ack_memory_pressure(source='Orchestrator')
        finally:
            extra_data = getattr(state, 'extra_data', None)
            if isinstance(extra_data, dict):
                extra_data.pop('planning_directive', None)
                extra_data.pop('memory_pressure', None)

        self._last_llm_latency = result.execution_time

        actions = result.actions or []
        if not actions:
            return self._build_fallback_action(result)
        self._queue_additional_actions(actions[1:])
        return actions[0]

    async def _execute_llm_step_async(self, state: State, condensed: Any) -> Action:
        """Async variant of _execute_llm_step using real LLM streaming."""
        pending = self._handle_pending_action_from_condensation(state, condensed)
        if pending is not None:
            return pending

        initial_user_message = self.memory_manager.get_initial_user_message(
            state.history
        )
        self._set_prompt_tier_from_recent_history(state)

        messages = self.memory_manager.build_messages(
            condensed_history=condensed.events,
            initial_user_message=initial_user_message,
            llm_config=self.llm.config,
        )
        serialized_messages = message_serializer.serialize_messages(messages)
        params = self.planner.build_llm_params(serialized_messages, state, self.tools)
        self._sync_executor_llm()

        result = await self.executor.async_execute(params, self.event_stream)

        try:
            if hasattr(state, 'ack_planning_directive'):
                state.ack_planning_directive(source='Orchestrator')
            if hasattr(state, 'ack_memory_pressure'):
                state.ack_memory_pressure(source='Orchestrator')
        finally:
            extra_data = getattr(state, 'extra_data', None)
            if isinstance(extra_data, dict):
                extra_data.pop('planning_directive', None)
                extra_data.pop('memory_pressure', None)

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
        if hasattr(self, 'planner') and hasattr(self.planner, '_llm'):
            try:
                self.planner._llm = llm  # type: ignore[attr-defined]  # pylint: disable=protected-access
            except Exception:
                pass
        if hasattr(self, 'executor') and hasattr(self.executor, '_llm'):
            try:
                self.executor._llm = llm  # type: ignore[attr-defined]  # pylint: disable=protected-access
            except Exception:
                pass

    def _consume_pending_action(self) -> Action | None:
        if not self.pending_actions:
            return None
        # Try to batch consecutive read-only file reads into one action
        from .file_reads import try_batch_file_reads

        batched = try_batch_file_reads(self.pending_actions)
        if batched:
            return batched
        return self.pending_actions.popleft()

    def _sync_executor_llm(self) -> None:
        if (
            hasattr(self, 'executor')
            and getattr(self.executor, '_llm', None) is not self.llm
        ):
            try:  # pragma: no cover - defensive assignment
                self.executor._llm = self.llm  # type: ignore[attr-defined]  # pylint: disable=protected-access
            except Exception:
                pass

    def _build_fallback_action(self, result) -> Action:
        """Create a message action when the LLM returns no tool calls.

        This typically means the LLM returned pure-text (e.g. a final answer
        or a refusal). We surface it as a ``MessageAction`` so the controller
        can decide whether to continue or stop.
        """
        message_text = ''
        if result.response and getattr(result.response, 'choices', None):
            first_choice = result.response.choices[0]
            message = getattr(first_choice, 'message', None)
            if message is not None:
                message_text = getattr(message, 'content', '') or ''

        if not message_text.strip():
            raise ModelProviderError(
                'LLM returned an empty response with no tool calls'
            )

        fallback = MessageAction(content=message_text)
        fallback.source = EventSource.AGENT
        return fallback

    def _queue_additional_actions(self, actions: list[Action]) -> None:
        for pending in actions:
            self.pending_actions.append(pending)

    def _queue_post_condensation_recovery(self, task_text: str = '') -> None:
        """Queue a brief think action after condensation to break the re-condensation loop.

        The agent_controller drain loop calls astep() immediately after dispatching
        a CondensationAction. The event-delivery pipeline (background thread →
        ThreadPoolExecutor → call_soon_threadsafe → ensure_future) needs at least
        2 event-loop ticks before state.history reflects the CondensationAction.

        With only asyncio.sleep(0) (1 tick) in the drain loop, the next astep()
        call sees stale state, condense_history() concludes condensation is still
        needed, and returns another CondensationAction — an infinite loop.

        Queuing an AgentThinkAction here ensures _consume_pending_action() returns
        it on the very next astep() call, skipping condense_history() entirely.
        By the time the ThinkAction's observation triggers the following step,
        state.history already contains the original CondensationAction.
        """
        self.pending_actions.append(
            AgentThinkAction(thought='Memory condensed. Resuming task.')
        )

    # ------------------------------------------------------------------ #
    # Convenience helpers
    # ------------------------------------------------------------------ #
    def _check_exit_command(self, state: State) -> Action | None:
        latest_user_message = state.get_last_user_message()
        if latest_user_message and latest_user_message.content.strip() == '/exit':
            return PlaybookFinishAction()
        return None

    def response_to_actions(self, response) -> list[Action]:
        """Convert an LLM response into executable actions."""
        return orchestrator_function_calling.response_to_actions(
            response,
            mcp_tool_names=list(self.mcp_tools.keys()),
            mcp_tools=self.mcp_tools,
        )

    def _mcp_server_prompt_hints(self) -> list[dict[str, str]]:
        """Build ``[{"server": name, "hint": text}, ...]`` from MCP ``usage_hint`` fields."""
        try:
            app_cfg = getattr(self.llm_registry, 'config', None)
            mcp = getattr(app_cfg, 'mcp', None) if app_cfg is not None else None
            servers = getattr(mcp, 'servers', None) or []
            rows: list[dict[str, str]] = []
            for s in servers:
                hint = (getattr(s, 'usage_hint', None) or '').strip()
                if not hint:
                    continue
                name = (getattr(s, 'name', None) or '').strip() or 'unknown'
                rows.append({'server': name, 'hint': hint})
            return rows
        except Exception:
            return []

    def set_mcp_tools(self, mcp_tools: list[dict]) -> None:
        """Set MCP tools and sync names to prompt manager for dynamic discovery."""
        super().set_mcp_tools(mcp_tools)

        # Warn early if MCP tool names collide with internal tool names.
        from backend.engine.tool_registry import (
            validate_mcp_tool_name_collisions,
        )

        validate_mcp_tool_name_collisions(
            self.tools,
            self.mcp_tools.keys(),
            strict=bool(getattr(self.config, 'strict_mcp_tool_name_collision', False)),
        )
        # Sync connected tool names and descriptions so the system prompt reflects reality
        pm = getattr(self, '_prompt_manager', None)
        if pm and hasattr(pm, 'mcp_tool_names'):
            pm.mcp_tool_names = list(self.mcp_tools.keys())
            descriptions: dict[str, str] = {}
            for tool_dict in mcp_tools:
                fn = tool_dict.get('function') or {}
                name = fn.get('name') or tool_dict.get('name', '')
                desc = fn.get('description') or tool_dict.get('description', '')
                if name and desc:
                    first_line = desc.split('\n')[0][:120]
                    descriptions[name] = first_line
            if hasattr(pm, 'mcp_tool_descriptions'):
                pm.mcp_tool_descriptions = descriptions
            if hasattr(pm, 'mcp_server_hints'):
                pm.mcp_server_hints = self._mcp_server_prompt_hints()
        # Surface any MCP connection failures before the first user response so the
        # agent immediately knows which tools are unavailable, avoiding wasted turns
        # diagnosing connectivity issues at call-time.
        from backend.integrations.mcp.error_collector import mcp_error_collector

        errors = mcp_error_collector.get_errors()
        if errors:
            lines = [
                'WARNING: Some MCP servers failed to connect. '
                'The following tools may be unavailable:',
            ]
            for err in errors:
                lines.append(
                    f'  - {err.server_name} ({err.server_type}): {err.error_message}'
                )
            lines.append('Do not attempt to call these tools. Plan accordingly.')
            think = AgentThinkAction(thought='\n'.join(lines))
            self.pending_actions.appendleft(think)
