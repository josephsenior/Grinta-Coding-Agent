"""Split from ``llm.py`` — see ``backend.inference.llm`` facade."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from typing import (
    TYPE_CHECKING,
    Any,
)

from backend.core import json_compat as json
from backend.core.errors import LLMNoResponseError
from backend.core.logging.logger import app_logger as logger
from backend.core.message import Message
from backend.inference.capabilities.model_features import ModelFeatures
from backend.inference.debug_mixin import DebugMixin
from backend.inference.exceptions import (
    APIConnectionError,
    AuthenticationError,
    RateLimitError,
    ServiceUnavailableError,
)
from backend.inference.llm.utils import get_token_count
from backend.inference.metrics import Metrics
from backend.inference.retry_mixin import RetryMixin

if TYPE_CHECKING:
    from backend.core.config import LLMConfig

from backend.inference.llm.config import (
    _apply_base_url_discovery,
    _apply_custom_tokenizer,
    _get_provider_resolver,
    _llm_model_metadata_for_log,
    _load_cached_features,
    _resolve_function_calling_config,
    _safe_call_kwargs_for_log,
    _validate_api_key_or_local,
)
from backend.inference.llm.exceptions import _map_provider_exception
from backend.inference.llm.stream import (
    _INBAND_DISCONNECT_PHRASES,
    _INBAND_PREFIX_LIMIT,
    LLM_RETRY_EXCEPTIONS,
    _stream_with_chunk_timeout,
)


class LLM(RetryMixin, DebugMixin):
    """Language Model abstraction layer with direct SDK client support.

    Provides a unified interface to LLM models from providers including OpenAI,
    Anthropic, Google (Gemini), and xAI (Grok). Handles retries, cost tracking,
    streaming, and provider-specific quirks while using official SDKs for
    better stability and performance.
    """

    def __init__(
        self,
        config: LLMConfig,
        service_id: str,
        metrics: Metrics | None = None,
        retry_listener: Callable[[int, int], None] | None = None,
    ) -> None:
        super().__init__()
        from backend.inference import llm as llm_module

        self.config: LLMConfig = llm_module.copy.deepcopy(config)
        if not self.config.model or not str(self.config.model).strip():
            raise AuthenticationError(
                'No LLM model is configured. Set llm_model in settings.json or LLM_MODEL in the environment.',
                model=None,
            )

        # Early-exit validation: Check if the model name is known to the catalog
        # or has an explicit provider prefix. This prevents hard 404s later.
        resolver = _get_provider_resolver()
        config_provider = getattr(self.config, 'custom_llm_provider', None)
        if (
            isinstance(config_provider, str)
            and config_provider.strip()
            and self.config.model
            and '/' not in str(self.config.model)
        ):
            provider = config_provider.strip().lower()
            model = str(self.config.model).strip()
            if provider and model:
                self.config.model = f'{provider}/{model}'
        try:
            # resolve_provider raises ValueError if the model is unknown and has no prefix
            resolver.resolve_provider(
                self.config.model, config_provider=config_provider
            )
        except ValueError as exc:
            from backend.inference.exceptions import NotFoundError

            raise NotFoundError(
                f"Model '{self.config.model}' is not registered in the catalog and lacks a provider prefix. "
                "Please configure a valid model (e.g. 'openai/gpt-4o' or a known catalog entry).",
                model=self.config.model,
            ) from exc

        self.service_id = service_id
        self.metrics: Metrics = (
            metrics if metrics is not None else Metrics(model_name=self.config.model)
        )
        self.retry_listener = retry_listener
        self._function_calling_active: bool = False

        resolver = _get_provider_resolver()
        _apply_base_url_discovery(self.config, resolver)

        api_key_value = self._extract_api_key()
        _validate_api_key_or_local(api_key_value, self.config, resolver)

        from backend.inference.catalog.catalog_loader import validate_model_transport

        validate_model_transport(
            self.config.model,
            config_provider=getattr(self.config, 'custom_llm_provider', None),
        )

        self.client = llm_module.get_direct_client(
            model=self.config.model,
            api_key=api_key_value or 'not-needed',
            base_url=self.config.base_url,
            timeout=self.config.timeout,
            provider=getattr(self.config, 'custom_llm_provider', None),
        )

        self._function_calling_active = _resolve_function_calling_config(
            self.config.native_tool_calling, self.config.model
        )
        self.init_model_info()
        logger.info(
            'LLM active model metadata: %s',
            json.dumps(
                _llm_model_metadata_for_log(self.config, resolver),
                sort_keys=True,
                default=str,
            ),
        )
        self._cached_features = _load_cached_features(self.config.model)
        _apply_custom_tokenizer(self.config)

        from backend.inference.runtime_profile import (
            attach_runtime_profile,
            resolve_runtime_profile,
        )

        self.runtime_profile = resolve_runtime_profile(
            self.config,
            provider=getattr(self.config, 'custom_llm_provider', None),
        )
        attach_runtime_profile(self.config, self.runtime_profile)
        logger.info(
            'LLM runtime profile: model=%s profile=%s source=%s window=%s',
            self.runtime_profile.model,
            self.runtime_profile.param_profile_id,
            self.runtime_profile.source,
            self.runtime_profile.context_limits.usable_input_tokens,
        )

    @property
    def features(self) -> ModelFeatures:
        """Get model features/capabilities."""
        return self._cached_features

    def init_model_info(self) -> None:
        """Initialize model limits and capabilities.

        Uses native model_features.
        """
        try:
            model = (self.config.model or '').strip()
            if not model:
                return
            from backend.inference import llm as llm_module

            features = llm_module.get_features(model)
            if getattr(self.config, 'context_window_tokens', None) is None:
                self.config.context_window_tokens = features.context_window_tokens
            if self.config.max_input_tokens is None:
                self.config.max_input_tokens = features.max_input_tokens
            if self.config.max_output_tokens is None:
                self.config.max_output_tokens = features.max_output_tokens
        except (KeyError, ValueError, AttributeError) as exc:
            logger.warning(
                'Could not initialize token limits for model %s: %s  '
                '— max_input_tokens and max_output_tokens may be None.',
                self.config.model,
                exc,
            )

    def _extract_api_key(self) -> str | None:
        """Extract API key from config or environment."""
        from backend.core.config.api_key_manager import api_key_manager

        if (
            self.config.api_key
            and self.config.api_key.get_secret_value()
            and self.config.api_key.get_secret_value().strip()
        ):
            return self.config.api_key.get_secret_value()

        key_obj = api_key_manager.get_api_key_for_model(
            self.config.model, self.config.api_key
        )
        return key_obj.get_secret_value() if key_obj else None

    def _get_call_kwargs(self, **kwargs) -> dict:
        """Merge default config with call-specific kwargs and handle model-specific parameters.

        Model-specific parameter overrides are driven by provider catalog files
        via ``apply_model_param_overrides()``.
        """
        is_stream = kwargs.pop('is_stream', False)

        for param in (
            'drop_params',
            'force_timeout',
            'metadata',
            'api_base',
            'caching',
        ):
            kwargs.pop(param, None)
        prompt_accounting = kwargs.pop('_prompt_accounting', None)

        call_kwargs = {
            'model': self.config.model,
            'temperature': self.config.temperature,
            **kwargs,
        }

        # Some providers (including OpenAI-compatible gateways) treat explicit
        # `null` values differently than omitted parameters. In particular,
        # sending `max_tokens: null` can result in empty completions.
        if (
            self.config.max_output_tokens is not None
            and 'max_tokens' not in call_kwargs
            and 'max_completion_tokens' not in call_kwargs
        ):
            call_kwargs['max_tokens'] = self.config.max_output_tokens
        if self.config.top_p is not None:
            call_kwargs['top_p'] = self.config.top_p
        if self.config.top_k is not None:
            call_kwargs['top_k'] = self.config.top_k
        timeout = getattr(self.config, 'timeout', None)
        if timeout is not None:
            call_kwargs['timeout'] = float(timeout)

        from backend.inference.catalog.catalog_loader import (
            apply_model_param_overrides,
            sanitize_call_kwargs_for_provider,
        )

        model = (self.config.model or '').strip() or 'unknown'

        call_kwargs = apply_model_param_overrides(
            model,
            call_kwargs,
            reasoning_effort=self.config.reasoning_effort,
            is_stream=is_stream,
            provider=getattr(self.config, 'custom_llm_provider', None),
            caching_prompt=bool(getattr(self.config, 'caching_prompt', True)),
        )

        if self.config.seed is not None:
            call_kwargs['seed'] = self.config.seed

        call_kwargs = sanitize_call_kwargs_for_provider(model, call_kwargs)

        # Drop explicit None values to avoid sending JSON nulls.
        # Keep falsy values like 0/False.
        final_kwargs = {k: v for k, v in call_kwargs.items() if v is not None}
        log_payload = _safe_call_kwargs_for_log(final_kwargs)
        if isinstance(prompt_accounting, dict):
            log_payload['prompt_accounting'] = prompt_accounting
        log_payload['active_model_metadata'] = _llm_model_metadata_for_log(
            self.config,
            _get_provider_resolver(),
        )
        logger.info(
            'LLM applied call params: %s',
            json.dumps(log_payload, sort_keys=True, default=str),
        )
        return final_kwargs

    def _record_response_metrics(self, response: Any, latency: float) -> None:
        """Record latency, cost, and token usage from an LLM response.

        Centralises the metrics-extraction logic shared by ``completion()``
        and ``acompletion()`` so it is defined in exactly one place.
        """
        self.metrics.add_response_latency(latency, response.id)
        if not response.usage:
            return

        usage = response.usage
        prompt_tokens = usage.get('prompt_tokens', 0)
        completion_tokens = usage.get('completion_tokens', 0)
        usage_estimated = bool(usage.get('is_estimated', False))

        # Extract cache tokens from provider-specific nested structures
        cache_read = usage.get('cache_read_tokens', 0)
        cache_write = usage.get('cache_write_tokens', 0)

        if not cache_read and 'prompt_tokens_details' in usage:
            details: Any = usage['prompt_tokens_details']
            if hasattr(details, 'cached_tokens'):
                cache_read = details.cached_tokens
            elif isinstance(details, dict):
                cache_read = details.get('cached_tokens', 0)

        if not cache_write and 'model_extra' in usage:
            extra: Any = usage['model_extra']
            if isinstance(extra, dict):
                cache_write = extra.get('cache_creation_input_tokens', 0)

        cost = self.client.get_completion_cost(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            config=self.config,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
        )
        self.metrics.add_cost(cost)

        self.metrics.add_token_usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            context_window=self._get_context_window_for_metrics(),
            response_id=response.id,
            usage_estimated=usage_estimated,
        )

    def _get_context_window_for_metrics(self) -> int:
        """Return a best-effort context window (total tokens) for the active model.

        Prefer catalog-driven model features; fall back to config fields.
        Returns 0 when unknown.
        """

        def _as_int(value: Any) -> int | None:
            try:
                if value is None:
                    return None
                iv = int(value)
                return iv if iv > 0 else None
            except Exception:
                return None

        # Model catalog limits (preferred)
        context_window = _as_int(getattr(self.features, 'context_window_tokens', None))
        if context_window is None:
            context_window = _as_int(
                getattr(self.config, 'context_window_tokens', None)
            )
        if context_window is not None:
            return context_window

        max_in = _as_int(getattr(self.features, 'max_input_tokens', None))
        max_out = _as_int(getattr(self.features, 'max_output_tokens', None))

        # Config limits (fallback)
        if max_in is None:
            max_in = _as_int(getattr(self.config, 'max_input_tokens', None))
        if max_out is None:
            max_out = _as_int(getattr(self.config, 'max_output_tokens', None))

        if max_in is not None and max_out is not None:
            return max_in + max_out
        if max_in is not None:
            return max_in
        # Last-ditch: some providers treat max_tokens as a total window, but we
        # don't rely on that heuristic. Unknown → 0.
        return 0

    def completion(self, *args, **kwargs) -> Any:
        """Synchronous completion call."""
        messages = self._extract_messages(args, kwargs)

        # Merge default kwargs
        call_kwargs = self._get_call_kwargs(is_stream=False, **kwargs)

        @self.retry_decorator(
            num_retries=self.config.num_retries,
            retry_exceptions=LLM_RETRY_EXCEPTIONS,
            retry_min_wait=self.config.retry_min_wait,
            retry_max_wait=self.config.retry_max_wait,
            retry_multiplier=self.config.retry_multiplier,
            retry_listener=self.retry_listener,
        )
        def _completion_with_retry(**kwargs):
            start_time = time.time()
            try:
                self.log_prompt(messages)
                response = self.client.completion(messages=messages, **kwargs)
                self._record_response_metrics(response, time.time() - start_time)
                self.log_response(response.to_dict())
                return response
            except Exception as e:
                # Map provider SDK exceptions to our unified hierarchy
                mapped = _map_provider_exception(e, (self.config.model or '').strip())
                if mapped is not e:
                    raise mapped from e
                raise

        return _completion_with_retry(**call_kwargs)

    async def acompletion(self, *args, **kwargs) -> Any:
        """Asynchronous completion call with cancellation support."""
        messages = self._extract_messages(args, kwargs)

        # Plugin hook: llm_pre
        try:
            from backend.core.plugin import get_plugin_registry

            messages = await get_plugin_registry().dispatch_llm_pre(messages)
        except Exception as e:
            logger.warning('Error in LLM pre-plugin dispatch: %s', e)

        # Merge default kwargs
        call_kwargs = self._get_call_kwargs(is_stream=False, **kwargs)

        @self.retry_decorator(
            num_retries=self.config.num_retries,
            retry_exceptions=LLM_RETRY_EXCEPTIONS,
            retry_min_wait=self.config.retry_min_wait,
            retry_max_wait=self.config.retry_max_wait,
            retry_multiplier=self.config.retry_multiplier,
            retry_listener=self.retry_listener,
        )
        async def _acompletion_with_retry(**kwargs):
            start_time = time.time()
            # Check for cancellation before start
            if await self._check_cancelled():
                raise LLMNoResponseError('Request cancelled before start')

            self.log_prompt(messages)
            response = await self.client.acompletion(messages=messages, **kwargs)
            self._record_response_metrics(response, time.time() - start_time)
            self.log_response(response.to_dict())

            # Plugin hook: llm_post
            try:
                from backend.core.plugin import get_plugin_registry

                response = await get_plugin_registry().dispatch_llm_post(response)
            except Exception as e:
                logger.warning('Error in LLM post-plugin dispatch: %s', e)

            return response

        return await _acompletion_with_retry(**call_kwargs)

    def _get_astream_retry_params(self) -> tuple[int, float, float]:
        """Return (max_attempts, retry_min_wait, retry_max_wait)."""
        max_a = getattr(self.config, 'num_retries', None) or 3
        min_w = getattr(self.config, 'retry_min_wait', None) or 1
        max_w = getattr(self.config, 'retry_max_wait', None) or 10
        return max_a, min_w, max_w

    def _should_retry_astream(
        self,
        is_retryable: bool,
        is_last: bool,
        yielded_any: bool,
        exc: Exception | None = None,
    ) -> bool:
        """Return True if we should sleep and retry (not re-raise).

        Rate-limit and service-unavailability errors are intentionally NOT
        retried here.  They must propagate to the outer recovery service
        (recovery_service.py) which handles them correctly by transitioning to
        AgentState.RATE_LIMITED and scheduling exponential backoff.  Retrying
        them inside astream() consumes the first-chunk timeout window and
        prevents that outer machinery from ever seeing the rate-limit.
        """
        if exc is not None and isinstance(
            exc, (RateLimitError, ServiceUnavailableError)
        ):
            return False
        return is_retryable and not is_last and not yielded_any

    def _notify_retry_listener(  # type: ignore[override]
        self,
        attempt: int,
        max_attempts: int,
        **kwargs: Any,
    ) -> None:
        listener = getattr(self, 'retry_listener', None)
        if listener is None:
            return
        try:
            listener(attempt, max_attempts, **kwargs)
            return
        except TypeError:
            pass
        listener(attempt, max_attempts)

    def _notify_stream_retry(self, attempt: int, max_attempts: int) -> None:
        if attempt > 1:
            self._notify_retry_listener(
                attempt,
                max_attempts,
                status_type='llm_retry_resuming',
                reason='stream reconnect',
                source='llm_stream',
                streaming=True,
            )

    def _probe_inband_disconnect(self, prefix: str) -> None:
        if len(prefix) > _INBAND_PREFIX_LIMIT:
            return
        lower = prefix.lower()
        logger.debug(
            'LLM in-band disconnect prefix probe',
            extra={
                'msg_type': 'LLM_INBAND_PROBE',
                'prefix_preview': prefix[:120],
                'prefix_repr': repr(prefix[:120]),
                'lower_preview': lower[:120],
                'matched_phrases': [
                    p for p in _INBAND_DISCONNECT_PHRASES if p in lower
                ][:5],
            },
        )
        if any(p in lower for p in _INBAND_DISCONNECT_PHRASES):
            raise APIConnectionError(
                f'Provider sent in-band disconnect message: {prefix.strip()!r}',
                model=(self.config.model or '').strip(),
            )

    async def _process_astream_chunk(
        self,
        chunk: dict[str, Any],
        yielded_any: bool,
        inband_prefix: list[str],
    ) -> bool | None:
        if await self._check_cancelled():
            logger.debug('LLM stream cancelled by user.')
            return None
        if chunk.get('choices') and chunk['choices'][0].get('delta'):
            content = chunk['choices'][0]['delta'].get('content', '')
            if content:
                self.log_response(content)
                if not yielded_any:
                    inband_prefix.append(content)
                    prefix = ''.join(inband_prefix)
                    self._probe_inband_disconnect(prefix)
        return True

    async def _handle_astream_error(
        self,
        e: Exception,
        attempt: int,
        max_attempts: int,
        yielded_any: bool,
        retry_min: float,
        retry_max: float,
    ) -> None:
        import asyncio as _asyncio

        is_retryable = isinstance(e, LLM_RETRY_EXCEPTIONS)
        is_last = attempt >= max_attempts
        if not self._should_retry_astream(is_retryable, is_last, yielded_any, exc=e):
            logger.error('LLM astream error: %s', e)
            mapped = _map_provider_exception(e, (self.config.model or '').strip())
            if mapped is not e:
                raise mapped from e
            raise
        wait = min(retry_max, retry_min * (2 ** (attempt - 1)))
        logger.warning(
            'LLM astream transient error (attempt %d/%d): %s — retrying in %.1fs',
            attempt,
            max_attempts,
            e,
            wait,
        )
        self._notify_retry_listener(
            attempt,
            max_attempts,
            status_type='llm_retry_pending',
            reason=type(e).__name__,
            wait_seconds=wait,
            source='llm_stream',
            streaming=True,
        )
        await _asyncio.sleep(wait)

    async def astream(self, *args, **kwargs) -> AsyncIterator[dict[str, Any]]:
        """Asynchronous streaming call with cancellation support and retry.

        Unlike ``acompletion`` we cannot wrap the entire generator with
        tenacity's ``@retry`` because it expects a normal return value.
        Instead we implement a manual retry loop that restarts the stream
        from scratch on transient failures (same exception set as
        ``acompletion``).
        """
        messages = self._extract_messages(args, kwargs)
        call_kwargs = self._get_call_kwargs(is_stream=True, **kwargs)
        max_attempts, retry_min, retry_max = self._get_astream_retry_params()

        for attempt in range(1, max_attempts + 1):
            yielded_any = False
            _inband_prefix: list[str] = []
            try:
                self._notify_stream_retry(attempt, max_attempts)
                self.log_prompt(messages)
                stream_iter = self.client.astream(messages=messages, **call_kwargs)
                async for chunk in _stream_with_chunk_timeout(stream_iter):
                    result = await self._process_astream_chunk(
                        chunk, yielded_any, _inband_prefix
                    )
                    if result is None:
                        return
                    yield chunk
                    yielded_any = True
                return
            except Exception as e:
                await self._handle_astream_error(
                    e, attempt, max_attempts, yielded_any, retry_min, retry_max
                )

    async def _check_cancelled(self) -> bool:
        """Check if the request has been cancelled."""
        if (
            hasattr(self.config, 'on_cancel_requested_fn')
            and self.config.on_cancel_requested_fn is not None
        ):
            return await self.config.on_cancel_requested_fn()
        return False

    def _extract_messages(
        self, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> list[dict]:
        """Extract and normalize messages from args and kwargs."""
        if args:
            messages_kwarg = args[0]
        elif 'messages' in kwargs:
            messages_kwarg = kwargs.pop('messages')
        else:
            messages_kwarg = []

        if isinstance(messages_kwarg, list):
            messages_list = messages_kwarg
        else:
            messages_list = [messages_kwarg]

        normalized_messages = []
        for m in messages_list:
            if isinstance(m, Message):
                from backend.core.pydantic_compat import model_dump_with_options

                normalized_messages.append(model_dump_with_options(m))
            else:
                normalized_messages.append(m)

        return normalized_messages

    def vision_is_active(self) -> bool:
        return bool(self.config.vision_is_active)

    def is_caching_prompt_active(self) -> bool:
        return self.config.caching_prompt

    def is_function_calling_active(self) -> bool:
        return self._function_calling_active

    def get_token_count(self, messages: list[dict] | list[Message]) -> int:
        """Estimate token count."""
        try:
            model = (self.config.model or '').strip()
            return get_token_count(
                messages,
                model=model,
                custom_tokenizer=self.config.custom_tokenizer,
            )
        except Exception as e:
            logger.error(
                'Error getting token count for\n model %s\n%s', self.config.model, e
            )
            # Conservative fallback: ~4 chars per token is a safe heuristic.
            # Returning 0 here would cause downstream code to believe the
            # context is empty, leading to context-window overflows.
            try:
                raw = str(messages)
                return max(len(raw) // 4, 1)
            except Exception:
                return 1

    def format_messages_for_llm(self, messages: Message | list[Message]) -> list[dict]:
        if isinstance(messages, Message):
            messages = [messages]
        from backend.core.pydantic_compat import model_dump_with_options

        return [model_dump_with_options(m) for m in messages]

    def __str__(self) -> str:
        return f'LLM(model={self.config.model})'

    def __repr__(self) -> str:
        return str(self)
