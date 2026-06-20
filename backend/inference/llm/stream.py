"""Split from ``llm.py`` — see ``backend.inference.llm`` facade."""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
)

from backend.core.errors import LLMNoResponseError
from backend.inference.exceptions import (
    APIConnectionError,
    InternalServerError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

if TYPE_CHECKING:
    pass

LLM_RETRY_EXCEPTIONS: tuple[type[Exception], ...] = (
    APIConnectionError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
    InternalServerError,
    LLMNoResponseError,
)

# Provider proxies (Lightning AI, OpenRouter, etc.) sometimes inject error
# messages directly into the stream body instead of returning an HTTP error
# code.  These arrive as valid JSON chunks with content that happens to be a
# disconnect notice.  The strings below are lowercased for case-insensitive
# matching.  When detected before any real content has been yielded, the
# stream is aborted and an APIConnectionError is raised so the existing
# backoff/retry machinery kicks in exactly as for a proper network failure.
_INBAND_DISCONNECT_PHRASES: tuple[str, ...] = (
    '网络中断',  # Lightning AI / DeepSeek: "network disconnected"
    '请重新连接',  # Lightning AI: "please reconnect"
    '网络连接中断',  # variant
    # Common mojibake variants observed in proxies/tests where UTF-8 Chinese
    # text is decoded with a Western codepage before reaching the SDK stream.
    'ç½‘ç»œä¸­æ–­',
    'è¯·é‡æ–°è¿žæŽ¥',
    'network disconnected, please reconnect',
    'connection was reset',
    'upstream connect error',
    'upstream request timeout',
    'bad gateway',
    'gateway timeout',
    'service temporarily unavailable',
)

# We only inspect the first _INBAND_PREFIX_LIMIT chars so we never buffer
# the entire stream.  Real responses are never this short, and all known
# in-band error messages fit comfortably within this window.
_INBAND_PREFIX_LIMIT = 256


async def _stream_with_chunk_timeout(
    stream_iter: Any, *, timeout_sec: float | None = None
) -> Any:
    """Yield chunks from *stream_iter*, raising TimeoutError if a chunk takes too long."""
    import asyncio as _asyncio

    from backend.core.constants import LLM_STREAM_CHUNK_TIMEOUT_SECONDS

    if timeout_sec is None:
        timeout_sec = LLM_STREAM_CHUNK_TIMEOUT_SECONDS

    while True:
        try:
            chunk = await _asyncio.wait_for(
                stream_iter.__anext__(), timeout=timeout_sec
            )
        except StopAsyncIteration:
            return
        except _asyncio.TimeoutError:
            from backend.core.logging.logger import app_logger as logger
            from backend.inference.exceptions import Timeout as LLMTimeout

            logger.warning(
                'LLM chunk timeout after %.1fs',
                timeout_sec,
                extra={'msg_type': 'LLM_CHUNK_TIMEOUT'},
            )
            raise LLMTimeout(
                message=f'LLM chunk timeout after {timeout_sec}s',
                model='',
                llm_provider='',
            )
        yield chunk
