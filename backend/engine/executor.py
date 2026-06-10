from __future__ import annotations

import asyncio
import os
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from backend.core.errors import ModelProviderError
from backend.core.logger import app_logger as logger
from backend.engine import function_calling as _function_calling_module  # noqa: F401
from backend.engine.streaming_checkpoint import StreamingCheckpoint

if TYPE_CHECKING:
    from backend.inference.llm import LLM
    from backend.ledger.stream import EventStream

    from .planner import OrchestratorPlanner
    from .safety import OrchestratorSafetyManager

from backend.engine.executor_mixins._executor_lifecycle_mixin import (
    _ExecutorLifecycleMixin,
)
from backend.engine.executor_mixins._executor_response_mixin import _ExecutorResponseMixin
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
        safety_manager: OrchestratorSafetyManager,
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
        if task is not None and not task.done():
            task.cancel()
            return

        stream_iter = self._active_stream_iter
        aclose = getattr(stream_iter, 'aclose', None)
        if not callable(aclose):
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(aclose())

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

        # APP_DEBUG_MODE=1: log tools sent to LLM
        if os.environ.get('APP_DEBUG_MODE', '').strip().lower() in (
            '1',
            'true',
            'yes',
            'on',
        ):
            tool_list = call_params.get('tools', [])
            tool_names = (
                [t.get('function', {}).get('name', '?') for t in tool_list]
                if tool_list
                else []
            )
            active_mode = getattr(self, '_active_run_mode', 'N/A')
            logger.info(
                '[APP_DEBUG_MODE] executor.execute: mode=%r tools=%r',
                active_mode,
                tool_names,
            )

        # NOTE: Grinta's DirectLLMClient implementations intentionally expose
        # deterministic *non-streaming* completion for all providers. Native
        # streaming support varies widely across SDKs and tends to be the
        # source of flakiness. To keep UX responsive without relying on
        # provider-specific streaming, we always fetch a complete response
        # and then emit StreamingChunkAction events derived from the final text.
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

        # Emit synthetic streaming events from the final response text
        # (post-hoc streaming). This is deterministic and provider-agnostic.
        try:
            if response is not None and event_stream is not None:
                response_text = self._extract_response_text(response)
                self._emit_streaming_actions(response_text, event_stream, response)
        except Exception as exc:  # pragma: no cover - streaming is best-effort
            logger.debug('Failed to emit streaming actions: %s', exc)

        execution_time = time.time() - start_time
        actions = self._without_blank_agent_messages(
            self._response_to_actions(response)
        )
        # Commit only after the model response has been converted into durable
        # actions. If conversion fails, the WAL remains as an explicit recovery
        # fence instead of making an incomplete turn look successful.
        checkpoint.commit(ckpt_token)
        return ExecutionResult(actions, response, execution_time, error_message)

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

        ckpt_token = checkpoint.begin(call_params, anchor_event_id=self._checkpoint_anchor_event_id(event_stream))

        response = None
        loop = asyncio.get_running_loop()
        state = _AsyncStreamingState()
        stream_iter: Any | None = None
        consume_task: asyncio.Task[Any] | None = None

        try:
            response = await self._execute_stream(call_params, event_stream, state, loop)
        except asyncio.CancelledError:
            self.cancel_step()
            checkpoint.discard()
            raise
        except Exception as exc:
            response = self._handle_stream_error(exc, error_message)
        finally:
            self._cleanup_stream_refs(consume_task, stream_iter)

        if response is None:
            raise ModelProviderError('LLM returned no response')

        logger.info('OrchestratorExecutor.async_execute done in %.3fs', time.time() - start_time)
        execution_time = time.time() - start_time
        actions = self._without_blank_agent_messages(self._response_to_actions(response))
        return ExecutionResult(actions, response, execution_time, error_message)

    def _prepare_call_params(self, params: dict) -> dict:
        call_params = dict(params)
        call_params.pop('stream', None)
        call_params['stream'] = True
        return self._apply_context_window_preflight(call_params)

    def _log_debug_mode_tools(self, call_params: dict) -> None:
        if os.environ.get('APP_DEBUG_MODE', '').strip().lower() not in ('1', 'true', 'yes', 'on'):
            return
        tool_list = call_params.get('tools', [])
        tool_names = [t.get('function', {}).get('name', '?') for t in tool_list] if tool_list else []
        logger.info('[APP_DEBUG_MODE] async_execute: mode=%r tools=%r', getattr(self, '_active_run_mode', 'N/A'), tool_names)

    async def _execute_stream(self, call_params: dict, event_stream: EventStream | None, state: _AsyncStreamingState, loop: Any) -> Any:
        logger.info('OrchestratorExecutor.async_execute: calling LLM.astream')
        stream_iter = self._llm.astream(**call_params)
        consume_task = loop.create_task(self._consume_async_stream(stream_iter, call_params, event_stream, state))
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
        response = self._build_streaming_response(call_params, visible_accum, state.thinking_accumulate, tool_calls_list, state.streamed_usage)
        self._record_streaming_metrics(response, time.time())
        return response

    def _handle_stream_error(self, exc: Exception, error_message: str | None) -> None:
        from backend.inference.exceptions import LLMError, RateLimitError
        if isinstance(exc, RateLimitError):
            logger.debug('OrchestratorExecutor.async_execute: bubbling up RateLimitError natively')
            raise
        if isinstance(exc, LLMError):
            raise
        error_message = str(exc)
        raise ModelProviderError('LLM streaming failed', context={'error': error_message}) from exc

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
