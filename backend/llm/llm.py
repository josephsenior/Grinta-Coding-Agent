"""LLM integration and communication layer.

Classes:
    LLM

Functions:
    retry_decorator
"""

from __future__ import annotations

import copy
import time
from collections.abc import AsyncIterator, Callable
from typing import (
    TYPE_CHECKING,
    Any,
)

from backend.core.exceptions import LLMNoResponseError
from backend.core.logger import FORGE_logger as logger
from backend.core.message import Message
from backend.llm.debug_mixin import DebugMixin
from backend.llm.direct_clients import get_direct_client
from backend.llm.exceptions import (
    APIConnectionError,
    APIError,
    AuthenticationError,
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    LLMError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
    is_context_window_error,
)
from backend.llm.llm_utils import create_pretrained_tokenizer, get_token_count
from backend.llm.metrics import Metrics
from backend.llm.model_features import ModelFeatures, get_features
from backend.llm.retry_mixin import RetryMixin

if TYPE_CHECKING:
    from backend.core.config import LLMConfig


def _map_openai_exception(exc: Exception, model: str) -> Exception | None:
    """Map OpenAI SDK exceptions."""
    try:
        import openai as _oai

        if isinstance(exc, _oai.AuthenticationError):
            return AuthenticationError(str(exc), model=model, llm_provider="openai")
        if isinstance(exc, _oai.RateLimitError):
            return RateLimitError(str(exc), model=model, llm_provider="openai")
        if isinstance(exc, _oai.APIConnectionError):
            return APIConnectionError(str(exc), model=model, llm_provider="openai")
        if isinstance(exc, _oai.APITimeoutError):
            return Timeout(str(exc), model=model, llm_provider="openai")
        if isinstance(exc, _oai.BadRequestError):
            if is_context_window_error(str(exc).lower(), exc):
                return ContextWindowExceededError(
                    str(exc), model=model, llm_provider="openai"
                )
            return BadRequestError(str(exc), model=model, llm_provider="openai")
        if isinstance(exc, _oai.InternalServerError):
            return InternalServerError(str(exc), model=model, llm_provider="openai")
        if isinstance(exc, _oai.APIStatusError):
            status = getattr(exc, "status_code", None)
            if status == 503:
                return ServiceUnavailableError(
                    str(exc), model=model, llm_provider="openai"
                )
            return APIError(
                str(exc), model=model, llm_provider="openai", status_code=status
            )
    except ImportError:
        pass
    return None


def _map_anthropic_exception(exc: Exception, model: str) -> Exception | None:
    """Map Anthropic SDK exceptions."""
    try:
        import anthropic as _anth

        if isinstance(exc, _anth.AuthenticationError):
            return AuthenticationError(str(exc), model=model, llm_provider="anthropic")
        if isinstance(exc, _anth.RateLimitError):
            return RateLimitError(str(exc), model=model, llm_provider="anthropic")
        if isinstance(exc, _anth.APIConnectionError):
            return APIConnectionError(str(exc), model=model, llm_provider="anthropic")
        if isinstance(exc, _anth.APITimeoutError):
            return Timeout(str(exc), model=model, llm_provider="anthropic")
        if isinstance(exc, _anth.BadRequestError):
            if is_context_window_error(str(exc).lower(), exc):
                return ContextWindowExceededError(
                    str(exc), model=model, llm_provider="anthropic"
                )
            return BadRequestError(str(exc), model=model, llm_provider="anthropic")
        if isinstance(exc, _anth.InternalServerError):
            return InternalServerError(str(exc), model=model, llm_provider="anthropic")
        if isinstance(exc, _anth.APIStatusError):
            status = getattr(exc, "status_code", None)
            if status == 503:
                return ServiceUnavailableError(
                    str(exc), model=model, llm_provider="anthropic"
                )
            return APIError(
                str(exc), model=model, llm_provider="anthropic", status_code=status
            )
    except ImportError:
        pass
    return None


def _map_provider_exception(exc: Exception, model: str) -> Exception:
    """Map provider SDK exceptions to our :mod:`backend.llm.exceptions` hierarchy.

    If the exception is already one of ours, it passes through unchanged.
    Unknown exceptions are wrapped in :class:`APIError` for uniformity.
    """
    if isinstance(exc, LLMError):
        return exc

    # Attempt provider-specific mapping
    for mapper in [_map_openai_exception, _map_anthropic_exception]:
        mapped = mapper(exc, model)
        if mapped:
            return mapped

    exc_name = type(exc).__name__.lower()
    exc_str = str(exc).lower()

    # Google Generative AI exceptions
    if "google" in exc_name or "generativeai" in exc_name:
        if is_context_window_error(exc_str, exc):
            return ContextWindowExceededError(
                str(exc), model=model, llm_provider="google"
            )
        if "quota" in exc_str or "rate" in exc_str:
            return RateLimitError(str(exc), model=model, llm_provider="google")
        return APIError(str(exc), model=model, llm_provider="google")

    # Content-policy / safety-filter heuristics
    if (
        "content_filter" in exc_str
        or "content policy" in exc_str
        or "safety" in exc_str
    ):
        return ContentPolicyViolationError(str(exc), model=model)

    # Context-window overflow heuristic (catches providers we don't explicitly know)
    if is_context_window_error(exc_str, exc):
        return ContextWindowExceededError(str(exc), model=model)

    # Fallback — wrap in generic APIError so callers always get LLMError subtypes
    return APIError(str(exc), model=model)


__all__ = ["LLM", "_map_provider_exception"]

LLM_RETRY_EXCEPTIONS: tuple[type[Exception], ...] = (
    APIConnectionError,
    RateLimitError,
    ServiceUnavailableError,
    LLMNoResponseError,
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
        self.config: LLMConfig = copy.deepcopy(config)
        self.service_id = service_id
        self.metrics: Metrics = (
            metrics if metrics is not None else Metrics(model_name=config.model)
        )
        self.retry_listener = retry_listener
        self._function_calling_active: bool = False

        # Initialize client
        api_key_value = self._extract_api_key()

        # Local models (Ollama, LM Studio, vLLM) don't require real API keys.
        _is_local = "ollama" in self.config.model.lower() or (
            self.config.base_url
            and any(
                h in self.config.base_url
                for h in ("localhost", "127.0.0.1", "0.0.0.0")
            )
        )

        if not api_key_value and not _is_local:
            logger.error("No API key available for model: %s", self.config.model)
            raise AuthenticationError(
                f"No API key provided for model '{self.config.model}'. "
                "Please set it in Settings -> Models -> API Keys.",
                model=self.config.model,
            )

        self.client = get_direct_client(
            model=self.config.model,
            api_key=api_key_value or "not-needed",
            base_url=self.config.base_url,
        )

        # Configure capabilities
        try:
            features = get_features(self.config.model)
            self._function_calling_active = (
                self.config.native_tool_calling
                if self.config.native_tool_calling is not None
                else features.supports_function_calling
            )
        except (KeyError, ValueError) as exc:
            logger.warning(
                "Could not detect function-calling support for model %s: %s  "
                "— defaulting to disabled. If this model supports tools, "
                "set native_tool_calling=true in the LLM config.",
                self.config.model,
                exc,
            )
            self._function_calling_active = self.config.native_tool_calling or False

        # Initialize model info (limits, etc)
        self.init_model_info()

        # Cache model features for easy access
        try:
            self._cached_features = get_features(self.config.model)
        except (KeyError, ValueError) as exc:
            logger.warning(
                "Model feature lookup failed for %s: %s  "
                "— using empty defaults. Token limits, vision, and "
                "other capabilities may be inaccurate.",
                self.config.model,
                exc,
            )
            from backend.llm.model_features import ModelFeatures

            self._cached_features = ModelFeatures()

        # Handle custom tokenizer
        if self.config.custom_tokenizer:
            tokenizer = create_pretrained_tokenizer(self.config.custom_tokenizer)
            if tokenizer is not None:
                self.config.custom_tokenizer = tokenizer

    @property
    def features(self) -> ModelFeatures:
        """Get model features/capabilities."""
        return self._cached_features

    def init_model_info(self) -> None:
        """Initialize model limits and capabilities.

        Uses native model_features.
        """
        try:
            features = get_features(self.config.model)
            if self.config.max_input_tokens is None:
                self.config.max_input_tokens = features.max_input_tokens
            if self.config.max_output_tokens is None:
                self.config.max_output_tokens = features.max_output_tokens
        except (KeyError, ValueError, AttributeError) as exc:
            logger.warning(
                "Could not initialize token limits for model %s: %s  "
                "— max_input_tokens and max_output_tokens may be None.",
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
        """Merge default config with call-specific kwargs and handle model-specific parameters."""
        is_stream = kwargs.pop("is_stream", False)

        # Filter out compatibility parameters that are not used by direct SDKs
        compatibility_params = [
            "drop_params",
            "force_timeout",
            "metadata",
            "api_base",
            "caching",
        ]
        for param in compatibility_params:
            kwargs.pop(param, None)

        call_kwargs = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_output_tokens,
            **kwargs,
        }
        if self.config.top_p is not None:
            call_kwargs["top_p"] = self.config.top_p
        if self.config.top_k is not None:
            call_kwargs["top_k"] = self.config.top_k

        # Handle model-specific tweaks and optimizations
        model_lower = self.config.model.lower()
        provider_lower = (self.config.custom_llm_provider or "").lower()
        is_gemini = "gemini" in model_lower or "gemini" in provider_lower

        if is_gemini:
            # Gemini specific reasoning mapping
            if self.config.reasoning_effort in [None, "low"]:
                # In streaming, we don't support thinking budget yet for Gemini
                if not is_stream:
                    call_kwargs["thinking"] = {"budget_tokens": 128}
                call_kwargs.pop("reasoning_effort", None)
                # Gemini often doesn't want temperature/top_p when thinking is enabled
                if not is_stream:
                    call_kwargs.pop("temperature", None)
                    call_kwargs.pop("top_p", None)
            elif self.config.reasoning_effort == "medium":
                call_kwargs["reasoning_effort"] = "medium"
                call_kwargs.pop("thinking", None)
            elif self.config.reasoning_effort == "high":
                call_kwargs["reasoning_effort"] = "high"
                call_kwargs.pop("thinking", None)
        elif "opus-4-1" in model_lower:
            # Anthropic Opus 4.1 specific tweaks
            call_kwargs["thinking"] = {"type": "disabled"}
            call_kwargs.pop("top_p", None)
        elif "claude" in model_lower:
            # Claude models don't support reasoning_effort param
            call_kwargs.pop("reasoning_effort", None)
            if "claude-3-7" in model_lower or "claude-3.7" in model_lower:
                # Claude 3.7 supports thinking
                if self.config.reasoning_effort == "low":
                    call_kwargs["thinking"] = {"type": "enabled", "budget_tokens": 1024}
                elif self.config.reasoning_effort in ["medium", "high"]:
                    call_kwargs["thinking"] = {"type": "enabled", "budget_tokens": 4096}
        else:
            if self.config.reasoning_effort is not None:
                call_kwargs["reasoning_effort"] = self.config.reasoning_effort

        if self.config.seed is not None:
            call_kwargs["seed"] = self.config.seed

        return call_kwargs

    def _record_response_metrics(self, response: Any, latency: float) -> None:
        """Record latency, cost, and token usage from an LLM response.

        Centralises the metrics-extraction logic shared by ``completion()``
        and ``acompletion()`` so it is defined in exactly one place.
        """
        self.metrics.add_response_latency(latency, response.id)
        if not response.usage:
            return

        usage = response.usage
        prompt_tokens = usage.get("prompt_tokens", 0)
        completion_tokens = usage.get("completion_tokens", 0)

        cost = self.client.get_completion_cost(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            config=self.config,
        )
        self.metrics.add_cost(cost)

        # Extract cache tokens from provider-specific nested structures
        cache_read = usage.get("cache_read_tokens", 0)
        cache_write = usage.get("cache_write_tokens", 0)

        if not cache_read and "prompt_tokens_details" in usage:
            details: Any = usage["prompt_tokens_details"]
            if hasattr(details, "cached_tokens"):
                cache_read = details.cached_tokens
            elif isinstance(details, dict):
                cache_read = details.get("cached_tokens", 0)

        if not cache_write and "model_extra" in usage:
            extra: Any = usage["model_extra"]
            if isinstance(extra, dict):
                cache_write = extra.get("cache_creation_input_tokens", 0)

        self.metrics.add_token_usage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cache_read_tokens=cache_read,
            cache_write_tokens=cache_write,
            context_window=0,
            response_id=response.id,
        )

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
                mapped = _map_provider_exception(e, self.config.model)
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
        except Exception:
            pass

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
                raise LLMNoResponseError("Request cancelled before start")

            self.log_prompt(messages)
            response = await self.client.acompletion(messages=messages, **kwargs)
            self._record_response_metrics(response, time.time() - start_time)
            self.log_response(response.to_dict())

            # Plugin hook: llm_post
            try:
                from backend.core.plugin import get_plugin_registry

                response = await get_plugin_registry().dispatch_llm_post(response)
            except Exception:
                pass

            return response

        return await _acompletion_with_retry(**call_kwargs)

    async def astream(self, *args, **kwargs) -> AsyncIterator[dict[str, Any]]:
        """Asynchronous streaming call with cancellation support."""
        messages = self._extract_messages(args, kwargs)

        # Merge default kwargs
        call_kwargs = self._get_call_kwargs(is_stream=True, **kwargs)

        # Log prompt
        self.log_prompt(messages)

        try:
            # Type: ignore needed because mypy doesn't understand async generator return types
            # astream returns an async iterator, not a coroutine
            stream_iter = self.client.astream(messages=messages, **call_kwargs)
            async for chunk in stream_iter:  # type: ignore[attr-defined]
                # Check for cancellation during stream
                if await self._check_cancelled():
                    logger.debug("LLM stream cancelled by user.")
                    break

                # Log chunk content if available
                if chunk.get("choices") and chunk["choices"][0].get("delta"):
                    content = chunk["choices"][0]["delta"].get("content", "")
                    if content:
                        self.log_response(content)

                yield chunk
        except Exception as e:
            logger.error("LLM astream error: %s", e)
            mapped = _map_provider_exception(e, self.config.model)
            if mapped is not e:
                raise mapped from e
            raise

    async def _check_cancelled(self) -> bool:
        """Check if the request has been cancelled."""
        if (
            hasattr(self.config, "on_cancel_requested_fn")
            and self.config.on_cancel_requested_fn is not None
        ):
            return await self.config.on_cancel_requested_fn()
        return False

    def _extract_messages(
        self, args: tuple[Any, ...], kwargs: dict[str, Any]
    ) -> list[dict]:
        """Extract and normalize messages from args and kwargs."""
        if len(args) > 0:
            messages_kwarg = args[0]
        elif "messages" in kwargs:
            messages_kwarg = kwargs.pop("messages")
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
        return not self.config.disable_vision

    def is_caching_prompt_active(self) -> bool:
        return self.config.caching_prompt

    def is_function_calling_active(self) -> bool:
        return self._function_calling_active

    def get_token_count(self, messages: list[dict] | list[Message]) -> int:
        """Estimate token count."""
        try:
            return get_token_count(
                messages,
                model=self.config.model,
                custom_tokenizer=self.config.custom_tokenizer,
            )
        except Exception as e:
            logger.error(
                "Error getting token count for\n model %s\n%s", self.config.model, e
            )
            return 0

    def format_messages_for_llm(self, messages: Message | list[Message]) -> list[dict]:
        if isinstance(messages, Message):
            messages = [messages]
        from backend.core.pydantic_compat import model_dump_with_options

        return [model_dump_with_options(m) for m in messages]

    def __str__(self) -> str:
        return f"LLM(model={self.config.model})"

    def __repr__(self) -> str:
        return str(self)
