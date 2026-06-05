"""Top-level :meth:`Orchestrator.step` and LLM-step helpers.

This module contains the long-running step dispatch (``astep``) plus
the two variants of the LLM step itself (sync wrapper and async
streaming variant). The bulk of the work is delegated to helpers in
the sibling modules; the functions here mostly orchestrate.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

from backend.core.constants import DEFAULT_AGENT_MAX_CONTEXT_LIMIT_ERRORS
from backend.core.errors import (
    AgentRuntimeError,
    ContextLimitError,
    FunctionCallConversionError,
    FunctionCallNotExistsError,
    FunctionCallValidationError,
    LLMMalformedActionError,
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
from backend.engine.orchestrator_helpers._orchestrator_actions import (
    _active_run_mode_for_state,
    _has_active_tasks_in_state,
    _queue_additional_actions,
    _sync_executor_llm,
)
from backend.engine.orchestrator_helpers._orchestrator_condensation import (
    _emit_compaction_status,
    _emit_compaction_status_if_needed,
    _handle_pending_action_from_condensation,
)
from backend.engine.orchestrator_helpers._orchestrator_helpers import (
    _graceful_shrink_large_cmd_outputs,
    _graceful_trim_old_error_observations,
    _safe_plain_text_count,
    _should_reset_plain_text_count,
)
from backend.engine.orchestrator_helpers._orchestrator_prompts import (
    _set_prompt_tier_from_recent_history,
)
from backend.engine.orchestrator_helpers._orchestrator_protocol import (
    _build_fallback_action,
)
from backend.engine.orchestrator_helpers._orchestrator_recovery import (
    _astep_handle_recoverable_tool_call_shape_error,
    _astep_handle_tool_execution_error,
)
from backend.inference.exceptions import LLMError

if TYPE_CHECKING:
    from backend.core.contracts.state import State
    from backend.engine.orchestrator import Orchestrator
    from backend.ledger.action import Action


def _generate_delimiter_token(orch: Orchestrator) -> str:
    import secrets

    token = f'GRINTA_{secrets.token_hex(3).upper()}'
    orch._current_delimiter_token = token
    return token


def _check_exit_command(orch: Orchestrator, state: State) -> Action | None:
    from backend.ledger.action import PlaybookFinishAction

    latest_user_message = state.get_last_user_message()
    if latest_user_message and latest_user_message.content.strip() == '/exit':
        return PlaybookFinishAction()
    return None


async def _astep_normal_path(orch: Orchestrator, state: State) -> Action:
    """Happy path: optional exit/deferred/pending handling then LLM step."""
    if exit_action := orch._check_exit_command(state):
        orch._reset_step_recovery_counters()
        return exit_action

    if not orch.pending_actions and orch.deferred_actions:
        orch._promote_deferred_actions()

    if pending := _consume_pending_action(orch):
        orch._reset_step_recovery_counters()
        return pending

    emitted_compaction_status = _emit_compaction_status_if_needed(orch, state)
    condensed = await orch.memory_manager.condense_history(state)
    if condensed.pending_action is not None and not emitted_compaction_status:
        _emit_compaction_status(orch)
    action = await orch._execute_llm_step_async(state, condensed)
    orch._reset_step_recovery_counters()
    return action


def _consume_pending_action(orch: Orchestrator) -> Action | None:
    from backend.engine.orchestrator_helpers._orchestrator_actions import (
        _consume_pending_action as impl,
    )

    return impl(orch)


async def _astep_handle_context_limit_error(
    orch: Orchestrator, state: State
) -> Action:
    """Condense/retry after ContextLimitError; may degrade or raise."""
    orch._consecutive_context_errors = (
        getattr(orch, '_consecutive_context_errors', 0) + 1
    )
    logger.warning(
        'ContextLimitError encountered (%d/%d). Attempting condensation + retry.',
        orch._consecutive_context_errors,
        DEFAULT_AGENT_MAX_CONTEXT_LIMIT_ERRORS,
    )

    if orch._consecutive_context_errors >= DEFAULT_AGENT_MAX_CONTEXT_LIMIT_ERRORS:
        degraded = await _attempt_graceful_context_degradation(orch, state)
        if degraded is not None:
            orch._consecutive_context_errors = 0
            return degraded
        raise AgentRuntimeError(
            'Circuit breaker: continuous ContextLimitErrors'
        ) from None

    try:
        emitted_compaction_status = _emit_compaction_status_if_needed(orch, state)
        condensed = await orch.memory_manager.condense_history(state)
        if condensed.pending_action is not None and not emitted_compaction_status:
            _emit_compaction_status(orch)
        action = await _execute_llm_step_async(orch, state, condensed)
        orch._consecutive_context_errors = 0
        return action
    except ContextLimitError:
        raise
    except Exception:
        logger.warning(
            'Auto-Healing retry failed after condensation. Falling back to think action.'
        )
        from backend.ledger.action import AgentThinkAction

        return AgentThinkAction(
            thought='I have reached the context limit. I must condense my memory before proceeding.',
        )


async def _attempt_graceful_context_degradation(
    orch: Orchestrator, state: State
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
        _emit_compaction_status(orch)
        condensed = await orch.memory_manager.condense_history(state)
        return await _execute_llm_step_async(orch, state, condensed)
    except ContextLimitError:
        logger.error('Graceful degradation insufficient — context still overflows')
        return None
    except Exception as exc:  # pragma: no cover — defensive
        logger.error(
            'Graceful degradation raised unexpectedly: %s', exc, exc_info=True
        )
        return None


async def astep(orch: Orchestrator, state: State) -> Action:
    """Async version of step() with hard circuit breaker for consecutive ContextLimitErrors."""
    from backend.core.errors import LLMNoActionError

    try:
        return await _astep_normal_path(orch, state)
    except ContextLimitError:
        return await _astep_handle_context_limit_error(orch, state)
    except ToolExecutionError as e:
        return _astep_handle_tool_execution_error(orch, e)
    except (
        FunctionCallValidationError,
        FunctionCallNotExistsError,
        CommonFunctionCallValidationError,
        CommonFunctionCallNotExistsError,
        FunctionCallConversionError,
        LLMMalformedActionError,
        ValueError,
    ) as e:
        return _astep_handle_recoverable_tool_call_shape_error(orch, e)
    except (ModelProviderError, LLMError, LLMNoActionError):
        orch._consecutive_context_errors = 0
        raise
    except Exception as e:
        orch._consecutive_context_errors = 0
        logger.error('Critical Failure in Orchestrator.astep: %s', e, exc_info=True)
        raise AgentRuntimeError(f'Critical agent failure: {str(e)}') from e


def _step_sync(orch: Orchestrator, state: State) -> Action:
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
    primitives and hid the misuse — it is now an explicit
    ``RuntimeError``. The only production caller (replay-mode
    ``ConfirmationService``) now uses :meth:`astep` directly via
    :meth:`ConfirmationService.aget_next_action`, so this branch is
    no longer reachable from the agent loop.
    """
    import threading

    from backend.utils.async_utils import get_main_event_loop

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    if current_loop is None:
        return asyncio.run(astep(orch, state))

    main_loop = get_main_event_loop()
    if (
        main_loop is not None
        and main_loop is not current_loop
        and main_loop.is_running()
    ):
        # Run on the registered main loop so cross-loop primitives stay
        # attached to the right loop.
        future = asyncio.run_coroutine_threadsafe(astep(orch, state), main_loop)
        return future.result()

    raise RuntimeError(
        'Engine.step() was called from inside a running event loop with no '
        'separate registered main loop available. Use ``await self.astep(state)`` '
        f'instead. caller_thread={threading.current_thread().name}'
    )


def _execute_llm_step(orch: Orchestrator, state: State, condensed: Any) -> Action:
    """Core logic to prepare messages, call LLM, and return the first action."""
    pending = _handle_pending_action_from_condensation(orch, state, condensed)
    if pending is not None:
        return pending

    _generate_delimiter_token(orch)

    initial_user_message = orch.memory_manager.get_initial_user_message(state.history)
    _set_prompt_tier_from_recent_history(orch, state)

    astep_id = (
        _prompt_role_debug.mark_astep_begin()
        if _prompt_role_debug.any_prompt_or_reasoning_debug()
        else 0
    )
    messages = orch.memory_manager.build_messages(
        condensed_history=condensed.events,
        initial_user_message=initial_user_message,
        llm_config=orch.llm.config,
    )
    _prompt_role_debug.log_prompt_roles_after_build_messages(
        messages,
        astep_id=astep_id,
        condensed_event_count=len(condensed.events),
        pending_condensation=condensed.pending_action is not None,
        history_event_count=len(state.history),
    )
    serialized_messages = message_serializer.serialize_messages(messages)
    params = orch.planner.build_llm_params(serialized_messages, state, orch.tools)
    _sync_executor_llm(orch)

    try:
        orch.executor._has_active_tasks = _has_active_tasks_in_state(state)  # type: ignore[attr-defined]
        orch.executor._active_run_mode = _active_run_mode_for_state(orch, state)  # type: ignore[attr-defined]
        orch.executor._state = state  # type: ignore[attr-defined]
        result = orch.executor.execute(params, orch.event_stream)
        orch._consecutive_invalid_protocol_outputs = 0
    except Exception:
        raise

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

    orch._last_llm_latency = result.execution_time

    actions = result.actions or []
    if not actions:
        return _build_fallback_action(orch, result)
    # Real tool call: clear the plain-text streak.
    current_count = _safe_plain_text_count(orch.executor)
    if (
        current_count > 0
        and _should_reset_plain_text_count(actions)
        and hasattr(orch.executor, '_consecutive_plain_text_blocks')
    ):
        orch.executor._consecutive_plain_text_blocks = 0  # type: ignore[attr-defined]
    _queue_additional_actions(orch, actions[1:])
    return actions[0]


async def _execute_llm_step_async(
    orch: Orchestrator, state: State, condensed: Any
) -> Action:
    """Async variant of _execute_llm_step using real LLM streaming."""
    pending = _handle_pending_action_from_condensation(orch, state, condensed)
    if pending is not None:
        return pending

    _generate_delimiter_token(orch)

    initial_user_message = orch.memory_manager.get_initial_user_message(state.history)
    _set_prompt_tier_from_recent_history(orch, state)

    astep_id = (
        _prompt_role_debug.mark_astep_begin()
        if _prompt_role_debug.any_prompt_or_reasoning_debug()
        else 0
    )

    def _prepare_params() -> dict[str, Any]:
        prepare_started = time.perf_counter()
        messages_started = time.perf_counter()
        messages = orch.memory_manager.build_messages(
            condensed_history=condensed.events,
            initial_user_message=initial_user_message,
            llm_config=orch.llm.config,
        )
        messages_elapsed = time.perf_counter() - messages_started
        _prompt_role_debug.log_prompt_roles_after_build_messages(
            messages,
            astep_id=astep_id,
            condensed_event_count=len(condensed.events),
            pending_condensation=condensed.pending_action is not None,
            history_event_count=len(state.history),
        )
        serialize_started = time.perf_counter()
        serialized_messages = message_serializer.serialize_messages(messages)
        serialize_elapsed = time.perf_counter() - serialize_started
        planner_started = time.perf_counter()
        params = orch.planner.build_llm_params(
            serialized_messages, state, orch.tools
        )
        logger.info(
            'Orchestrator._prepare_params built params '
            '(history_events=%d condensed_events=%d messages=%d '
            'pending_condensation=%s build_messages=%.3fs serialize=%.3fs '
            'planner=%.3fs elapsed=%.3fs)',
            len(state.history),
            len(condensed.events),
            len(messages),
            condensed.pending_action is not None,
            messages_elapsed,
            serialize_elapsed,
            time.perf_counter() - planner_started,
            time.perf_counter() - prepare_started,
        )
        return params

    params_started = time.perf_counter()
    params = await asyncio.to_thread(_prepare_params)
    logger.info(
        'Orchestrator._execute_llm_step_async prepared LLM params in %.3fs',
        time.perf_counter() - params_started,
    )
    _sync_executor_llm(orch)

    try:
        orch.executor._has_active_tasks = _has_active_tasks_in_state(state)  # type: ignore[attr-defined]
        orch.executor._active_run_mode = _active_run_mode_for_state(orch, state)  # type: ignore[attr-defined]
        orch.executor._state = state  # type: ignore[attr-defined]
        result = await orch.executor.async_execute(params, orch.event_stream)
        orch._consecutive_invalid_protocol_outputs = 0
    except Exception:
        raise

    # Ensure extra_data cleanup always runs, even if async_execute raises.
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

    orch._last_llm_latency = result.execution_time

    actions = result.actions or []
    if not actions:
        return _build_fallback_action(orch, result)
    current_count = _safe_plain_text_count(orch.executor)
    if (
        current_count > 0
        and _should_reset_plain_text_count(actions)
        and hasattr(orch.executor, '_consecutive_plain_text_blocks')
    ):
        orch.executor._consecutive_plain_text_blocks = 0  # type: ignore[attr-defined]
    _queue_additional_actions(orch, actions[1:])
    return actions[0]
