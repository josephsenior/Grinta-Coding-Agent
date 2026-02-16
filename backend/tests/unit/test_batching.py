"""Tests for backend.llm.utils.batching — LLM batch processor."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.llm.utils.batching import (
    BatchRequest,
    BatchResult,
    LLMBatchProcessor,
    create_batch_processor,
)


# ---------------------------------------------------------------------------
# BatchRequest
# ---------------------------------------------------------------------------

class TestBatchRequest:
    """Tests for the BatchRequest dataclass."""

    def test_defaults(self):
        req = BatchRequest(prompt="hello")
        assert req.prompt == "hello"
        assert req.model is None
        assert req.temperature == 0.0
        assert req.max_tokens is None
        assert req.metadata == {}

    def test_metadata_default_init(self):
        req = BatchRequest(prompt="x")
        assert req.metadata == {}
        # Ensure each instance gets its own dict
        req2 = BatchRequest(prompt="y")
        req.metadata["key"] = "value"
        assert "key" not in req2.metadata

    def test_custom_values(self):
        req = BatchRequest(
            prompt="test",
            model="gpt-4",
            temperature=0.7,
            max_tokens=100,
            metadata={"project": "forge"},
        )
        assert req.model == "gpt-4"
        assert req.temperature == 0.7
        assert req.max_tokens == 100
        assert req.metadata == {"project": "forge"}


# ---------------------------------------------------------------------------
# BatchResult
# ---------------------------------------------------------------------------

class TestBatchResult:
    """Tests for the BatchResult dataclass."""

    def test_success_result(self):
        r = BatchResult(success=True, response="hello", provider="primary")
        assert r.success is True
        assert r.response == "hello"
        assert r.error is None
        assert r.cost == 0.0
        assert r.latency_ms == 0.0

    def test_failure_result(self):
        exc = RuntimeError("boom")
        r = BatchResult(success=False, error=exc)
        assert r.success is False
        assert r.error is exc
        assert r.response is None


# ---------------------------------------------------------------------------
# LLMBatchProcessor
# ---------------------------------------------------------------------------

class TestLLMBatchProcessor:
    """Tests for the LLMBatchProcessor class."""

    def _make_llm(self, response_text="answer"):
        """Create a mock LLM with async completion."""
        llm = MagicMock()
        choice = MagicMock()
        choice.message.content = response_text
        resp = MagicMock()
        resp.choices = [choice]
        llm.acompletion = AsyncMock(return_value=resp)
        llm.metrics = {"accumulated_cost": 0.01}
        return llm

    def test_init_defaults(self):
        llm = self._make_llm()
        proc = LLMBatchProcessor(primary_llm=llm)
        assert proc.batch_size == 5
        assert proc.max_concurrent == 10
        assert proc.backup_llms == []

    async def test_process_batch_single_request(self):
        llm = self._make_llm("hello")
        proc = LLMBatchProcessor(primary_llm=llm, batch_size=5)
        results = await proc.process_batch([BatchRequest(prompt="hi")])
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].response == "hello"
        assert results[0].provider == "primary"

    async def test_process_batch_multiple_requests(self):
        llm = self._make_llm("ok")
        proc = LLMBatchProcessor(primary_llm=llm, batch_size=10)
        reqs = [BatchRequest(prompt=f"q{i}") for i in range(3)]
        results = await proc.process_batch(reqs)
        assert len(results) == 3
        assert all(r.success for r in results)

    async def test_process_batch_splits_into_batches(self):
        llm = self._make_llm("ok")
        proc = LLMBatchProcessor(primary_llm=llm, batch_size=2)
        reqs = [BatchRequest(prompt=f"q{i}") for i in range(5)]
        results = await proc.process_batch(reqs)
        assert len(results) == 5

    async def test_failover_to_backup(self):
        primary = MagicMock()
        primary.acompletion = AsyncMock(side_effect=RuntimeError("primary down"))

        backup = self._make_llm("backup answer")
        proc = LLMBatchProcessor(primary_llm=primary, backup_llms=[backup])
        results = await proc.process_batch([BatchRequest(prompt="help")])
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].response == "backup answer"
        assert results[0].provider == "backup"

    async def test_all_providers_fail(self):
        primary = MagicMock()
        primary.acompletion = AsyncMock(side_effect=RuntimeError("primary fail"))

        backup = MagicMock()
        backup.acompletion = AsyncMock(side_effect=RuntimeError("backup fail"))

        proc = LLMBatchProcessor(primary_llm=primary, backup_llms=[backup])
        results = await proc.process_batch([BatchRequest(prompt="help")])
        assert len(results) == 1
        assert results[0].success is False
        assert results[0].error is not None

    async def test_empty_batch(self):
        llm = self._make_llm()
        proc = LLMBatchProcessor(primary_llm=llm)
        results = await proc.process_batch([])
        assert results == []

    async def test_latency_tracked(self):
        llm = self._make_llm("fast")
        proc = LLMBatchProcessor(primary_llm=llm)
        results = await proc.process_batch([BatchRequest(prompt="x")])
        assert results[0].latency_ms >= 0

    async def test_uses_fallback_when_no_acompletion(self):
        llm = MagicMock()
        llm.acompletion = None  # Force fallback path
        choice = MagicMock()
        choice.message.content = "sync_answer"
        resp = MagicMock()
        resp.choices = [choice]
        sync_fn = MagicMock(return_value=resp)
        llm.completion = MagicMock(return_value=sync_fn)
        llm.metrics = {"accumulated_cost": 0.0}

        proc = LLMBatchProcessor(primary_llm=llm)
        results = await proc.process_batch([BatchRequest(prompt="x")])
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].response == "sync_answer"


# ---------------------------------------------------------------------------
# create_batch_processor
# ---------------------------------------------------------------------------

class TestCreateBatchProcessor:
    """Tests for the factory function."""

    def test_creates_processor(self):
        llm = MagicMock()
        proc = create_batch_processor(llm, batch_size=3, max_concurrent=5)
        assert isinstance(proc, LLMBatchProcessor)
        assert proc.batch_size == 3
        assert proc.max_concurrent == 5

    def test_with_backup_llms(self):
        primary = MagicMock()
        backup = MagicMock()
        proc = create_batch_processor(primary, backup_llms=[backup])
        assert proc.backup_llms == [backup]
