from __future__ import annotations

import asyncio
import os
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from backend.core.errors import ModelProviderError
from backend.core.logging.logger import app_logger as logger
from backend.engine.streaming_checkpoint import StreamingCheckpoint

if TYPE_CHECKING:
    from backend.inference.llm import LLM
    from backend.ledger.stream import EventStream

    from .contracts import NoopSafetyManager
    from .planner import OrchestratorPlanner

from backend.engine.executor_mixins._executor_lifecycle_mixin import (
    _ExecutorLifecycleMixin,
)
from backend.engine.executor_mixins._executor_response_mixin import (
    _ExecutorResponseMixin,
)
from backend.engine.executor_mixins._executor_streaming_mixin import (
    _ExecutorStreamingMixin,
)
from backend.engine.executor_mixins._executor_types import (  # noqa: F401
    ExecutionResult,
    _AsyncStreamingState,
)


class OrchestratorExecutor(
    _ExecutorStreamingMixin, _ExecutorLifecycleMixin, _ExecutorResponseMixin
):
    """Handles LLM invocation, streaming, and post-processing."""

    def __init__(
        self,
        llm: LLM,
        safety_manager: NoopSafetyManager,
        planner: OrchestratorPlanner,
        mcp_tools_provider: Callable[[], dict[str, Any]],
    ) -> None:
        self._llm = llm
        self._safety = safety_manager
        self._planner = planner
        self._mcp_tools_provider = mcp_tools_provider
        # Write-ahead checkpoint root for crash recovery. Session-specific
        # checkpoint files are created lazily from the active event stream.
        self._checkpoint_root = os.path.join(
            os.environ.get('APP_DATA_DIR', os.path.expanduser('~/.app')),
            'streaming_checkpoints',
        )
        self._checkpoint_cache: OrderedDict[str, StreamingCheckpoint] = OrderedDict()
        self._step_cancelled = False
        self._active_stream_task: asyncio.Task[Any] | None = None
        self._active_stream_iter: Any | None = None
        self._has_active_tasks: bool = False
        self._active_run_mode: str = ''
        # Per-session state reference and plain-text gate counter. Populated by
        # ``Orchestrator._execute_llm_step[_async]`` right before each step.
        self._state: Any | None = None
        self._consecutive_plain_text_blocks: int = 0

    def cancel_step(self) -> None:
        """Signal the current (or next) streaming step to abort early."""
        self._step_cancelled = True
        task = self._active_stream_task
        stream_iter = self._active_stream_iter
        if task is not None and not task.done():
            task.cancel()
        else:
            aclose = getattr(stream_iter, 'aclose', None)
            if callable(aclose):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    pass
                else:
                    loop.create_task(aclose())
        # Dropped stream handles must not suppress no-step-progress watchdogs.
        self._active_stream_task = None
        self._active_stream_iter = None

    def execute(
        self,
        params: dict,
        event_stream: EventStream | None,
    ) -> ExecutionResult:
        checkpoint = self._get_checkpoint(event_stream)
        start_time = time.time()
        error_message: str | None = None
        self._step_cancelled = False

        call_params = dict(params)
        call_params = self._apply_context_window_preflight(call_params)

        self._log_tool_names(call_params)

        ckpt_token = checkpoint.begin(
            call_params,
            anchor_event_id=self._checkpoint_anchor_event_id(event_stream),
        )

        try:
            call_params['stream'] = False
            response = self._llm.completion(**call_params)
        except Exception as exc:
            from backend.inference.exceptions import LLMError

            if isinstance(exc, LLMError):
                raise
            logger.error('Error during LLM completion: %s', exc)
            error_message = str(exc)
            raise ModelProviderError(
                'LLM completion failed',
                context={'error': error_message},
            ) from exc

        if response is None:
            raise ModelProviderError('LLM returned no response')

        self._emit_synthetic_streaming(response, event_stream)

        execution_time = time.time() - start_time
        actions = self._without_blank_agent_messages(
            self._response_to_actions(response)
        )
        if response is not None and event_stream is not None:
            from backend.engine.executor_response_helpers import (
                prepare_streamed_message_actions,
            )

            prepare_streamed_message_actions(
                actions,
                streamed_visible_text=self._extract_response_text(response),
            )
        checkpoint.commit(ckpt_token)
        return ExecutionResult(actions, response, execution_time, error_message)

    def _log_tool_names(self, call_params: dict) -> None:
        """Log tool names sent to LLM for session.jsonl correlation."""
        tool_list = call_params.get('tools', [])
        tool_names = (
            [t.get('function', {}).get('name', '?') for t in tool_list]
            if tool_list
            else []
        )
        active_mode = getattr(self, '_active_run_mode', 'N/A')
        logger.info(
            'executor.execute: mode=%r tools=%r',
            active_mode,
            tool_names,
            extra={'msg_type': 'EXECUTOR_TOOLS'},
        )

    def _emit_synthetic_streaming(
        self,
        response: Any,
        event_stream: EventStream | None,
    ) -> None:
        """Emit synthetic streaming events from a completed response."""
        try:
            if response is not None and event_stream is not None:
                response_text = self._extract_response_text(response)
                self._emit_streaming_actions(response_text, event_stream, response)
        except Exception as exc:
            logger.debug('Failed to emit streaming actions: %s', exc)

    async def async_execute(
        self,
        params: dict,
        event_stream: EventStream | None,
    ) -> ExecutionResult:
        """Execute LLM call with async interface natively streaming tokens."""
        checkpoint = self._get_checkpoint(event_stream)
        start_time = time.time()
        error_message: str | None = None
        self._step_cancelled = False

        call_params = self._prepare_call_params(params)
        self._log_debug_mode_tools(call_params)

        checkpoint.begin(
            call_params, anchor_event_id=self._checkpoint_anchor_event_id(event_stream)
        )

        response = None
        loop = asyncio.get_running_loop()
        state = _AsyncStreamingState()
        stream_iter: Any | None = None
        consume_task: asyncio.Task[Any] | None = None

        try:
            response = await self._execute_stream(
                call_params, event_stream, state, loop
            )
        except asyncio.CancelledError:
            self.cancel_step()
            checkpoint.discard()
            raise
        except Exception as exc:
            self._handle_stream_error(exc, error_message)
        finally:
            self._cleanup_stream_refs(consume_task, stream_iter)

        if response is None:
            raise ModelProviderError('LLM returned no response')

        execution_time = time.time() - start_time
        from backend.core.logging.session_event_logger import emit_session_event
        from backend.core.prompt_role_debug import current_astep_id

        latency_ms = int(execution_time * 1000)
        emit_session_event(
            'AGENT_STEP',
            {
                'astep_id': current_astep_id() or None,
                'latency_ms': latency_ms,
                'partial': True,
                'text': state.content_accumulate or '',
                'thinking': state.thinking_accumulate or '',
            },
        )
        logger.info(
            'OrchestratorExecutor.async_execute done in %.3fs',
            execution_time,
            extra={
                'msg_type': 'LLM_STEP_DONE',
                'astep_id': current_astep_id() or None,
                'latency_ms': latency_ms,
            },
        )
        actions = self._without_blank_agent_messages(
            self._response_to_actions(response)
        )
        from backend.engine.executor_response_helpers import (
            prepare_streamed_message_actions,
        )

        prepare_streamed_message_actions(
            actions,
            streamed_visible_text=state.content_accumulate,
            streamed_thinking_text=state.thinking_accumulate,
        )
        return ExecutionResult(actions, response, execution_time, error_message)

    def _prepare_call_params(self, params: dict) -> dict:
        call_params = dict(params)
        call_params.pop('stream', None)
        call_params['stream'] = True
        return self._apply_context_window_preflight(call_params)

    def _log_debug_mode_tools(self, call_params: dict) -> None:
        tool_list = call_params.get('tools', [])
        tool_names = (
            [t.get('function', {}).get('name', '?') for t in tool_list]
            if tool_list
            else []
        )
        logger.info(
            'async_execute: mode=%r tools=%r',
            getattr(self, '_active_run_mode', 'N/A'),
            tool_names,
            extra={'msg_type': 'EXECUTOR_TOOLS'},
        )

    async def _execute_stream(
        self,
        call_params: dict,
        event_stream: EventStream | None,
        state: _AsyncStreamingState,
        loop: Any,
    ) -> Any:
        logger.info('OrchestratorExecutor.async_execute: calling LLM.astream')
        stream_iter = self._llm.astream(**call_params)
        consume_task = loop.create_task(
            self._consume_async_stream(stream_iter, call_params, event_stream, state)
        )
        self._active_stream_iter = stream_iter
        self._active_stream_task = consume_task
        await consume_task
        if self._step_cancelled:
            raise asyncio.CancelledError()
        await self._flush_stream_paint_events(state, event_stream)
        tool_calls_list = self._finalize_stream_tool_calls(state)
        visible_accum = self._visible_stream_content(state.content_accumulate)
        self._emit_final_stream_event(
            event_stream,
            state.content_accumulate,
            visible_accum,
            tool_calls_list,
            thinking_accumulate=state.thinking_accumulate,
        )
        response = self._build_streaming_response(
            call_params,
            visible_accum,
            state.thinking_accumulate,
            tool_calls_list,
            state.streamed_usage,
            stream_response_id=self._ensure_stream_response_id(state),
        )
        self._record_streaming_metrics(response, time.time())
        return response

    def _handle_stream_error(self, exc: Exception, error_message: str | None) -> None:
        from backend.inference.exceptions import LLMError, RateLimitError

        if isinstance(exc, RateLimitError):
            logger.debug(
                'OrchestratorExecutor.async_execute: bubbling up RateLimitError natively'
            )
            raise
        if isinstance(exc, LLMError):
            raise
        error_message = str(exc)
        raise ModelProviderError(
            'LLM streaming failed', context={'error': error_message}
        ) from exc

    def _cleanup_stream_refs(self, consume_task: Any, stream_iter: Any) -> None:
        if consume_task is not None and self._active_stream_task is consume_task:
            self._active_stream_task = None
        if stream_iter is not None and self._active_stream_iter is stream_iter:
            self._active_stream_iter = None


# ---------------------------------------------------------------------------
# Backward-compat re-exports. Originals live in _executor_types.py.
# Tests and external callers access these as module-level attributes on
# `backend.engine.executor` (e.g., `executor_module.orchestrator_function_calling`).
# ExecutionResult and _AsyncStreamingState are imported at the top because the
# core method bodies use them at runtime; the rest are re-exported here.
# ---------------------------------------------------------------------------
from backend.engine.executor_mixins._executor_types import (  # noqa: E402
    _INLINE_CLOSE_THINK_RE,  # noqa: F401
    _INLINE_OPEN_THINK_RE,  # noqa: F401
    _MAX_CHECKPOINT_CACHE_SIZE,  # noqa: F401
    ModelResponse,  # noqa: F401
    _FunctionCallingProxy,  # noqa: F401
    orchestrator_function_calling,  # noqa: F401
)
