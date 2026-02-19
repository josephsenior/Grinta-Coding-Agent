"""Tests for backend.controller.idempotency — compute_idempotency_key, classify, middleware."""

from __future__ import annotations

import time
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from backend.controller.idempotency import (
    IdempotencyMiddleware,
    classify_idempotency,
    compute_idempotency_key,
)
from backend.events.action import (
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    MessageAction,
)


# ---------------------------------------------------------------------------
# compute_idempotency_key
# ---------------------------------------------------------------------------
class TestComputeIdempotencyKey:
    def test_deterministic(self):
        a = CmdRunAction(command="ls -la")
        k1 = compute_idempotency_key(a)
        k2 = compute_idempotency_key(a)
        assert k1 == k2

    def test_different_actions_different_keys(self):
        a = CmdRunAction(command="ls")
        b = CmdRunAction(command="pwd")
        assert compute_idempotency_key(a) != compute_idempotency_key(b)

    def test_sha256_hex(self):
        key = compute_idempotency_key(CmdRunAction(command="echo hi"))
        assert len(key) == 64  # sha256 hex digest
        assert all(c in "0123456789abcdef" for c in key)

    def test_ignores_volatile_fields(self):
        """Keys should be the same even if volatile fields differ."""
        a = CmdRunAction(command="ls")
        b = CmdRunAction(command="ls")
        a._id = 1
        b._id = 999
        assert compute_idempotency_key(a) == compute_idempotency_key(b)

    def test_non_dataclass_object(self):
        """Should still produce a key for non-dataclass objects."""
        obj = MagicMock()
        obj.__class__.__name__ = "CustomAction"
        key = compute_idempotency_key(obj)
        assert isinstance(key, str) and len(key) == 64


# ---------------------------------------------------------------------------
# classify_idempotency
# ---------------------------------------------------------------------------
class TestClassifyIdempotency:
    def test_idempotent_actions(self):
        assert classify_idempotency(FileReadAction(path="/x")) == "idempotent"
        assert classify_idempotency(MessageAction(content="hi")) == "idempotent"

    def test_non_idempotent_actions(self):
        assert (
            classify_idempotency(CmdRunAction(command="rm -rf /")) == "non-idempotent"
        )
        assert (
            classify_idempotency(FileEditAction(path="/x", content="y"))
            == "non-idempotent"
        )

    def test_unknown_action(self):
        @dataclass
        class WeirdAction:
            pass

        assert classify_idempotency(WeirdAction()) == "unknown"


# ---------------------------------------------------------------------------
# IdempotencyMiddleware
# ---------------------------------------------------------------------------
class TestIdempotencyMiddleware:
    def _make_ctx(self, action, blocked=False):
        ctx = MagicMock()
        ctx.action = action
        ctx.metadata = {}
        ctx.block = MagicMock()
        return ctx

    @pytest.mark.asyncio
    async def test_idempotent_action_always_passes(self):
        mw = IdempotencyMiddleware()
        ctx = self._make_ctx(FileReadAction(path="/x"))
        await mw.plan(ctx)
        ctx.block.assert_not_called()
        assert ctx.metadata["idempotency_class"] == "idempotent"

    @pytest.mark.asyncio
    async def test_non_idempotent_first_call_passes(self):
        mw = IdempotencyMiddleware()
        ctx = self._make_ctx(CmdRunAction(command="echo hi"))
        await mw.plan(ctx)
        ctx.block.assert_not_called()
        assert ctx.metadata["idempotency_key"]

    @pytest.mark.asyncio
    async def test_duplicate_non_idempotent_blocked(self):
        mw = IdempotencyMiddleware(ttl_seconds=60.0)
        action = CmdRunAction(command="echo hi")
        ctx1 = self._make_ctx(action)
        await mw.plan(ctx1)
        ctx1.block.assert_not_called()

        # Second call — same action — should be blocked
        ctx2 = self._make_ctx(action)
        await mw.plan(ctx2)
        ctx2.block.assert_called_once()

    @pytest.mark.asyncio
    async def test_expired_entry_not_blocked(self):
        mw = IdempotencyMiddleware(ttl_seconds=0.01)
        action = CmdRunAction(command="echo hi")
        ctx1 = self._make_ctx(action)
        await mw.plan(ctx1)
        ctx1.block.assert_not_called()

        time.sleep(0.02)  # Wait for TTL to expire

        ctx2 = self._make_ctx(action)
        await mw.plan(ctx2)
        ctx2.block.assert_not_called()

    @pytest.mark.asyncio
    async def test_cache_bounded(self):
        mw = IdempotencyMiddleware(max_cache_size=3, ttl_seconds=60.0)
        for i in range(5):
            ctx = self._make_ctx(CmdRunAction(command=f"echo {i}"))
            await mw.plan(ctx)
        assert len(mw._cache) <= 3

    @pytest.mark.asyncio
    async def test_evict_expired(self):
        mw = IdempotencyMiddleware(ttl_seconds=0.01)
        action = CmdRunAction(command="echo evict")
        ctx = self._make_ctx(action)
        await mw.plan(ctx)
        assert len(mw._cache) == 1

        time.sleep(0.02)
        mw._evict_expired(time.monotonic())
        assert not mw._cache

    @pytest.mark.asyncio
    async def test_metadata_populated(self):
        mw = IdempotencyMiddleware()
        ctx = self._make_ctx(CmdRunAction(command="ls"))
        await mw.plan(ctx)
        assert "idempotency_key" in ctx.metadata
        assert "idempotency_class" in ctx.metadata
        assert ctx.metadata["idempotency_class"] == "non-idempotent"
