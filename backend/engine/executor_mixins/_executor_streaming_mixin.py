"""Streaming-related methods for OrchestratorExecutor.

Pure code motion: extracted from backend/engine/executor.py. Contains
delta parsing, chunk consumption, fallback handling, and post-stream
event emission. Methods are defined at module level so the class body
binds them via simple names without indirection.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from typing import TYPE_CHECKING, Any

from backend.core.constants import LLM_STREAM_CHUNK_TIMEOUT_SECONDS
from backend.core.logging.logger import app_logger as logger
from backend.engine.executor_mixins._executor_types import (
    _INLINE_CLOSE_THINK_RE,
    _INLINE_OPEN_THINK_RE,
    _AsyncStreamingState,
)
from backend.inference.tool_support.tool_types import is_valid_tool_call_name

if TYPE_CHECKING:
    from backend.engine.executor_mixins._executor_types import ModelResponse
    from backend.ledger.stream import EventStream


class _ExecutorStreamingMixin:
    """Mixin: streaming delta parsing, chunk consumption, fallback, and event emission."""

    @staticmethod
    def _stream_emit_limits() -> tuple[float, int]:
        raw_interval = os.getenv('APP_STREAM_EMIT_INTERVAL_MS', '120').strip()
        raw_min_chars = os.getenv('APP_STREAM_EMIT_MIN_CHARS', '96').strip()
        try:
            interval_ms = float(raw_interval)
        except ValueError:
            interval_ms = 120.0
        try:
            min_chars = int(raw_min_chars)
        except ValueError:
            min_chars = 96
        return max(0.016, interval_ms / 1000.0), max(1, min_chars)

    def _should_emit_stream_snapshot(
        self,
        state: _AsyncStreamingState,
        *,
        channel: str,
        force: bool = False,
    ) -> bool:
        if force:
            return True
        interval, min_chars = self._stream_emit_limits()
        now = time.monotonic()
        if channel == 'text':
            last_at = state.last_text_emit_at
            last_len = state.last_text_emit_len
            current_len = len(state.content_accumulate)
        else:
            last_at = state.last_thinking_emit_at
            last_len = state.last_thinking_emit_len
            current_len = len(state.thinking_accumulate)
        if last_at <= 0.0:
            return True
        if (now - last_at) >= interval:
            return True
        return (current_len - last_len) >= min_chars

    @staticmethod
    def _mark_stream_snapshot_emitted(
        state: _AsyncStreamingState,
        *,
        channel: str,
    ) -> None:
        now = time.monotonic()
        if channel == 'text':
            state.last_text_emit_at = now
            state.last_text_emit_len = len(state.content_accumulate)
            return
        state.last_thinking_emit_at = now
        state.last_thinking_emit_len = len(state.thinking_accumulate)

    async def _flush_stream_paint_events(
        self,
        state: _AsyncStreamingState,
        event_stream: EventStream | None,
    ) -> None:
        """Emit the latest accumulated stream snapshot before the final chunk."""
        if event_stream is None:
            return
        if state.thinking_accumulate:
            await self._emit_stream_thinking_piece(
                state,
                '',
                event_stream,
                force=True,
            )
        if state.content_accumulate:
            await self._emit_stream_text_piece(
                state,
                '',
                event_stream,
                force=True,
            )

    async def _apply_fallback_completion(
        self,
        fallback: Any,
        state: _AsyncStreamingState,
        event_stream: EventStream | None,
    ) -> None:
        fallback_message = self._extract_fallback_message(fallback)
        fallback_content = self._extract_fallback_content(fallback, fallback_message)
        fallback_reasoning = self._extract_fallback_reasoning(
            fallback,
            fallback_message,
        )

        if fallback_content:
            # If the fallback content contains inline thinking tags (like <think>...</think>),
            # we must process it through the text delta parser so the tags are stripped and
            # the thinking/content streams are correctly separated/routed. Directly passing
            # raw content with tags to _emit_stream_text_piece causes duplication/merging
            # issues with the already-accumulated (stripped) stream content.
            pseudo_delta: dict[str, Any] = {'content': fallback_content}
            if fallback_reasoning:
                pseudo_delta['reasoning_content'] = fallback_reasoning
            await self._process_stream_text_delta(
                pseudo_delta,
                state,
                event_stream,
            )
        elif fallback_reasoning:
            await self._emit_stream_thinking_piece(
                state,
                fallback_reasoning,
                event_stream,
            )

        for index, tool_call in enumerate(
            self._extract_fallback_tool_calls(fallback, fallback_message)
        ):
            if not isinstance(tool_call, dict):
                continue  # type: ignore[unreachable]
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
        self._capture_fallback_response_id(state, fallback)

    @staticmethod
    def _capture_stream_response_id(
        state: _AsyncStreamingState,
        chunk: Any,
    ) -> None:
        """Capture the provider response id from the first stream chunk that has one."""
        if (state.stream_response_id or '').strip():
            return
        chunk_id: Any = None
        if isinstance(chunk, dict):
            chunk_id = chunk.get('id')
        else:
            chunk_id = getattr(chunk, 'id', None)
        if isinstance(chunk_id, str) and chunk_id.strip():
            state.stream_response_id = chunk_id.strip()

    @staticmethod
    def _capture_fallback_response_id(
        state: _AsyncStreamingState,
        fallback: Any,
    ) -> None:
        if (state.stream_response_id or '').strip():
            return
        fallback_id = getattr(fallback, 'id', None)
        if fallback_id is None and isinstance(fallback, dict):
            fallback_id = fallback.get('id')
        if isinstance(fallback_id, str) and fallback_id.strip():
            state.stream_response_id = fallback_id.strip()

    @staticmethod
    def _ensure_stream_response_id(state: _AsyncStreamingState) -> str:
        candidate = (state.stream_response_id or '').strip()
        if candidate:
            return candidate
        synthetic = f'grinta-synthetic-{uuid.uuid4().hex}'
        state.stream_response_id = synthetic
        logger.debug('Generated synthetic stream response_id=%s', synthetic)
        return synthetic

    def _build_streaming_response(
        self,
        call_params: dict[str, Any],
        visible_accum: str,
        thinking_accum: str,
        tool_calls_list: list[dict[str, Any]] | None,
        streamed_usage: dict[str, int] | None,
        *,
        stream_response_id: str = '',
    ) -> Any:
        from backend.inference.clients import LLMResponse

        model_name = self._llm_model_name(self._llm) or 'unknown'
        resolved_usage = self._resolve_stream_usage(
            call_params,
            visible_accum,
            tool_calls_list,
            streamed_usage,
        )
        resolved_response_id = (stream_response_id or '').strip()
        if not resolved_response_id:
            resolved_response_id = f'grinta-synthetic-{uuid.uuid4().hex}'
        return LLMResponse(
            content=visible_accum,
            model=model_name,
            usage=resolved_usage,
            response_id=resolved_response_id,
            finish_reason='stop',
            tool_calls=tool_calls_list,
            reasoning_content=thinking_accum,
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

        stream_chunk_timeout = (
            self._timeout_from_env(
                'APP_LLM_STREAM_CHUNK_TIMEOUT_SECONDS',
                LLM_STREAM_CHUNK_TIMEOUT_SECONDS,
            )
            or LLM_STREAM_CHUNK_TIMEOUT_SECONDS
        )
        await self._consume_remaining_stream_chunks(
            stream_aiter,
            event_stream,
            state,
            stream_chunk_timeout,
        )

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

        if self._step_cancelled:
            return False

        got_chunk = False
        chunk: Any = None
        try:
            chunk = await asyncio.wait_for(
                stream_aiter.__anext__(),
                timeout=first_chunk_timeout,
            )
            got_chunk = True
        except StopAsyncIteration:
            return False
        except asyncio.TimeoutError:
            fallback_succeeded = await self._handle_first_chunk_timeout_safe(
                call_params, event_stream, state, first_chunk_timeout
            )
            if not fallback_succeeded:
                return False

        if not got_chunk:
            return False

        if self._step_cancelled:
            return False  # type: ignore[unreachable]

        first_chunk = chunk
        self._capture_stream_response_id(state, first_chunk)

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
            if self._step_cancelled:
                return

            try:
                chunk = await asyncio.wait_for(
                    anext(stream_aiter),
                    timeout=stream_chunk_timeout,
                )
            except StopAsyncIteration:
                return
            except asyncio.TimeoutError:
                logger.warning(
                    'LLM chunk timeout after %.1fs',
                    stream_chunk_timeout,
                    extra={'msg_type': 'LLM_CHUNK_TIMEOUT'},
                )
                raise LLMTimeout(
                    f'LLM chunk timeout after {stream_chunk_timeout}s',
                    model=self._llm_model_name(self._llm),
                ) from None

            self._capture_stream_response_id(state, chunk)
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

            if not self._step_cancelled:
                continue
            return  # type: ignore[unreachable]

    def _emit_final_stream_event(
        self,
        event_stream: EventStream | None,
        content_accumulate: str,
        visible_accum: str,
        tool_calls_list: list[dict[str, Any]] | None,
        *,
        thinking_accumulate: str = '',
    ) -> None:
        if not event_stream:
            return
        has_tools = bool(tool_calls_list)
        has_visible = bool(visible_accum.strip())
        has_thinking = bool(thinking_accumulate.strip())
        if not content_accumulate and not has_visible and not has_thinking:
            return

        from backend.ledger.action.message import StreamingChunkAction
        from backend.ledger.event import EventSource

        draft_reply_accum = '' if has_tools else visible_accum
        from backend.cli.event_rendering.text_utils import (
            sanitize_streaming_thinking_text,
        )

        ev = StreamingChunkAction(
            chunk='',
            accumulated=draft_reply_accum,
            is_final=True,
            suppress_live_response=has_tools,
            thinking_accumulated=sanitize_streaming_thinking_text(thinking_accumulate),
        )
        ev.source = EventSource.AGENT
        event_stream.add_event(ev, EventSource.AGENT)

    async def _emit_stream_text_piece(
        self,
        state: _AsyncStreamingState,
        text_piece: str,
        event_stream: EventStream | None,
        *,
        force: bool = False,
    ) -> None:
        if text_piece:
            state.content_accumulate = self._merge_stream_fragment(
                state.content_accumulate,
                text_piece,
            )
        if not event_stream or not state.content_accumulate:
            return
        if not self._should_emit_stream_snapshot(state, channel='text', force=force):
            return

        from backend.cli.display.tool_call_display import (
            redact_streamed_tool_call_markers,
        )
        from backend.cli.event_rendering.text_utils import (
            sanitize_streaming_thinking_text,
        )
        from backend.ledger.action.message import StreamingChunkAction
        from backend.ledger.event import EventSource

        display_acc = redact_streamed_tool_call_markers(state.content_accumulate)
        ev = StreamingChunkAction(
            chunk=text_piece,
            accumulated=display_acc,
            is_final=False,
            thinking_accumulated=sanitize_streaming_thinking_text(
                state.thinking_accumulate
            ),
        )
        ev.source = EventSource.AGENT
        event_stream.add_event(ev, EventSource.AGENT)
        self._mark_stream_snapshot_emitted(state, channel='text')
        await asyncio.sleep(0)

    async def _emit_stream_thinking_piece(
        self,
        state: _AsyncStreamingState,
        text_piece: str,
        event_stream: EventStream | None,
        *,
        force: bool = False,
    ) -> None:
        if text_piece:
            state.thinking_accumulate = self._merge_stream_fragment(
                state.thinking_accumulate,
                text_piece,
            )
        if not event_stream or not state.thinking_accumulate:
            return
        if not self._should_emit_stream_snapshot(
            state, channel='thinking', force=force
        ):
            return

        from backend.cli.display.tool_call_display import (
            redact_streamed_tool_call_markers,
        )
        from backend.cli.event_rendering.text_utils import (
            sanitize_streaming_thinking_text,
        )
        from backend.ledger.action.message import StreamingChunkAction
        from backend.ledger.event import EventSource

        thinking_display = sanitize_streaming_thinking_text(state.thinking_accumulate)
        ev = StreamingChunkAction(
            chunk='',
            accumulated=redact_streamed_tool_call_markers(state.content_accumulate),
            is_final=False,
            thinking_chunk=text_piece,
            thinking_accumulated=thinking_display,
        )
        ev.source = EventSource.AGENT
        event_stream.add_event(ev, EventSource.AGENT)
        self._mark_stream_snapshot_emitted(state, channel='thinking')
        await asyncio.sleep(0)

    def _emit_streaming_actions(
        self,
        text: str,
        event_stream: EventStream,
        response: ModelResponse | None = None,
    ) -> None:
        from backend.cli.display.tool_call_display import (
            redact_streamed_tool_call_markers,
        )
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
        from backend.core.tools.tool_arguments_json import parse_tool_arguments_object
        from backend.engine.response_processing import extract_assistant_message
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

    @staticmethod
    def _is_reasoning_content_part(part: Any) -> bool:
        if isinstance(part, str) or not isinstance(part, dict):
            return False
        part_type = str(part.get('type') or '').lower()
        if 'reasoning' in part_type or part_type == 'thinking':
            return True
        if part.get('thought') is True or part.get('thinking') is True:
            return True
        return False

    @staticmethod
    def _extract_reasoning_details_text(details: Any) -> str:
        if not isinstance(details, list):
            return ''

        parts: list[str] = []
        for item in details:
            if isinstance(item, str):
                if item:
                    parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            detail_type = str(item.get('type') or '').lower()
            if 'encrypted' in detail_type:
                continue
            for key in ('text', 'summary', 'content'):
                value = item.get(key)
                if isinstance(value, str) and value:
                    parts.append(value)
                    break
        return ''.join(parts)

    @classmethod
    def _extract_reasoning_from_content_parts(cls, content_parts: list[Any]) -> str:
        parts: list[str] = []
        for part in content_parts:
            if not cls._is_reasoning_content_part(part):
                continue
            if isinstance(part, str):
                parts.append(part)
                continue
            for key in ('text', 'summary', 'content', 'reasoning'):
                value = part.get(key)
                if isinstance(value, str) and value:
                    parts.append(value)
                    break
        return ''.join(parts)

    @classmethod
    def _extract_delta_reasoning(cls, delta: dict[str, Any]) -> str:
        for alt_key in ('reasoning_content', 'reasoning', 'thinking'):
            alt_val = delta.get(alt_key)
            if isinstance(alt_val, str) and alt_val:
                return alt_val

        details_text = cls._extract_reasoning_details_text(
            delta.get('reasoning_details')
        )
        if details_text:
            return details_text

        delta_content = delta.get('content')
        if isinstance(delta_content, list):
            reasoning_text = cls._extract_reasoning_from_content_parts(delta_content)
            if reasoning_text:
                return reasoning_text
        return ''

    @classmethod
    def _extract_delta_text(cls, delta: dict[str, Any]) -> str:
        delta_content = delta.get('content')
        if isinstance(delta_content, str):
            return delta_content
        if not isinstance(delta_content, list):
            return ''

        parts: list[str] = []
        for part in delta_content:
            if cls._is_reasoning_content_part(part):
                continue
            if isinstance(part, str):
                parts.append(part)
                continue
            if not isinstance(part, dict):
                continue
            maybe_text = part.get('text')
            if isinstance(maybe_text, str):
                parts.append(maybe_text)
        return ''.join(parts)

    def _extract_fallback_content(
        self, fallback: Any, fallback_message: Any | None
    ) -> str:
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
    def _extract_fallback_message(fallback: Any) -> Any | None:
        choices = getattr(fallback, 'choices', None)
        if not isinstance(choices, list) or not choices:
            return None
        first_choice = choices[0]
        if isinstance(first_choice, dict):
            return first_choice.get('message')
        return getattr(first_choice, 'message', None)

    @classmethod
    def _extract_fallback_reasoning(
        cls,
        fallback: Any,
        fallback_message: Any | None,
    ) -> str:
        for candidate in (fallback_message, fallback):
            if candidate is None:
                continue
            for key in ('reasoning_content', 'reasoning', 'thinking'):
                reasoning = (
                    candidate.get(key)
                    if isinstance(candidate, dict)
                    else getattr(candidate, key, None)
                )
                if isinstance(reasoning, str) and reasoning:
                    return reasoning
            details = (
                candidate.get('reasoning_details')
                if isinstance(candidate, dict)
                else getattr(candidate, 'reasoning_details', None)
            )
            details_text = cls._extract_reasoning_details_text(details)
            if details_text:
                return details_text
        return ''

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

    def _finalize_stream_tool_calls(
        self,
        state: _AsyncStreamingState,
    ) -> list[dict[str, Any]] | None:
        tool_calls_list = self._valid_stream_tool_calls(state.tool_calls_dict)
        if not tool_calls_list and state.content_accumulate:
            from backend.cli.display.tool_call_display import (
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
                tool_calls_list = self._valid_stream_tool_calls(state.tool_calls_dict)

        return tool_calls_list or None

    @staticmethod
    def _valid_stream_tool_calls(
        tool_calls_dict: dict[int, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        tool_calls: list[dict[str, Any]] = []
        for idx in sorted(tool_calls_dict.keys()):
            tool_call = tool_calls_dict[idx]
            function = tool_call.get('function') or {}
            name = function.get('name') if isinstance(function, dict) else ''
            if is_valid_tool_call_name(name):
                tool_calls.append(tool_call)
                continue
            logger.warning(
                'Ignoring malformed streamed tool call with invalid function name: %r',
                name,
            )
        return tool_calls

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
        fallback_timeout = (
            self._timeout_from_env(
                'APP_LLM_FALLBACK_TIMEOUT_SECONDS',
                60.0,
            )
            or 60.0
        )
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

    async def _handle_first_chunk_timeout_safe(
        self,
        call_params: dict[str, Any],
        event_stream: EventStream | None,
        state: _AsyncStreamingState,
        first_chunk_timeout: float,
    ) -> bool:
        try:
            await self._handle_first_chunk_timeout_fallback(
                call_params, event_stream, state, first_chunk_timeout
            )
            return True
        except Exception:
            return False

    async def _ingest_stream_tool_call_chunk(
        self,
        tool_call_chunk: dict[str, Any],
        state: _AsyncStreamingState,
        event_stream: EventStream | None,
    ) -> None:
        from backend.ledger.action.message import StreamingChunkAction
        from backend.ledger.event import EventSource

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
            return

        current_args = state.tool_calls_dict[idx]['function']['arguments']
        state.tool_calls_dict[idx]['function']['arguments'] = (
            self._merge_stream_fragment(current_args, raw_args)
        )
        if event_stream:
            display_name = state.tool_calls_dict[idx]['function']['name']
            if not is_valid_tool_call_name(display_name):
                display_name = 'tool'
            logger.debug(
                'DEBUG: Emitting tool argument chunk of len %d',
                len(raw_args),
            )
            ev = StreamingChunkAction(
                chunk=raw_args,
                accumulated=state.tool_calls_dict[idx]['function']['arguments'],
                is_final=False,
                is_tool_call=True,
                tool_call_name=display_name,
            )
            ev.source = EventSource.AGENT
            event_stream.add_event(ev, EventSource.AGENT)
            await asyncio.sleep(0)

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

    async def _process_stream_delta(
        self,
        delta: dict[str, Any],
        state: _AsyncStreamingState,
        event_stream: EventStream | None,
    ) -> None:
        await self._process_stream_text_delta(delta, state, event_stream)
        await self._process_stream_tool_calls(delta, state, event_stream)

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
                await self._emit_stream_thinking_piece(state, remaining, event_stream)  # type: ignore[unreachable]
                return

            open_match = _INLINE_OPEN_THINK_RE.search(remaining)
            if open_match:
                before = remaining[: open_match.start()]
                if before:
                    await self._emit_stream_text_piece(state, before, event_stream)
                state.in_inline_think_block = True
                remaining = remaining[open_match.end() :]
                continue
            await self._emit_stream_text_piece(state, remaining, event_stream)  # type: ignore[unreachable]
            return

    async def _process_stream_tool_calls(
        self,
        delta: dict[str, Any],
        state: _AsyncStreamingState,
        event_stream: EventStream | None,
    ) -> None:
        tool_call_chunks = delta.get('tool_calls')
        if not tool_call_chunks:
            return

        for tool_call_chunk in tool_call_chunks:
            await self._ingest_stream_tool_call_chunk(
                tool_call_chunk,
                state,
                event_stream,
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

    def _resolve_stream_usage(
        self,
        call_params: dict[str, Any],
        visible_accum: str,
        tool_calls_list: list[dict[str, Any]] | None,
        streamed_usage: dict[str, int] | None,
    ) -> dict[str, Any]:
        if streamed_usage:
            return streamed_usage

        from backend.inference.llm.utils import get_token_count

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

    @staticmethod
    def _visible_stream_content(content_accumulate: str) -> str:
        from backend.cli.display.tool_call_display import (
            redact_streamed_tool_call_markers,
        )

        return redact_streamed_tool_call_markers(content_accumulate).strip()
