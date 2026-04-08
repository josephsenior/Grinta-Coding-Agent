from __future__ import annotations

import asyncio
import os
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

from backend.core.errors import ModelProviderError
from backend.core.logger import app_logger as logger
from backend.engine import function_calling as _function_calling_module  # noqa: F401
from backend.engine.streaming_checkpoint import StreamingCheckpoint
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


@dataclass(slots=True)
class ExecutionResult:
    """Container for executor outcomes."""

    actions: list[Action] = field(default_factory=list)
    response: ModelResponse | Any | None = None
    execution_time: float = 0.0
    error: str | None = None


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
        actions = self._without_blank_agent_messages(self._response_to_actions(response))
        return ExecutionResult(actions, response, execution_time, error_message)

    # ------------------------------------------------------------------ #
    # Async streaming execution
    # ------------------------------------------------------------------ #
    async def async_execute(
        self,
        params: dict,
        event_stream: EventStream | None,
    ) -> ExecutionResult:
        """Execute LLM call with async interface natively streaming tokens."""
        checkpoint = self._get_checkpoint(event_stream)
        self._raise_if_recovery_blocked(event_stream)
        from backend.inference.direct_clients import LLMResponse
        from backend.ledger.action.message import StreamingChunkAction
        from backend.ledger.event import EventSource

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

        content_accumulate = ''
        tool_calls_dict = {}
        # Captured from the provider's usage chunk (e.g. OpenAI with
        # stream_options={include_usage:True}, Anthropic, Gemini).  None until
        # a usage chunk arrives; used to record real metrics after streaming.
        streamed_usage: dict[str, int] | None = None

        try:
            from backend.cli.tool_call_display import redact_streamed_tool_call_markers

            logger.info('OrchestratorExecutor.async_execute: calling LLM.astream')
            stream_iter = self._llm.astream(**call_params)

            first_chunk_timeout: float | None = 45.0
            first_chunk_timeout_raw = os.getenv(
                'APP_LLM_FIRST_CHUNK_TIMEOUT_SECONDS', '45'
            ).strip()
            try:
                parsed_first_chunk_timeout = float(first_chunk_timeout_raw)
                first_chunk_timeout = (
                    parsed_first_chunk_timeout
                    if parsed_first_chunk_timeout > 0
                    else None
                )
            except ValueError:
                first_chunk_timeout = 45.0

            async def _consume_stream():
                nonlocal content_accumulate, streamed_usage
                thinking_accumulate = ''

                async def _emit_text_piece(text_piece: str) -> None:
                    nonlocal content_accumulate
                    if not text_piece:
                        return

                    content_accumulate += text_piece
                    display_acc = redact_streamed_tool_call_markers(
                        content_accumulate
                    )
                    if event_stream:
                        ev = StreamingChunkAction(
                            chunk=text_piece,
                            accumulated=display_acc,
                            is_final=False,
                            thinking_accumulated=thinking_accumulate,
                        )
                        ev.source = EventSource.AGENT
                        event_stream.add_event(ev, EventSource.AGENT)
                        # Yield so Socket.IO / asyncio can flush between chunks.
                        await asyncio.sleep(0)

                async def _emit_thinking_piece(text_piece: str) -> None:
                    nonlocal thinking_accumulate
                    if not text_piece:
                        return

                    thinking_accumulate += text_piece
                    if event_stream:
                        ev = StreamingChunkAction(
                            chunk='',
                            accumulated=redact_streamed_tool_call_markers(
                                content_accumulate
                            ),
                            is_final=False,
                            thinking_chunk=text_piece,
                            thinking_accumulated=thinking_accumulate,
                        )
                        ev.source = EventSource.AGENT
                        event_stream.add_event(ev, EventSource.AGENT)
                        await asyncio.sleep(0)

                async def _process_delta(delta: dict[str, Any]) -> None:
                    text_chunk = ''
                    delta_content = delta.get('content')
                    if isinstance(delta_content, str):
                        text_chunk = delta_content
                    elif isinstance(delta_content, list):
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
                        text_chunk = ''.join(parts)

                    # Some OpenAI-compatible providers stream reasoning under
                    # alternate keys instead of delta.content.  Route these to
                    # the dedicated thinking channel so the UI can display them
                    # in the reasoning panel rather than as regular content.
                    reasoning_chunk = ''
                    for alt_key in ('reasoning_content', 'reasoning'):
                        alt_val = delta.get(alt_key)
                        if isinstance(alt_val, str) and alt_val:
                            reasoning_chunk = alt_val
                            break

                    if reasoning_chunk:
                        await _emit_thinking_piece(reasoning_chunk)

                    if text_chunk:
                        await _emit_text_piece(text_chunk)

                    if 'tool_calls' in delta and delta['tool_calls']:
                        for tc_chunk in delta['tool_calls']:
                            idx = tc_chunk['index']
                            if idx not in tool_calls_dict:
                                tool_calls_dict[idx] = {
                                    'id': tc_chunk.get('id'),
                                    'type': 'function',
                                    'function': {'name': '', 'arguments': ''},
                                }

                            fn = tc_chunk.get('function', {})
                            if fn.get('name'):
                                tool_calls_dict[idx]['function']['name'] += fn['name']

                            if fn.get('arguments'):
                                chunk_args = fn['arguments']
                                tool_calls_dict[idx]['function']['arguments'] += (
                                    chunk_args
                                )
                                if event_stream:
                                    logger.debug(
                                        'DEBUG: Emitting tool argument chunk of len %d',
                                        len(chunk_args),
                                    )
                                    ev = StreamingChunkAction(
                                        chunk=chunk_args,
                                        accumulated=tool_calls_dict[idx]['function'][
                                            'arguments'
                                        ],
                                        is_final=False,
                                        is_tool_call=True,
                                        tool_call_name=tool_calls_dict[idx]['function'][
                                            'name'
                                        ],
                                    )
                                    ev.source = EventSource.AGENT
                                    event_stream.add_event(ev, EventSource.AGENT)
                                    await asyncio.sleep(0)

                stream_aiter = stream_iter.__aiter__()
                if first_chunk_timeout is not None:
                    try:
                        first_chunk = await asyncio.wait_for(
                            stream_aiter.__anext__(),
                            timeout=first_chunk_timeout,
                        )
                    except StopAsyncIteration:
                        return
                    except asyncio.TimeoutError:
                        logger.warning(
                            'LLM stream produced no first chunk after %.1fs; '
                            'falling back to non-stream completion',
                            first_chunk_timeout,
                        )

                        # Notify the UI so the user doesn't think it's hung.
                        if event_stream:
                            from backend.ledger.observation import StatusObservation
                            status_ev = StatusObservation(
                                content='Stream timed out — retrying without streaming…'
                            )
                            event_stream.add_event(status_ev, EventSource.ENVIRONMENT)

                        fallback_params = dict(call_params)
                        fallback_params['stream'] = False

                        fallback_timeout = 60.0
                        try:
                            _fb_raw = os.getenv(
                                'APP_LLM_FALLBACK_TIMEOUT_SECONDS', '60'
                            )
                            _fb_parsed = float(_fb_raw)
                            fallback_timeout = _fb_parsed if _fb_parsed > 0 else 60.0
                        except (TypeError, ValueError):
                            fallback_timeout = 60.0
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
                            from backend.inference.exceptions import (
                                Timeout as LLMTimeout,
                            )

                            model_name = getattr(
                                getattr(self._llm, 'config', None), 'model', None
                            )
                            raise LLMTimeout(
                                f'Fallback completion timed out after {fallback_timeout} seconds',
                                model=model_name,
                            )

                        fallback_content_raw = getattr(fallback, 'content', None)
                        fallback_content = (
                            self._content_to_str(fallback_content_raw)
                            if fallback_content_raw is not None
                            else ''
                        )

                        fallback_message: Any | None = None
                        choices = getattr(fallback, 'choices', None)
                        if isinstance(choices, list) and choices:
                            first_choice = choices[0]
                            if isinstance(first_choice, dict):
                                fallback_message = first_choice.get('message')
                            else:
                                fallback_message = getattr(
                                    first_choice, 'message', None
                                )

                        if not fallback_content and fallback_message is not None:
                            if isinstance(fallback_message, dict):
                                fallback_content = self._content_to_str(
                                    fallback_message.get('content')
                                )
                            else:
                                fallback_content = self._content_to_str(
                                    getattr(fallback_message, 'content', None)
                                )

                        if fallback_content:
                            await _emit_text_piece(fallback_content)

                        fallback_tool_calls = getattr(fallback, 'tool_calls', None)
                        if not isinstance(fallback_tool_calls, list):
                            fallback_tool_calls = None
                        if fallback_tool_calls is None and fallback_message is not None:
                            if isinstance(fallback_message, dict):
                                maybe_tool_calls = fallback_message.get('tool_calls')
                            else:
                                maybe_tool_calls = getattr(
                                    fallback_message, 'tool_calls', None
                                )
                            if isinstance(maybe_tool_calls, list):
                                fallback_tool_calls = maybe_tool_calls
                        fallback_tool_calls = fallback_tool_calls or []

                        if isinstance(fallback_tool_calls, list):
                            for i, tc in enumerate(fallback_tool_calls):
                                if not isinstance(tc, dict):
                                    continue
                                fn = tc.get('function') or {}
                                name = fn.get('name') if isinstance(fn, dict) else ''
                                arguments = (
                                    fn.get('arguments') if isinstance(fn, dict) else ''
                                )
                                tool_calls_dict[i] = {
                                    'id': tc.get('id'),
                                    'type': tc.get('type', 'function'),
                                    'function': {
                                        'name': name if isinstance(name, str) else '',
                                        'arguments': arguments
                                        if isinstance(arguments, str)
                                        else '',
                                    },
                                }
                        return

                    choices = first_chunk.get('choices', [])
                    if choices:
                        await _process_delta(choices[0].get('delta', {}))
                    else:
                        # First chunk might be a provider usage chunk (no choices).
                        _fc_usage = first_chunk.get('usage')
                        if _fc_usage and isinstance(_fc_usage, dict):
                            streamed_usage = _fc_usage

                while True:
                    try:
                        chunk = await asyncio.wait_for(
                            anext(stream_aiter), timeout=20.0
                        )
                    except StopAsyncIteration:
                        break
                    except asyncio.TimeoutError:
                        logger.warning(
                            'LLM stream chunk timed out mid-generation after 20 seconds. Streaming stalled.'
                        )
                        from backend.inference.exceptions import Timeout as LLMTimeout

                        model_name = getattr(
                            getattr(self._llm, 'config', None), 'model', None
                        )
                        raise LLMTimeout(
                            'LLM stream chunk timed out mid-generation after 20 seconds',
                            model=model_name,
                        )

                    choices = chunk.get('choices', [])
                    if not choices:
                        # Capture provider usage chunks (OpenAI stream_options,
                        # Anthropic message_usage, Gemini usage_metadata).
                        _chunk_usage = chunk.get('usage')
                        if _chunk_usage and isinstance(_chunk_usage, dict):
                            streamed_usage = _chunk_usage
                        continue
                    await _process_delta(choices[0].get('delta', {}))

            consume_task = loop.create_task(_consume_stream())
            if timeout_seconds is None:
                await consume_task
            else:
                await asyncio.wait_for(consume_task, timeout=timeout_seconds)

            # finalize streams
            visible_accum = redact_streamed_tool_call_markers(content_accumulate).strip()
            if event_stream and content_accumulate:
                ev = StreamingChunkAction(
                    chunk='', accumulated=visible_accum, is_final=True
                )
                ev.source = EventSource.AGENT
                event_stream.add_event(ev, EventSource.AGENT)

            tool_calls_list: list[dict[str, Any]] | None = [
                tool_calls_dict[idx] for idx in sorted(tool_calls_dict.keys())
            ]
            if not tool_calls_list:
                tool_calls_list = None

            model_name = getattr(getattr(self._llm, 'config', None), 'model', 'unknown')
            if streamed_usage:
                _resolved_usage = streamed_usage
            else:
                # Provider didn't send usage data (e.g. Google Gemini via
                # OpenAI-compat, OpenRouter, local models).  Estimate tokens
                # so the HUD still shows meaningful numbers.
                from backend.inference.llm_utils import get_token_count

                _est_prompt = get_token_count(call_params.get('messages') or [])
                _est_completion = max(1, len(visible_accum) // 4)
                # Include tool-call argument text in the estimate.
                if tool_calls_list:
                    for _tc in tool_calls_list:
                        _fn = _tc.get('function', {})
                        _est_completion += max(0, len(_fn.get('arguments', '')) // 4)
                _resolved_usage = {
                    'prompt_tokens': _est_prompt,
                    'completion_tokens': _est_completion,
                    'total_tokens': _est_prompt + _est_completion,
                }
            response = LLMResponse(
                content=visible_accum,
                model=model_name,
                usage=_resolved_usage,
                response_id='',
                finish_reason='stop',
                tool_calls=tool_calls_list,
            )
            # Record metrics on the LLM so HUD reflects real token/cost data.
            _pt = int(_resolved_usage.get('prompt_tokens', 0) or 0)
            _ct = int(_resolved_usage.get('completion_tokens', 0) or 0)
            if _pt > 0 or _ct > 0:
                try:
                    _stream_latency = time.time() - start_time
                    self._llm._record_response_metrics(response, _stream_latency)  # type: ignore[attr-defined]
                except Exception as _me:
                    logger.debug('Failed to record streaming metrics: %s', _me)

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
        actions = self._without_blank_agent_messages(self._response_to_actions(response))
        return ExecutionResult(actions, response, execution_time, error_message)

    def _raise_if_recovery_blocked(self, event_stream: EventStream | None) -> None:
        session_key = self._checkpoint_session_key(event_stream)
        reason = self._recovery_blocked_reasons.pop(session_key, None)
        if not reason:
            return
        raise ModelProviderError(
            'Streaming checkpoint recovery requires manual confirmation before continuing.',
            context={'recovery_reason': reason},
        )

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

        checkpoint = StreamingCheckpoint(checkpoint_dir)
        inspection = checkpoint.inspect_recovery()
        if inspection.status == 'blocked_uncommitted':
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
        import json

        from backend.engine.common import extract_assistant_message
        from backend.ledger.action.message import StreamingChunkAction
        from backend.ledger.event import EventSource

        assistant_msg = extract_assistant_message(response)
        tool_calls = getattr(assistant_msg, 'tool_calls', None)

        if not tool_calls:
            return

        for idx, tool_call in enumerate(tool_calls):
            try:
                if getattr(tool_call, 'function', None) and isinstance(
                    tool_call.function.arguments, str
                ):
                    args = json.loads(tool_call.function.arguments)
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
        """Drop agent ``MessageAction``s with nothing user-visible (no text, no thought)."""
        from backend.ledger.action import MessageAction

        out: list[Action] = []
        for action in actions:
            if isinstance(action, MessageAction):
                content = str(getattr(action, 'content', '') or '').strip()
                thought = str(getattr(action, 'thought', '') or '').strip()
                if not content and not thought:
                    continue
            out.append(action)
        return out

    def _response_to_actions(self, response: ModelResponse) -> list[Action]:
        mcp_tools = self._mcp_tools_provider()
        actions = list(
            orchestrator_function_calling.response_to_actions(
                response,
                mcp_tool_names=list(mcp_tools.keys()),
                mcp_tools=mcp_tools,
            )
        )

        _, validated_actions = self._safety.apply(self._extract_response_text(response), actions)
        return validated_actions

    def _extract_response_text(self, response: ModelResponse) -> str:
        if not hasattr(response, 'choices') or not response.choices:
            return ''
        choice = response.choices[0]
        if not hasattr(choice, 'message'):
            return ''
        content = getattr(choice.message, 'content', None)
        return self._content_to_str(content)

    def _content_to_str(self, content: Any) -> str:
        """Convert message content (str, list of parts, etc.) to a plain string."""
        if isinstance(content, str):
            return content
        if isinstance(content, dict):
            text = content.get('text')
            return text if isinstance(text, str) else ''
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str) and item:
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get('text')
                    if isinstance(text, str) and text:
                        parts.append(text)
            return ''.join(parts)
        return str(content) if content else ''

    def _extract_last_user_text(self, messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            role = str(message.get('role', ''))
            content = message.get('content', '')
            if role != 'user':
                continue
            return self._content_to_str(content).strip()
        return ''

    def _extract_recent_user_text(self, messages: list[dict[str, Any]]) -> str:
        for message in reversed(messages):
            role = str(message.get('role', ''))
            content = message.get('content', '')
            if role != 'user':
                continue
            text = self._content_to_str(content).strip()
            if text:
                return text
        return ''
