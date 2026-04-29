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

import asyncio
import contextlib
import os
from collections import deque
from typing import TYPE_CHECKING, Any

import backend.engine.function_calling as orchestrator_function_calling
from backend.core.config import AgentConfig
from backend.core.constants import (
    DEFAULT_AGENT_MAX_CONTEXT_LIMIT_ERRORS,
    DEFAULT_AGENT_RECOVERABLE_TOOL_ERROR_THRESHOLD,
)
from backend.core.contracts.state import State
from backend.core.errors import (
    AgentRuntimeError,
    ContextLimitError,
    FunctionCallConversionError,
    FunctionCallNotExistsError,
    FunctionCallValidationError,
    LLMMalformedActionError,
    LLMNoActionError,
    ModelProviderError,
    ToolExecutionError,
)
from backend.core.logger import app_logger as logger
from backend.engine import message_serializer
from backend.engine import prompt_role_debug as _prompt_role_debug
from backend.engine.common import (
    FunctionCallNotExistsError as CommonFunctionCallNotExistsError,
)
from backend.engine.common import (
    FunctionCallValidationError as CommonFunctionCallValidationError,
)
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
from backend.inference.exceptions import LLMError
from backend.inference.llm_registry import LLMRegistry
from backend.ledger.action import AgentThinkAction, MessageAction, PlaybookFinishAction
from backend.ledger.action.agent import CondensationAction
from backend.ledger.event import EventSource
from backend.orchestration.agent import Agent
from backend.utils.prompt import OrchestratorPromptManager, PromptManager

if TYPE_CHECKING:
    from backend.ledger.action import Action
    from backend.ledger.stream import EventStream


def _graceful_shrink_large_cmd_outputs(history: list[Any]) -> int:
    """Truncate oversized command outputs; returns count mutated."""
    from backend.ledger.observation import (
        CmdOutputObservation,
    )

    shrunk = 0
    for ev in history:
        if not isinstance(ev, CmdOutputObservation):
            continue
        content = getattr(ev, 'content', '') or ''
        if len(content) <= 2000:
            continue
        head = content[:800]
        tail = content[-800:]
        ev.content = (
            f'{head}\n... [graceful-degradation truncated '
            f'{len(content) - 1600} chars] ...\n{tail}'
        )
        shrunk += 1
    return shrunk


def _graceful_trim_old_error_observations(history: list[Any]) -> int:
    """Replace oldest ErrorObservations beyond the last five; returns count mutated."""
    from backend.ledger.observation.error import ErrorObservation

    errors = [
        i for i, ev in enumerate(history) if isinstance(ev, ErrorObservation)
    ]
    dropped = 0
    if len(errors) <= 5:
        return dropped
    for idx in errors[:-5]:
        ev = history[idx]
        if not isinstance(ev, ErrorObservation):
            continue
        msg = (ev.content or '')[:200]
        ev.content = f'[graceful-degradation: error trimmed] {msg}'
        dropped += 1
    return dropped


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

        self.pending_actions: deque[Action] = deque()
        self.deferred_actions: deque[Action] = deque()
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
        self._recoverable_tool_error_signature: str = ''
        self._recoverable_tool_error_count: int = 0
        self._reflection_interval: int = int(
            getattr(self.config, 'reflection_interval', 8)
        )
        self._run_production_health_check()

    # ------------------------------------------------------------------ #
    # Initialization helpers
    # ------------------------------------------------------------------ #
    def _create_prompt_manager(self) -> PromptManager:
        prompt_dir = os.path.join(os.path.dirname(__file__), 'prompts')

        resolved_model = ''
        with contextlib.suppress(Exception):
            resolved_model = (self.llm.config.model or '').strip()
        if not resolved_model and self.llm_registry:
            with contextlib.suppress(Exception):
                llm_cfg = self.llm_registry.config.get_llm_config_from_agent_config(
                    self.config
                )
                if llm_cfg and getattr(llm_cfg, 'model', None):
                    resolved_model = str(llm_cfg.model).strip()
        return OrchestratorPromptManager(
            prompt_dir=prompt_dir,
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
        self.deferred_actions.clear()
        self._consecutive_context_errors = 0

    def step(self, state: State) -> Action:
        """Synchronous compatibility wrapper around :meth:`astep`.

        Prefer ``await astep(state)`` from any async context. This shim only
        exists for two scenarios and refuses anything else:

        * No running loop in this thread → ``asyncio.run(astep(state))``.
          Used by sync test entry points and offline replay tools.
        * Running loop in this thread that is **not** the registered main
          loop, and the registered main loop *is* running → schedule
          ``astep`` on the main loop via
          ``asyncio.run_coroutine_threadsafe`` so any cross-loop primitives
          inside ``astep`` (Locks/Events/Queues bound to the main loop)
          stay attached to the right loop.

        Calling ``step()`` from inside the main loop itself, or from a
        worker thread when no main loop is registered, used to silently
        fall back to an isolated event loop in a one-shot
        ``ThreadPoolExecutor``. That fallback orphaned cross-loop
        primitives and hid the misuse \u2014 it is now an explicit
        ``RuntimeError``. The only production caller (replay-mode
        ``ConfirmationService``) now uses :meth:`astep` directly via
        :meth:`ConfirmationService.aget_next_action`, so this branch is
        no longer reachable from the agent loop.
        """
        import asyncio
        import threading

        from backend.utils.async_utils import get_main_event_loop

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if current_loop is None:
            return asyncio.run(self.astep(state))

        main_loop = get_main_event_loop()
        if (
            main_loop is not None
            and main_loop is not current_loop
            and main_loop.is_running()
        ):
            # Run on the registered main loop so cross-loop primitives stay
            # attached to the right loop.
            future = asyncio.run_coroutine_threadsafe(self.astep(state), main_loop)
            return future.result()

        raise RuntimeError(
            'Engine.step() was called from inside a running event loop with no '
            'separate registered main loop available. Use ``await self.astep(state)`` '
            f'instead. caller_thread={threading.current_thread().name}'
        )

    async def _attempt_graceful_context_degradation(
        self, state: State
    ) -> Action | None:
        """Last-resort context shrinking before raising AgentRuntimeError.

        Strategy (most-aggressive last):

        1. Truncate the largest non-error tool observations in history (the
           usual culprits: ``cat`` of a giant file, ``git log --all``, build
           output) to a small head/tail.
        2. Drop oldest plain ErrorObservations except the most recent few.
        3. Re-condense and retry the LLM step once.

        Returns the next Action on success, or ``None`` if degradation could
        not produce a usable response (caller should raise).
        """
        if not getattr(state, 'history', None):
            return None
        try:
            shrunk = _graceful_shrink_large_cmd_outputs(state.history)
            dropped = _graceful_trim_old_error_observations(state.history)
            logger.warning(
                'Graceful context degradation: shrunk %d cmd outputs, '
                'trimmed %d error observations',
                shrunk,
                dropped,
            )
            if shrunk == 0 and dropped == 0:
                return None
            condensed = self.memory_manager.condense_history(state)
            return await self._execute_llm_step_async(state, condensed)
        except ContextLimitError:
            logger.error('Graceful degradation insufficient — context still overflows')
            return None
        except Exception as exc:  # pragma: no cover — defensive
            logger.error(
                'Graceful degradation raised unexpectedly: %s', exc, exc_info=True
            )
            return None

    def _reset_step_recovery_counters(self) -> None:
        """Clear context-limit and recoverable tool-call replay counters."""
        self._consecutive_context_errors = 0
        self._recoverable_tool_error_signature = ''
        self._recoverable_tool_error_count = 0

    async def _astep_normal_path(self, state: State) -> Action:
        """Happy path: optional exit/deferred/pending handling then LLM step."""
        if exit_action := self._check_exit_command(state):
            self._reset_step_recovery_counters()
            return exit_action

        if not self.pending_actions and self.deferred_actions:
            self._promote_deferred_actions()

        if pending := self._consume_pending_action():
            self._reset_step_recovery_counters()
            return pending

        condensed = self.memory_manager.condense_history(state)
        action = await self._execute_llm_step_async(state, condensed)
        self._reset_step_recovery_counters()
        return action

    async def _astep_handle_context_limit_error(self, state: State) -> Action:
        """Condense/retry after ContextLimitError; may degrade or raise."""
        self._consecutive_context_errors = (
            getattr(self, '_consecutive_context_errors', 0) + 1
        )
        logger.warning(
            'ContextLimitError encountered (%d/%d). Attempting condensation + retry.',
            self._consecutive_context_errors,
            DEFAULT_AGENT_MAX_CONTEXT_LIMIT_ERRORS,
        )

        if self._consecutive_context_errors > DEFAULT_AGENT_MAX_CONTEXT_LIMIT_ERRORS:
            degraded = await self._attempt_graceful_context_degradation(state)
            if degraded is not None:
                self._consecutive_context_errors = 0
                return degraded
            raise AgentRuntimeError(
                'Circuit breaker: continuous ContextLimitErrors'
            ) from None

        try:
            condensed = self.memory_manager.condense_history(state)
            action = await self._execute_llm_step_async(state, condensed)
            self._consecutive_context_errors = 0
            return action
        except ContextLimitError:
            raise
        except Exception:
            logger.warning(
                'Auto-Healing retry failed after condensation. Falling back to think action.'
            )
            return AgentThinkAction(
                thought='I have reached the context limit. I must condense my memory before proceeding.',
            )

    def _astep_handle_tool_execution_error(self, e: ToolExecutionError) -> Action:
        self._consecutive_context_errors = 0
        logger.warning('Auto-Healing: Tool Execution Error: %s', e)

        removed = self.clear_queued_actions(
            reason='Tool execution failed, aborting batched sequence'
        )
        if removed > 0:
            logger.info(
                'Batched sequence aborted! Dispelled %d blind follow-up actions.',
                removed,
            )

        return AgentThinkAction(
            thought=f'I encountered a tool error: {str(e)}. I will analyze the last tool call and retry.',
        )

    def _astep_handle_recoverable_tool_call_shape_error(self, e: Exception) -> Action:
        self._consecutive_context_errors = 0
        logger.warning('Recoverable LLM tool-call error: %s', e)

        error_signature = f'{type(e).__name__}:{str(e).strip()}'
        if error_signature == self._recoverable_tool_error_signature:
            self._recoverable_tool_error_count += 1
        else:
            self._recoverable_tool_error_signature = error_signature
            self._recoverable_tool_error_count = 1

        removed = self.clear_queued_actions(
            reason='Invalid LLM tool call, aborting batched sequence'
        )
        if removed > 0:
            logger.info(
                'Batched sequence aborted! Dispelled %d blind follow-up actions.',
                removed,
            )

        if (
            self._recoverable_tool_error_count
            >= DEFAULT_AGENT_RECOVERABLE_TOOL_ERROR_THRESHOLD
        ):
            return AgentThinkAction(
                thought=(
                    '[TOOL_CALL_RECOVERABLE_ERROR_ESCALATED] The same invalid tool call pattern '
                    'repeated 3 times and was blocked. You must change strategy now: '
                    're-read relevant file context and emit a different corrected action '
                    '(or switch tool), not a near-identical retry.'
                )
            )

        return AgentThinkAction(
            thought=(
                '[TOOL_CALL_RECOVERABLE_ERROR] The previous tool call was invalid and was not executed. '
                f'Details: {str(e)}\n'
                'I will emit one corrected tool call with valid JSON arguments '
                '(double-quoted keys/strings, escaped newlines/quotes, required arguments present).'
            )
        )

    async def astep(self, state: State) -> Action:
        """Async version of step() with hard circuit breaker for consecutive ContextLimitErrors."""
        try:
            return await self._astep_normal_path(state)
        except ContextLimitError:
            return await self._astep_handle_context_limit_error(state)
        except ToolExecutionError as e:
            return self._astep_handle_tool_execution_error(e)
        except (
            FunctionCallValidationError,
            FunctionCallNotExistsError,
            CommonFunctionCallValidationError,
            CommonFunctionCallNotExistsError,
            FunctionCallConversionError,
            LLMMalformedActionError,
        ) as e:
            return self._astep_handle_recoverable_tool_call_shape_error(e)

        except (ModelProviderError, LLMError, LLMNoActionError):
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
        with contextlib.suppress(Exception):
            initial_msg = self.memory_manager.get_initial_user_message(state.history)
            task_text = (getattr(initial_msg, 'content', '') or '')[:200]
        self._queue_post_condensation_recovery(task_text=task_text)
        return condensed.pending_action

    @staticmethod
    def _is_noop_condensation_action(action: object | None) -> bool:
        if not isinstance(action, CondensationAction):
            return False
        return False if action.summary is not None else len(action.pruned) == 0

    def _set_prompt_tier_from_recent_history(self, state: State) -> None:
        """Escalate to debug tier on recent errors or elevated-risk file operations."""
        with contextlib.suppress(Exception):
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

    def _execute_llm_step(self, state: State, condensed: Any) -> Action:
        """Core logic to prepare messages, call LLM, and return the first action."""
        pending = self._handle_pending_action_from_condensation(state, condensed)
        if pending is not None:
            return pending

        initial_user_message = self.memory_manager.get_initial_user_message(
            state.history
        )
        self._set_prompt_tier_from_recent_history(state)

        astep_id = (
            _prompt_role_debug.mark_astep_begin()
            if _prompt_role_debug.any_prompt_or_reasoning_debug()
            else 0
        )
        messages = self.memory_manager.build_messages(
            condensed_history=condensed.events,
            initial_user_message=initial_user_message,
            llm_config=self.llm.config,
        )
        _prompt_role_debug.log_prompt_roles_after_build_messages(
            messages,
            astep_id=astep_id,
            condensed_event_count=len(condensed.events),
            pending_condensation=condensed.pending_action is not None,
            history_event_count=len(state.history),
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

        astep_id = (
            _prompt_role_debug.mark_astep_begin()
            if _prompt_role_debug.any_prompt_or_reasoning_debug()
            else 0
        )

        def _prepare_params() -> dict[str, Any]:
            messages = self.memory_manager.build_messages(
                condensed_history=condensed.events,
                initial_user_message=initial_user_message,
                llm_config=self.llm.config,
            )
            _prompt_role_debug.log_prompt_roles_after_build_messages(
                messages,
                astep_id=astep_id,
                condensed_event_count=len(condensed.events),
                pending_condensation=condensed.pending_action is not None,
                history_event_count=len(state.history),
            )
            serialized_messages = message_serializer.serialize_messages(messages)
            return self.planner.build_llm_params(serialized_messages, state, self.tools)

        params = await asyncio.to_thread(_prepare_params)
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
            with contextlib.suppress(Exception):
                self.planner._llm = llm  # type: ignore[attr-defined]  # pylint: disable=protected-access
        if hasattr(self, 'executor') and hasattr(self.executor, '_llm'):
            with contextlib.suppress(Exception):
                self.executor._llm = llm  # type: ignore[attr-defined]  # pylint: disable=protected-access

    def _consume_pending_action(self) -> Action | None:
        if not self.pending_actions:
            return None
        # Try to batch consecutive read-only file reads into one action
        from backend.engine.file_reads import try_batch_file_reads

        batched = try_batch_file_reads(self.pending_actions)
        return batched if batched else self.pending_actions.popleft()

    def _sync_executor_llm(self) -> None:
        if (
            hasattr(self, 'executor')
            and getattr(self.executor, '_llm', None) is not self.llm
        ):
            with contextlib.suppress(Exception):
                self.executor._llm = self.llm  # type: ignore[attr-defined]  # pylint: disable=protected-access

    def _build_fallback_action(self, result) -> Action:
        """Create a message action when the LLM returns no tool calls.

        Always ``wait_for_response=False`` so the loop continues regardless of
        what the model emitted (planning blobs, narration, leaked reasoning).
        If the model genuinely wants to pause for user input it must call an
        explicit tool (``communicate_with_user``) — not rely on this path.

        Empty text → raises :class:`LLMNoActionError` so the recovery machinery
        in :class:`ActionExecutionService` can issue corrective feedback and retry.
        Text-only → wraps in :class:`MessageAction` (loop continues).
        """
        message_text = ''
        if result.response and getattr(result.response, 'choices', None):
            first_choice = result.response.choices[0]
            message = getattr(first_choice, 'message', None)
            if message is not None:
                raw = getattr(message, 'content', '') or ''
                message_text = raw if isinstance(raw, str) else str(raw)

        if not message_text.strip():
            raise LLMNoActionError(
                'LLM returned no tool calls and no content. '
                'The model must emit at least one tool call per step.'
            )

        logger.warning(
            'LLM returned text-only response with no tool calls — continuing loop. '
            'Model should use explicit tool calls instead of plain text output.'
        )
        fallback = MessageAction(content=message_text, wait_for_response=False)
        fallback.source = EventSource.AGENT
        return fallback

    def _queue_additional_actions(self, actions: list[Action]) -> None:
        for pending in actions:
            self.pending_actions.append(pending)

    def _promote_deferred_actions(self) -> None:
        """Promote a bounded set of deferred actions into the active queue."""
        while self.deferred_actions:
            self.pending_actions.append(self.deferred_actions.popleft())

    def clear_queued_actions(self, reason: str = '') -> int:
        """Clear pending/deferred queues explicitly (used by stuck recovery)."""
        removed = len(self.pending_actions) + len(self.deferred_actions)
        self.pending_actions.clear()
        self.deferred_actions.clear()
        if removed > 0:
            logger.warning(
                'Cleared %d queued actions (%s)', removed, reason or 'no reason'
            )
        return removed

    def iter_queued_actions(self) -> list[Action]:
        """Return a snapshot of all queued actions, pending first then deferred."""
        return [*self.pending_actions, *self.deferred_actions]

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

    @staticmethod
    def _mcp_tool_descriptions_from_specs(mcp_tools: list[dict]) -> dict[str, str]:
        descriptions: dict[str, str] = {}
        for tool_dict in mcp_tools:
            fn = tool_dict.get('function') or {}
            name = fn.get('name') or tool_dict.get('name', '')
            desc = fn.get('description') or tool_dict.get('description', '')
            if name and desc:
                descriptions[name] = desc.split('\n')[0][:120]
        return descriptions

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
            descriptions = self._mcp_tool_descriptions_from_specs(mcp_tools)
            if hasattr(pm, 'mcp_tool_descriptions'):
                pm.mcp_tool_descriptions = descriptions
            if hasattr(pm, 'mcp_server_hints'):
                pm.mcp_server_hints = self._mcp_server_prompt_hints()
