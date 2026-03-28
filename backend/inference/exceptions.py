"""Common exception types for LLM operations.

These are used to provide a consistent error interface regardless of the
underlying provider SDK.
"""


class LLMError(Exception):
    """Base exception for all LLM-related errors."""

    def __init__(
        self,
        message: str,
        llm_provider: str | None = None,
        model: str | None = None,
        status_code: int | None = None,
        *args: object,
        **kwargs: object,
    ) -> None:
        super().__init__(message, *args)
        self.message = message
        self.llm_provider = llm_provider
        self.model = model
        self.status_code = status_code
        self.kwargs = kwargs


class APIConnectionError(LLMError):
    """Error connecting to the LLM API."""


class APIError(LLMError):
    """Generic API error from the LLM provider."""


class AuthenticationError(LLMError):
    """Authentication or API key error."""


class BadRequestError(LLMError):
    """Invalid request parameters or format."""


class ContentPolicyViolationError(LLMError):
    """Content blocked by safety filters or policy."""


class ContextWindowExceededError(LLMError):
    """Input or output exceeded the model's context window."""


def is_context_window_error(error_str: str, exc: Exception) -> bool:
    """Return True when *exc* (with lowered *error_str*) looks like a context-window overflow.

    This check is intentionally conservative: it returns ``True`` only when
    the error string contains one of the known provider-specific messages
    **or** the exception is ``ContextWindowExceededError``.
    """
    lowered = error_str.lower() if error_str != error_str.lower() else error_str
    return (
        "contextwindowexceedederror" in lowered
        or "prompt is too long" in lowered
        or "input length and `max_tokens` exceed context limit" in lowered
        or "please reduce the length of either one" in lowered
        or "the request exceeds the available context size" in lowered
        or "context length exceeded" in lowered
        or ("sambanovaexception" in lowered and "maximum context length" in lowered)
        or isinstance(exc, ContextWindowExceededError)
    )


class InternalServerError(LLMError):
    """Server-side error from the LLM provider."""


class NotFoundError(LLMError):
    """Requested model or resource not found."""


class RateLimitError(LLMError):
    """API rate limit exceeded."""


class ServiceUnavailableError(LLMError):
    """LLM service is temporarily unavailable."""


class Timeout(LLMError):
    """Request timed out."""


class OpenAIError(LLMError):
    """OpenAI-specific error."""


__all__ = [
    "LLMError",
    "APIConnectionError",
    "APIError",
    "AuthenticationError",
    "BadRequestError",
    "ContentPolicyViolationError",
    "ContextWindowExceededError",
    "InternalServerError",
    "NotFoundError",
    "OpenAIError",
    "RateLimitError",
    "ServiceUnavailableError",
    "Timeout",
    "is_context_window_error",
]
