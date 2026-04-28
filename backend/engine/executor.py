from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Protocol,
    runtime_checkable,
)

from backend.core.constants import (
    DEFAULT_AGENT_STREAMING_CHECKPOINT_DISCARD_STALE_ON_RECOVERY,
    DEFAULT_AGENT_STREAMING_CHECKPOINT_MAX_AGE_SECONDS,
)
from backend.core.errors import ModelProviderError
from backend.core.logger import app_logger as logger
from backend.engine.executor_response_helpers import (
    build_recoverable_tool_call_error_action as _build_recoverable_tool_call_error_action_impl,
    content_to_str as _content_to_str_impl,
    extract_last_user_text as _extract_last_user_text_impl,
    extract_recent_user_text as _extract_recent_user_text_impl,
    extract_response_text as _extract_response_text_impl,
    is_recoverable_tool_call_error as _is_recoverable_tool_call_error_impl,
    without_blank_agent_messages as _without_blank_agent_messages_impl,
)
from backend.engine import function_calling as _function_calling_module  # noqa: F401
from backend.engine.streaming_checkpoint import (
    StreamingCheckpoint,
)
from backend.ledger.persistence import EventPersistence

if TYPE_CHECKING:
    from backend.inference.llm import LLM
    from backend.ledger.action import Action
    from backend.ledger.stream import EventStream

    from .planner import OrchestratorPlanner
    from .safety import OrchestratorSafetyManager


# ---------------------------------------------------------------------------
# Typed model-response protocol
# ---------------------------------------------------------------------------
@runtime_checkable
class ModelResponse(Protocol):
    """Structural type for LLM completion responses (OpenAI-compatible)."""

    choices: list
    id: str
    tool_calls: list[Any] | None  # OpenAI-style function/tool calls (optional)


# Compiled once at import time for inline <think>/<redacted_thinking> tag splitting
# in the streaming delta handler.  DeepSeek R1, QwQ, Ollama reasoning models, and
# early OpenAI o-series all embed chain-of-thought in delta.content using one of
# these two tag conventions.
_INLINE_OPEN_THINK_RE = re.compile(r'<(redacted_thinking|think)>', re.IGNORECASE)
_INLINE_CLOSE_THINK_RE = re.compile(r'</(redacted_thinking|think)>', re.IGNORECASE)


@dataclass(slots=True)
class ExecutionResult:
    """Container for executor outcomes."""

    actions: list[Action] = field(default_factory=list)
    response: ModelResponse | Any | None = None
    execution_time: float = 0.0
    error: str | None = None


@dataclass(slots=True)
class _AsyncStreamingState:
    content_accumulate: str = ''
    thinking_accumulate: str = ''
    tool_calls_dict: dict[int, dict[str, Any]] = field(default_factory=dict)
    streamed_usage: dict[str, int] | None = None
    in_inline_think_block: bool = False


class _FunctionCallingProxy:
    """Proxy that forwards attribute access to the live function_calling module.

    Keeps track of attribute overrides (via monkeypatch) so they persist even if
    the underlying module is reloaded during other tests.
    """

    def __init__(self, module_name: str) -> None:
        self.module_name = module_name
        self._overrides: dict[str, Any] = {}

    @property
    def module(self):
        return sys.modules[self.module_name]

    def __getattr__(self, item):
        if item in self._overrides:
            return self._overrides[item]
        return getattr(self.module, item)

    def __setattr__(self, key, value):
        if key in {'module_name', '_overrides'}:
            object.__setattr__(self, key, value)
        else:
            self._overrides[key] = value
            setattr(self.module, key, value)


orchestrator_function_calling = _FunctionCallingProxy('backend.engine.function_calling')


class OrchestratorExecutor:
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
        self._checkpoint_cache: dict[str, StreamingCheckpoint] = {}
        self._recovery_blocked_reasons: dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def execute(
        self,
        params: dict,
        event_stream: EventStream | None,
    ) -> ExecutionResult:
        checkpoint = self._get_checkpoint(event_stream)
        self._raise_if_recovery_blocked(event_stream)
        start_time = time.time()
        error_message: str | None = None
        response: ModelResponse | None = None

        # Write-ahead checkpoint before invoking the model.
        #
        # NOTE: App's DirectLLMClient implementations intentionally expose
        # deterministic *non-streaming* completion for all providers. Native
        # streaming support varies widely across SDKs and tends to be the
        # source of flakiness. To keep UX responsive without relying on
        # provider-specific streaming, we always fetch a complete response
        # and then emit StreamingChunkAction events derived from the final text.
        ckpt_token = checkpoint.begin(
            params,
            anchor_event_id=self._checkpoint_anchor_event_id(event_stream),
        )

        call_params = dict(params)

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

        # Commit checkpoint after a successful completion call.
        checkpoint.commit(ckpt_token)

        execution_time = time.time() - start_time
        actions = self._without_blank_agent_messages(
            self._response_to_actions(response)
        )
        return ExecutionResult(actions, response, execution_time, error_message)

    # ------------------------------------------------------------------ #
    # Async streaming execution
    # ------------------------------------------------------------------ #
    @staticmethod
    def _timeout_from_env(
        env_var: str,
        default: float,
        *,
        allow_disable: bool = False,
    ) -> float | None:
        raw = os.getenv(env_var, str(default)).strip()
        try:
            parsed = float(raw)
        except (TypeError, ValueError):
            return default
        if parsed > 0:
            return parsed
        return None if allow_disable else default

    @staticmethod
    def _llm_model_name(llm: Any) -> str | None:
        return getattr(getattr(llm, 'config', None), 'model', None)

    @staticmethod
    def _merge_stream_fragment(existing: str, incoming: str) -> str:
        r"""Merge streamed fragments with safe append-only defaults."""
        if not incoming:
            return existing
        if not existing:
            return incoming
        if incoming == existing:
            return existing
        if len(incoming) > len(existing) and incoming.startswith(existing):
            return incoming
        if (
            len(existing) >= 2
            and existing[-1:] in ('}', ']')
            and len(incoming) > len(existing)
            and incoming.startswith(existing[:-1])
        ):
            return incoming
        return existing + incoming

    async def _emit_stream_text_piece(
        self,
        state: _AsyncStreamingState,
        text_piece: str,
        event_stream: EventStream | None,
    ) -> None:
        if not text_piece:
            return

        from backend.cli.tool_call_display import redact_streamed_tool_call_markers
        from backend.ledger.action.message import StreamingChunkAction
        from backend.ledger.event import EventSource

        state.content_accumulate = self._merge_stream_fragment(
            state.content_accumulate,
            text_piece,
        )
        if event_stream:
            display_acc = redact_streamed_tool_call_markers(state.content_accumulate)
            ev = StreamingChunkAction(
                chunk=text_piece,
                accumulated=display_acc,
                is_final=False,
                thinking_accumulated=state.thinking_accumulate,
            )
            ev.source = EventSource.AGENT
            event_stream.add_event(ev, EventSource.AGENT)
            await asyncio.sleep(0)

    async def _emit_stream_thinking_piece(
        self,
        state: _AsyncStreamingState,
        text_piece: str,
        event_stream: EventStream | None,
    ) -> None:
        if not text_piece:
            return

        from backend.cli.tool_call_display import redact_streamed_tool_call_markers
        from backend.ledger.action.message import StreamingChunkAction
        from backend.ledger.event import EventSource

        state.thinking_accumulate = self._merge_stream_fragment(
            state.thinking_accumulate,
            text_piece,
        )
        if event_stream:
            ev = StreamingChunkAction(
                chunk='',
                accumulated=redact_streamed_tool_call_markers(
                    state.content_accumulate
                ),
                is_final=False,
                thinking_chunk=text_piece,
                thinking_accumulated=state.thinking_accumulate,
            )
            ev.source = EventSource.AGENT
            event_stream.add_event(ev, EventSource.AGENT)
            await asyncio.sleep(0)

    @staticmethod
    def _extract_delta_text(delta: dict[str, Any]) -> str:
        delta_content = delta.get('content')
        if isinstance(delta_content, str):
            return delta_content
        if not isinstance(delta_content, list):
            return ''

        parts: list[str] = []
        for part in delta_content:
            if isinstance(part, str):
                parts.append(part)
                continue
            if not isinstance(part, dict):
                continue
            maybe_text = part.get('text')
            if isinstance(maybe_text, str):
                parts.append(maybe_text)
        return ''.join(parts)

    @staticmethod
    def _extract_delta_reasoning(delta: dict[str, Any]) -> str:
        for alt_key in ('reasoning_content', 'reasoning'):
            alt_val = delta.get(alt_key)
            if isinstance(alt_val, str) and alt_val:
                return alt_val
        return ''

    async def _process_stream_text_delta(
        self,
        delta: dict[str, Any],
        state: _AsyncStreamingState,
        event_stream: EventStream | None,
    ) -> None:
        reasoning_chunk = self._extract_delta_reasoning(delta)
        if reasoning_chunk:
            await self._emit_stream_thinking_piece(
                state,
                reasoning_chunk,
                event_stream,
            )

        remaining = self._extract_delta_text(delta)
        while remaining:
            if state.in_inline_think_block:
                close_match = _INLINE_CLOSE_THINK_RE.search(remaining)
                if close_match:
                    await self._emit_stream_thinking_piece(
                        state,
                        remaining[: close_match.start()],
                        event_stream,
                    )
                    state.in_inline_think_block = False
                    remaining = remaining[close_match.end() :]
                    continue
                await self._emit_stream_thinking_piece(state, remaining, event_stream)
                return

            open_match = _INLINE_OPEN_THINK_RE.search(remaining)
            if open_match:
                before = remaining[: open_match.start()]
                if before:
                    await self._emit_stream_text_piece(state, before, event_stream)
                state.in_inline_think_block = True
                remaining = remaining[open_match.end() :]
                continue
            await self._emit_stream_text_piece(state, remaining, event_stream)
            return

    async def _process_stream_tool_calls(
        self,
        delta: dict[str, Any],
        state: _AsyncStreamingState,
        event_stream: EventStream | None,
    ) -> None:
        from backend.ledger.action.message import StreamingChunkAction
        from backend.ledger.event import EventSource

        tool_call_chunks = delta.get('tool_calls')
        if not tool_call_chunks:
            return

        for tool_call_chunk in tool_call_chunks:
            idx = tool_call_chunk['index']
            if idx not in state.tool_calls_dict:
                state.tool_calls_dict[idx] = {
                    'id': tool_call_chunk.get('id'),
                    'type': 'function',
                    'function': {'name': '', 'arguments': ''},
                }

            function = tool_call_chunk.get('function', {})
            raw_name = function.get('name') if isinstance(function, dict) else None
            if isinstance(raw_name, str) and raw_name:
                current_name = state.tool_calls_dict[idx]['function']['name']
                state.tool_calls_dict[idx]['function']['name'] = (
                    self._merge_stream_fragment(current_name, raw_name)
                )

            raw_args = function.get('arguments') if isinstance(function, dict) else None
            if not isinstance(raw_args, str) or not raw_args:
                continue

            current_args = state.tool_calls_dict[idx]['function']['arguments']
            state.tool_calls_dict[idx]['function']['arguments'] = (
                self._merge_stream_fragment(current_args, raw_args)
            )
            if event_stream:
                logger.debug(
                    'DEBUG: Emitting tool argument chunk of len %d',
                    len(raw_args),
                )
                ev = StreamingChunkAction(
                    chunk=raw_args,
                    accumulated=state.tool_calls_dict[idx]['function']['arguments'],
                    is_final=False,
                    is_tool_call=True,
                    tool_call_name=state.tool_calls_dict[idx]['function']['name'],
                )
                ev.source = EventSource.AGENT
                event_stream.add_event(ev, EventSource.AGENT)
                await asyncio.sleep(0)

    async def _process_stream_delta(
        self,
        delta: dict[str, Any],
        state: _AsyncStreamingState,
        event_stream: EventStream | None,
    ) -> None:
        await self._process_stream_text_delta(delta, state, event_stream)
        await self._process_stream_tool_calls(delta, state, event_stream)

    @staticmethod
    def _extract_fallback_message(fallback: Any) -> Any | None:
        choices = getattr(fallback, 'choices', None)
        if not isinstance(choices, list) or not choices:
            return None
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            return first_choice.get('message')
        return getattr(first_choice, 'message', None)

    def _extract_fallback_content(self, fallback: Any, fallback_message: Any | None) -> str:
        fallback_content_raw = getattr(fallback, 'content', None)
        fallback_content = (
            self._content_to_str(fallback_content_raw)
            if fallback_content_raw is not None
            else ''
        )
        if fallback_content or fallback_message is None:
            return fallback_content
        if isinstance(fallback_message, dict):
            return self._content_to_str(fallback_message.get('content'))
        return self._content_to_str(getattr(fallback_message, 'content', None))

    @staticmethod
    def _extract_fallback_tool_calls(
        fallback: Any,
        fallback_message: Any | None,
    ) -> list[dict[str, Any]]:
        fallback_tool_calls = getattr(fallback, 'tool_calls', None)
        if not isinstance(fallback_tool_calls, list) and fallback_message is not None:
            if isinstance(fallback_message, dict):
                maybe_tool_calls = fallback_message.get('tool_calls')
            else:
                maybe_tool_calls = getattr(fallback_message, 'tool_calls', None)
            if isinstance(maybe_tool_calls, list):
                fallback_tool_calls = maybe_tool_calls
        return fallback_tool_calls if isinstance(fallback_tool_calls, list) else []

    async def _apply_fallback_completion(
        self,
        fallback: Any,
        state: _AsyncStreamingState,
        event_stream: EventStream | None,
    ) -> None:
        fallback_message = self._extract_fallback_message(fallback)
        fallback_content = self._extract_fallback_content(fallback, fallback_message)
        if fallback_content:
            await self._emit_stream_text_piece(
                state,
                fallback_content,
                event_stream,
            )

        for index, tool_call in enumerate(
            self._extract_fallback_tool_calls(fallback, fallback_message)
        ):
            if not isinstance(tool_call, dict):
                continue
            function = tool_call.get('function') or {}
            name = function.get('name') if isinstance(function, dict) else ''
            arguments = function.get('arguments') if isinstance(function, dict) else ''
            state.tool_calls_dict[index] = {
                'id': tool_call.get('id'),
                'type': tool_call.get('type', 'function'),
                'function': {
                    'name': name if isinstance(name, str) else '',
                    'arguments': arguments if isinstance(arguments, str) else '',
                },
            }

    async def _handle_first_chunk_timeout_fallback(
        self,
        call_params: dict[str, Any],
        event_stream: EventStream | None,
        state: _AsyncStreamingState,
        first_chunk_timeout: float,
    ) -> None:
        from backend.inference.exceptions import Timeout as LLMTimeout

        logger.warning(
            'LLM stream produced no first chunk after %.1fs; falling back to non-stream completion',
            first_chunk_timeout,
        )

        if event_stream:
            from backend.ledger.event import EventSource
            from backend.ledger.observation import StatusObservation

            status_ev = StatusObservation(
                content='Stream timed out — retrying without streaming…'
            )
            event_stream.add_event(status_ev, EventSource.ENVIRONMENT)

        fallback_params = dict(call_params)
        fallback_params['stream'] = False
        fallback_timeout = self._timeout_from_env(
            'APP_LLM_FALLBACK_TIMEOUT_SECONDS',
            60.0,
        ) or 60.0
        logger.warning(
            'Attempting non-streaming fallback with %.1fs timeout',
            fallback_timeout,
        )

        try:
            fallback = await asyncio.wait_for(
                self._llm.acompletion(**fallback_params),
                timeout=fallback_timeout,
            )
        except asyncio.TimeoutError:
            logger.error(
                'Fallback non-streaming completion timed out after %.1fs',
                fallback_timeout,
            )
            raise LLMTimeout(
                f'Fallback completion timed out after {fallback_timeout} seconds',
                model=self._llm_model_name(self._llm),
            ) from None

        await self._apply_fallback_completion(fallback, state, event_stream)

    async def _consume_first_stream_chunk(
        self,
        stream_aiter: Any,
        call_params: dict[str, Any],
        event_stream: EventStream | None,
        state: _AsyncStreamingState,
        first_chunk_timeout: float | None,
    ) -> bool:
        if first_chunk_timeout is None:
            return True

        try:
            first_chunk = await asyncio.wait_for(
                stream_aiter.__anext__(),
                timeout=first_chunk_timeout,
            )
        except StopAsyncIteration:
            return False
        except asyncio.TimeoutError:
            await self._handle_first_chunk_timeout_fallback(
                call_params,
                event_stream,
                state,
                first_chunk_timeout,
            )
            return False

        choices = first_chunk.get('choices', [])
        if choices:
            await self._process_stream_delta(
                choices[0].get('delta', {}),
                state,
                event_stream,
            )
            return True

        first_chunk_usage = first_chunk.get('usage')
        if isinstance(first_chunk_usage, dict):
            state.streamed_usage = first_chunk_usage
        return True

    async def _consume_remaining_stream_chunks(
        self,
        stream_aiter: Any,
        event_stream: EventStream | None,
        state: _AsyncStreamingState,
        stream_chunk_timeout: float,
    ) -> None:
        from backend.inference.exceptions import Timeout as LLMTimeout

        while True:
            try:
                chunk = await asyncio.wait_for(
                    anext(stream_aiter),
                    timeout=stream_chunk_timeout,
                )
            except StopAsyncIteration:
                return
            except asyncio.TimeoutError:
                logger.warning(
                    'LLM stream chunk timed out mid-generation after %.1fs. Streaming stalled.',
                    stream_chunk_timeout,
                )
                raise LLMTimeout(
                    f'LLM stream chunk timed out mid-generation after {stream_chunk_timeout} seconds',
                    model=self._llm_model_name(self._llm),
                ) from None

            choices = chunk.get('choices', [])
            if not choices:
                chunk_usage = chunk.get('usage')
                if isinstance(chunk_usage, dict):
                    state.streamed_usage = chunk_usage
                continue
            await self._process_stream_delta(
                choices[0].get('delta', {}),
                state,
                event_stream,
            )

    async def _consume_async_stream(
        self,
        stream_iter: Any,
        call_params: dict[str, Any],
        event_stream: EventStream | None,
        state: _AsyncStreamingState,
    ) -> None:
        stream_aiter = stream_iter.__aiter__()
        first_chunk_timeout = self._timeout_from_env(
            'APP_LLM_FIRST_CHUNK_TIMEOUT_SECONDS',
            45.0,
            allow_disable=True,
        )
        should_continue = await self._consume_first_stream_chunk(
            stream_aiter,
            call_params,
            event_stream,
            state,
            first_chunk_timeout,
        )
        if not should_continue:
            return

        stream_chunk_timeout = self._timeout_from_env(
            'APP_LLM_STREAM_CHUNK_TIMEOUT_SECONDS',
            90.0,
        ) or 90.0
        await self._consume_remaining_stream_chunks(
            stream_aiter,
            event_stream,
            state,
            stream_chunk_timeout,
        )

    def _finalize_stream_tool_calls(
        self,
        state: _AsyncStreamingState,
    ) -> list[dict[str, Any]] | None:
        if not state.tool_calls_dict and state.content_accumulate:
            from backend.cli.tool_call_display import (
                extract_tool_calls_from_text_markers,
            )

            text_tool_calls = extract_tool_calls_from_text_markers(
                state.content_accumulate
            )
            if text_tool_calls:
                logger.info(
                    'Extracted %d text-format tool call(s) from streaming content; treating as structured tool calls.',
                    len(text_tool_calls),
                )
                for index, tool_call in enumerate(text_tool_calls):
                    state.tool_calls_dict[index] = tool_call

        tool_calls_list = [
            state.tool_calls_dict[idx] for idx in sorted(state.tool_calls_dict.keys())
        ]
        return tool_calls_list or None

    @staticmethod
    def _visible_stream_content(content_accumulate: str) -> str:
        from backend.cli.tool_call_display import redact_streamed_tool_call_markers

        return redact_streamed_tool_call_markers(content_accumulate).strip()

    def _emit_final_stream_event(
        self,
        event_stream: EventStream | None,
        content_accumulate: str,
        visible_accum: str,
        tool_calls_list: list[dict[str, Any]] | None,
    ) -> None:
        if not event_stream or not content_accumulate:
            return

        from backend.ledger.action.message import StreamingChunkAction
        from backend.ledger.event import EventSource

        draft_reply_accum = '' if tool_calls_list else visible_accum
        ev = StreamingChunkAction(
            chunk='',
            accumulated=draft_reply_accum,
            is_final=True,
        )
        ev.source = EventSource.AGENT
        event_stream.add_event(ev, EventSource.AGENT)

    def _resolve_stream_usage(
        self,
        call_params: dict[str, Any],
        visible_accum: str,
        tool_calls_list: list[dict[str, Any]] | None,
        streamed_usage: dict[str, int] | None,
    ) -> dict[str, Any]:
        if streamed_usage:
            return streamed_usage

        from backend.inference.llm_utils import get_token_count

        estimated_prompt = get_token_count(call_params.get('messages') or [])
        estimated_completion = get_token_count(
            [{'role': 'assistant', 'content': visible_accum or ''}]
        )
        if tool_calls_list:
            tool_payload: list[dict[str, Any]] = []
            for tool_call in tool_calls_list:
                function = tool_call.get('function', {})
                tool_payload.append(
                    {
                        'role': 'assistant',
                        'content': '',
                        'tool_calls': [
                            {
                                'function': {
                                    'name': function.get('name', ''),
                                    'arguments': function.get('arguments', ''),
                                }
                            }
                        ],
                    }
                )
            estimated_completion += get_token_count(tool_payload)
        return {
            'prompt_tokens': estimated_prompt,
            'completion_tokens': estimated_completion,
            'total_tokens': estimated_prompt + estimated_completion,
            'is_estimated': True,
        }

    def _build_streaming_response(
        self,
        call_params: dict[str, Any],
        visible_accum: str,
        tool_calls_list: list[dict[str, Any]] | None,
        streamed_usage: dict[str, int] | None,
    ) -> Any:
        from backend.inference.direct_clients import LLMResponse

        model_name = self._llm_model_name(self._llm) or 'unknown'
        resolved_usage = self._resolve_stream_usage(
            call_params,
            visible_accum,
            tool_calls_list,
            streamed_usage,
        )
        return LLMResponse(
            content=visible_accum,
            model=model_name,
            usage=resolved_usage,
            response_id='',
            finish_reason='stop',
            tool_calls=tool_calls_list,
        )

    def _record_streaming_metrics(self, response: Any, start_time: float) -> None:
        prompt_tokens = int(response.usage.get('prompt_tokens', 0) or 0)
        completion_tokens = int(response.usage.get('completion_tokens', 0) or 0)
        if prompt_tokens <= 0 and completion_tokens <= 0:
            return
        try:
            stream_latency = time.time() - start_time
            self._llm._record_response_metrics(response, stream_latency)  # type: ignore[attr-defined]
        except Exception as metrics_error:
            logger.debug('Failed to record streaming metrics: %s', metrics_error)

    async def async_execute(
        self,
        params: dict,
        event_stream: EventStream | None,
    ) -> ExecutionResult:
        """Execute LLM call with async interface natively streaming tokens."""
        checkpoint = self._get_checkpoint(event_stream)
        self._raise_if_recovery_blocked(event_stream)

        start_time = time.time()
        error_message: str | None = None

        call_params = dict(params)
        call_params.pop('stream', None)
        call_params['stream'] = True

        ckpt_token = checkpoint.begin(
            call_params,
            anchor_event_id=self._checkpoint_anchor_event_id(event_stream),
        )

        from backend.core.llm_step_timeout import llm_step_timeout_seconds_from_env

        timeout_seconds = llm_step_timeout_seconds_from_env()

        response = None
        loop = asyncio.get_running_loop()
        state = _AsyncStreamingState()

        try:
            logger.info('OrchestratorExecutor.async_execute: calling LLM.astream')
            stream_iter = self._llm.astream(**call_params)
            consume_task = loop.create_task(
                self._consume_async_stream(
                    stream_iter,
                    call_params,
                    event_stream,
                    state,
                )
            )
            if timeout_seconds is None:
                await consume_task
            else:
                await asyncio.wait_for(consume_task, timeout=timeout_seconds)
            tool_calls_list = self._finalize_stream_tool_calls(state)
            visible_accum = self._visible_stream_content(state.content_accumulate)
            self._emit_final_stream_event(
                event_stream,
                state.content_accumulate,
                visible_accum,
                tool_calls_list,
            )
            response = self._build_streaming_response(
                call_params,
                visible_accum,
                tool_calls_list,
                state.streamed_usage,
            )
            self._record_streaming_metrics(response, start_time)

        except asyncio.TimeoutError as exc:
            from backend.inference.exceptions import Timeout as LLMTimeout

            model_name = getattr(getattr(self._llm, 'config', None), 'model', None)
            logger.error('LLM timeout %s', type(exc).__name__)
            cap = timeout_seconds if timeout_seconds is not None else 0.0
            raise LLMTimeout(
                f'LLM streaming call timed out after {cap} seconds (Full Step Timeout)',
                model=model_name,
            ) from exc
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            from backend.inference.exceptions import LLMError

            if isinstance(exc, LLMError):
                raise
            error_message = str(exc)
            raise ModelProviderError(
                'LLM streaming failed', context={'error': error_message}
            ) from exc

        if response is None:
            raise ModelProviderError('LLM returned no response')

        logger.info(
            'OrchestratorExecutor.async_execute done in %.3fs', time.time() - start_time
        )

        checkpoint.commit(ckpt_token)

        execution_time = time.time() - start_time
        actions = self._without_blank_agent_messages(
            self._response_to_actions(response)
        )
        return ExecutionResult(actions, response, execution_time, error_message)

    def _raise_if_recovery_blocked(self, event_stream: EventStream | None) -> None:
        session_key = self._checkpoint_session_key(event_stream)
        if reason := self._recovery_blocked_reasons.pop(session_key, None):
            raise ModelProviderError(
                'Streaming checkpoint recovery requires manual confirmation before continuing.',
                context={'recovery_reason': reason},
            )
        return

    def _get_checkpoint(self, event_stream: EventStream | None) -> StreamingCheckpoint:
        session_key = self._checkpoint_session_key(event_stream)
        checkpoint = self._checkpoint_cache.get(session_key)
        if checkpoint is not None:
            return checkpoint

        if event_stream is None:
            checkpoint_dir = self._checkpoint_root
        else:
            checkpoint_dir = os.path.join(
                self._checkpoint_root,
                self._sanitize_checkpoint_key(session_key),
            )

        max_checkpoint_age_sec, discard_stale_on_recovery = (
            self._checkpoint_recovery_policy()
        )

        checkpoint = StreamingCheckpoint(
            checkpoint_dir,
            max_checkpoint_age_sec=max_checkpoint_age_sec,
            discard_stale_on_recovery=discard_stale_on_recovery,
        )
        inspection = checkpoint.inspect_recovery()
        if inspection.status in {'blocked_uncommitted', 'blocked_stale'}:
            if self._checkpoint_is_superseded_by_persisted_control_event(
                event_stream,
                inspection.record,
            ):
                checkpoint.discard()
                logger.warning(
                    'Discarded stale streaming checkpoint for %s because a newer persisted control event proves the session advanced',
                    session_key,
                )
            else:
                self._recovery_blocked_reasons[session_key] = inspection.reason
                checkpoint.discard()
                logger.error(
                    'Discarded uncommitted streaming checkpoint for %s and blocked next LLM call: %s',
                    session_key,
                    inspection.reason,
                )
        self._checkpoint_cache[session_key] = checkpoint
        return checkpoint

    def _checkpoint_recovery_policy(self) -> tuple[float, bool]:
        config = getattr(self._planner, '_config', None)

        max_checkpoint_age_sec = DEFAULT_AGENT_STREAMING_CHECKPOINT_MAX_AGE_SECONDS
        configured_max_age = getattr(
            config,
            'streaming_checkpoint_max_age_seconds',
            max_checkpoint_age_sec,
        )
        if (
            isinstance(configured_max_age, int | float)
            and not isinstance(configured_max_age, bool)
            and configured_max_age > 0
        ):
            max_checkpoint_age_sec = float(configured_max_age)

        discard_stale_on_recovery = (
            DEFAULT_AGENT_STREAMING_CHECKPOINT_DISCARD_STALE_ON_RECOVERY
        )
        configured_discard_stale = getattr(
            config,
            'streaming_checkpoint_discard_stale_on_recovery',
            discard_stale_on_recovery,
        )
        if isinstance(configured_discard_stale, bool):
            discard_stale_on_recovery = configured_discard_stale

        return max_checkpoint_age_sec, discard_stale_on_recovery

    @staticmethod
    def _checkpoint_anchor_event_id(event_stream: EventStream | None) -> int | None:
        if event_stream is None:
            return None
        try:
            latest = event_stream.get_latest_event_id()
        except Exception:
            return None
        return latest if isinstance(latest, int) and latest >= 0 else None

    def _checkpoint_is_superseded_by_persisted_control_event(
        self,
        event_stream: EventStream | None,
        record: Any,
    ) -> bool:
        if event_stream is None or record is None:
            return False
        anchor_event_id = getattr(record, 'anchor_event_id', None)
        if not isinstance(anchor_event_id, int) or anchor_event_id < 0:
            return False
        latest_critical_id = self._latest_persisted_critical_event_id(event_stream)
        return latest_critical_id is not None and latest_critical_id > anchor_event_id

    @staticmethod
    def _latest_persisted_critical_event_id(
        event_stream: EventStream,
    ) -> int | None:
        try:
            for event in event_stream.search_events(reverse=True):
                if not EventPersistence.is_critical_event(event):
                    continue
                event_id = getattr(event, 'id', None)
                if isinstance(event_id, int) and event_id >= 0:
                    return event_id
        except Exception as exc:
            logger.debug(
                'Failed to inspect persisted critical events for %s: %s',
                getattr(event_stream, 'sid', '<unknown>'),
                exc,
            )
        return None

    @staticmethod
    def _checkpoint_session_key(event_stream: EventStream | None) -> str:
        sid = getattr(event_stream, 'sid', None)
        return sid if isinstance(sid, str) and sid else '__global__'

    @staticmethod
    def _sanitize_checkpoint_key(session_key: str) -> str:
        safe = Path(session_key).name.replace('..', '_')
        return safe.replace('/', '_').replace('\\', '_')

    # ------------------------------------------------------------------ #
    # Streaming helpers (provider-agnostic post-hoc streaming)
    # ------------------------------------------------------------------ #
    def _emit_streaming_actions(
        self,
        text: str,
        event_stream: EventStream,
        response: ModelResponse | None = None,
    ) -> None:
        from backend.cli.tool_call_display import redact_streamed_tool_call_markers
        from backend.ledger.action.message import StreamingChunkAction
        from backend.ledger.event import EventSource

        # Keep event volume bounded. UI-side coalescing exists, but we still
        # avoid emitting thousands of tiny events for long responses.
        chunk_size = 80

        # Strip ``[Tool call] name({...})`` blobs (proxy / history echo) from
        # assistant text — structured tool actions already render in the CLI.
        text = redact_streamed_tool_call_markers(text or '').strip()

        # Stream text response if any
        if text:
            accumulated = ''
            for i in range(0, len(text), chunk_size):
                chunk = text[i : i + chunk_size]
                if not chunk:
                    continue
                accumulated += chunk
                ev = StreamingChunkAction(
                    chunk=chunk,
                    accumulated=accumulated,
                    is_final=False,
                )
                ev.source = EventSource.AGENT
                event_stream.add_event(ev, EventSource.AGENT)

            final_ev = StreamingChunkAction(
                chunk='', accumulated=accumulated, is_final=True
            )
            final_ev.source = EventSource.AGENT
            event_stream.add_event(final_ev, EventSource.AGENT)

        # Stream __thought from tool calls if present
        if response and hasattr(response, 'choices') and response.choices:
            try:
                self._emit_thought_chunks(response, event_stream, chunk_size)
            except Exception as e:
                logger.debug('Failed to stream thought chunks: %s', e)

    def _emit_thought_chunks(
        self, response: ModelResponse, event_stream: EventStream, chunk_size: int = 80
    ) -> None:
        from backend.core.tool_arguments_json import parse_tool_arguments_object
        from backend.engine.common import extract_assistant_message
        from backend.ledger.action.message import StreamingChunkAction
        from backend.ledger.event import EventSource

        assistant_msg = extract_assistant_message(response)
        tool_calls = getattr(assistant_msg, 'tool_calls', None)

        if not tool_calls:
            return

        for idx, tool_call in enumerate(tool_calls):
            try:
                fn = getattr(tool_call, 'function', None)
                if fn is None:
                    continue
                raw_args = getattr(fn, 'arguments', None)
                if isinstance(raw_args, dict):
                    args = raw_args
                elif isinstance(raw_args, str) and raw_args.strip():
                    # Route through parse_tool_arguments_object so malformed
                    # escapes don't silently swallow every thought.
                    args = parse_tool_arguments_object(raw_args)
                else:
                    continue
                if '__thought' in args:
                    thought_text = args['__thought']
                    accumulated = ''
                    for i in range(0, len(thought_text), chunk_size):
                        chunk = thought_text[i : i + chunk_size]
                        accumulated += chunk
                        ev = StreamingChunkAction(
                            chunk=chunk,
                            accumulated=accumulated,
                            is_final=False,
                        )
                        ev.source = EventSource.AGENT
                        event_stream.add_event(ev, EventSource.AGENT)

                    final_ev = StreamingChunkAction(
                        chunk='',
                        accumulated=accumulated,
                        is_final=True,
                    )
                    final_ev.source = EventSource.AGENT
                    event_stream.add_event(final_ev, EventSource.AGENT)
            except Exception as exc:
                logger.debug(
                    'Could not parse thought for streaming from tool call %d: %s',
                    idx,
                    exc,
                )

    # ------------------------------------------------------------------ #
    # Response processing
    # ------------------------------------------------------------------ #

    @staticmethod
    def _without_blank_agent_messages(actions: list[Action]) -> list[Action]:
        return _without_blank_agent_messages_impl(actions)

    @staticmethod
    def _is_recoverable_tool_call_error(exc: Exception) -> bool:
        return _is_recoverable_tool_call_error_impl(exc)

    @staticmethod
    def _build_recoverable_tool_call_error_action(exc: Exception) -> Action:
        return _build_recoverable_tool_call_error_action_impl(exc)

    def _response_to_actions(self, response: ModelResponse) -> list[Action]:
        mcp_tools = self._mcp_tools_provider()
        try:
            actions = list(
                orchestrator_function_calling.response_to_actions(
                    response,
                    mcp_tool_names=list(mcp_tools.keys()),
                    mcp_tools=mcp_tools,
                )
            )
        except Exception as exc:
            if not self._is_recoverable_tool_call_error(exc):
                raise
            logger.warning(
                'Recoverable tool-call error from LLM output: %s',
                exc,
            )
            actions = [self._build_recoverable_tool_call_error_action(exc)]

        _, validated_actions = self._safety.apply(
            self._extract_response_text(response), actions
        )
        return validated_actions

    def _extract_response_text(self, response: ModelResponse) -> str:
        return _extract_response_text_impl(response)

    def _content_to_str(self, content: Any) -> str:
        return _content_to_str_impl(content)

    def _extract_last_user_text(self, messages: list[dict[str, Any]]) -> str:
        return _extract_last_user_text_impl(messages)

    def _extract_recent_user_text(self, messages: list[dict[str, Any]]) -> str:
        return _extract_recent_user_text_impl(messages)
