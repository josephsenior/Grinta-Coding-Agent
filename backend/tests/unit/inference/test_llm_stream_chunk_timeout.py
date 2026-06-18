"""Tests for inter-chunk LLM stream timeout logging."""

from __future__ import annotations

import asyncio

import pytest

from backend.inference.exceptions import Timeout as LLMTimeout
from backend.inference.llm.stream import _stream_with_chunk_timeout


@pytest.mark.asyncio
async def test_stream_chunk_timeout_raises_with_distinct_error() -> None:
    async def _slow_stream():
        await asyncio.sleep(3600)
        yield {'choices': []}

    with pytest.raises(LLMTimeout, match='LLM chunk timeout after'):
        async for _chunk in _stream_with_chunk_timeout(
            _slow_stream(),
            timeout_sec=0.05,
        ):
            pass
