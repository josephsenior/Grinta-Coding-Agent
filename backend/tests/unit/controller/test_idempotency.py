"""Unit tests for backend.controller.idempotency — Idempotency tagging and dedup."""

import time
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from backend.controller.idempotency import (
    IdempotencyMiddleware,
    classify_idempotency,
    compute_idempotency_key,
)
from backend.controller.tool_pipeline import ToolInvocationContext
from backend.events.action import (
    AgentThinkAction,
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
    MessageAction,
)


# ---------------------------------------------------------------------------
# Idempotency key computation
# ---------------------------------------------------------------------------


class TestComputeIdempotencyKey:
    def test_same_action_same_key(self):
        action1 = CmdRunAction(command="ls -la")
        action2 = CmdRunAction(command="ls -la")
        assert compute_idempotency_key(action1) == compute_idempotency_key(action2)

    def test_different_command_different_key(self):
        action1 = CmdRunAction(command="ls -la")
        action2 = CmdRunAction(command="pwd")
        assert compute_idempotency_key(action1) != compute_idempotency_key(action2)

    def test_different_action_type_different_key(self):
        cmd_action = CmdRunAction(command="echo test")
        think_action = AgentThinkAction(thought="echo test")
        assert compute_idempotency_key(cmd_action) != compute_idempotency_key(
            think_action
        )

    def test_file_write_same_content_same_key(self):
        action1 = FileWriteAction(path="test.py", content="print('hello')")
        action2 = FileWriteAction(path="test.py", content="print('hello')")
        assert compute_idempotency_key(action1) == compute_idempotency_key(action2)

    def test_file_write_different_content_different_key(self):
        action1 = FileWriteAction(path="test.py", content="print('hello')")
        action2 = FileWriteAction(path="test.py", content="print('goodbye')")
        assert compute_idempotency_key(action1) != compute_idempotency_key(action2)

    def test_volatile_fields_excluded(self):
        """Volatile fields like _id, _timestamp should not affect key."""
        action1 = CmdRunAction(command="ls")
        action2 = CmdRunAction(command="ls")

        # Simulate volatile fields being set
        action1._id = 1
        action1._timestamp = "2024-01-01T00:00:00"
        action2._id = 999
        action2._timestamp = "2024-12-31T23:59:59"

        # Keys should still match because volatile fields are excluded
        assert compute_idempotency_key(action1) == compute_idempotency_key(action2)

    def test_key_is_deterministic(self):
        """Same action should always produce the same key."""
        action = CmdRunAction(command="echo test")
        key1 = compute_idempotency_key(action)
        key2 = compute_idempotency_key(action)
        key3 = compute_idempotency_key(action)
        assert key1 == key2 == key3

    def test_key_is_hexadecimal_sha256(self):
        """Key should be a 64-character hex string (SHA256)."""
        action = CmdRunAction(command="test")
        key = compute_idempotency_key(action)
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)


# ---------------------------------------------------------------------------
# Idempotency classification
# ---------------------------------------------------------------------------


class TestClassifyIdempotency:
    @pytest.mark.parametrize(
        "action",
        [
            FileReadAction(path="test.txt"),
            AgentThinkAction(thought="Thinking..."),
            MessageAction(content="Status update"),
        ],
    )
    def test_idempotent_actions(self, action):
        assert classify_idempotency(action) == "idempotent"

    @pytest.mark.parametrize(
        "action",
        [
            CmdRunAction(command="ls"),
            FileWriteAction(path="test.py", content="code"),
            FileEditAction(path="app.py"),
        ],
    )
    def test_non_idempotent_actions(self, action):
        assert classify_idempotency(action) == "non-idempotent"

    def test_unknown_action_type(self):
        """Unknown action types should be classified as 'unknown'."""

        @dataclass
        class CustomAction:
            custom_field: str

        action = CustomAction(custom_field="test")
        assert classify_idempotency(action) == "unknown"


# ---------------------------------------------------------------------------
# Middleware blocking logic
# ---------------------------------------------------------------------------


def _mock_ctx(action):
    """Create a mock ToolInvocationContext for testing."""
    return ToolInvocationContext(
        controller=MagicMock(),
        action=action,
        state=MagicMock(),
    )


class TestIdempotencyMiddleware:
    @pytest.mark.asyncio
    async def test_idempotent_action_always_allowed(self):
        middleware = IdempotencyMiddleware()
        action = FileReadAction(path="test.txt")
        ctx = _mock_ctx(action)

        # Should allow multiple executions
        await middleware.plan(ctx)
        assert not ctx.blocked

        await middleware.plan(ctx)
        assert not ctx.blocked

        await middleware.plan(ctx)
        assert not ctx.blocked

    @pytest.mark.asyncio
    async def test_non_idempotent_action_blocked_on_duplicate(self):
        middleware = IdempotencyMiddleware(ttl_seconds=10.0)
        action = CmdRunAction(command="rm -rf /tmp/test")
        ctx1 = _mock_ctx(action)

        # First execution should pass
        await middleware.plan(ctx1)
        assert not ctx1.blocked

        # Duplicate execution should be blocked
        ctx2 = _mock_ctx(action)
        await middleware.plan(ctx2)
        assert ctx2.blocked
        assert "duplicate_action" in ctx2.block_reason

    @pytest.mark.asyncio
    async def test_different_non_idempotent_actions_both_allowed(self):
        middleware = IdempotencyMiddleware()
        action1 = CmdRunAction(command="ls")
        action2 = CmdRunAction(command="pwd")

        ctx1 = _mock_ctx(action1)
        ctx2 = _mock_ctx(action2)

        await middleware.plan(ctx1)
        assert not ctx1.blocked

        await middleware.plan(ctx2)
        assert not ctx2.blocked

    @pytest.mark.asyncio
    async def test_ttl_expiration_allows_reexecution(self):
        middleware = IdempotencyMiddleware(ttl_seconds=0.1)
        action = CmdRunAction(command="test")

        # First execution
        ctx1 = _mock_ctx(action)
        await middleware.plan(ctx1)
        assert not ctx1.blocked

        # Immediate duplicate should be blocked
        ctx2 = _mock_ctx(action)
        await middleware.plan(ctx2)
        assert ctx2.blocked

        # Wait for TTL to expire
        time.sleep(0.15)

        # Should now be allowed
        ctx3 = _mock_ctx(action)
        await middleware.plan(ctx3)
        assert not ctx3.blocked

    @pytest.mark.asyncio
    async def test_metadata_populated(self):
        middleware = IdempotencyMiddleware()
        action = CmdRunAction(command="test")
        ctx = _mock_ctx(action)

        await middleware.plan(ctx)

        # Metadata should be populated
        assert "idempotency_key" in ctx.metadata
        assert "idempotency_class" in ctx.metadata
        assert ctx.metadata["idempotency_class"] == "non-idempotent"
        assert isinstance(ctx.metadata["idempotency_key"], str)
        assert len(ctx.metadata["idempotency_key"]) == 64


# ---------------------------------------------------------------------------
# LRU cache behavior
# ---------------------------------------------------------------------------


class TestIdempotencyLRUCache:
    @pytest.mark.asyncio
    async def test_cache_size_limit(self):
        middleware = IdempotencyMiddleware(max_cache_size=3, ttl_seconds=60.0)

        # Execute 4 different actions
        for i in range(4):
            action = CmdRunAction(command=f"echo {i}")
            ctx = _mock_ctx(action)
            await middleware.plan(ctx)

        # Cache should only hold 3 entries (oldest evicted)
        assert len(middleware._cache) == 3

    @pytest.mark.asyncio
    async def test_oldest_entry_evicted_on_overflow(self):
        middleware = IdempotencyMiddleware(max_cache_size=2, ttl_seconds=60.0)

        action1 = CmdRunAction(command="first")
        action2 = CmdRunAction(command="second")
        action3 = CmdRunAction(command="third")

        # Execute first two
        for action in [action1, action2]:
            ctx = _mock_ctx(action)
            await middleware.plan(ctx)

        # Execute third - should evict first
        ctx3 = _mock_ctx(action3)
        await middleware.plan(ctx3)

        # action1 should no longer be blocked (evicted from cache)
        ctx1_retry = _mock_ctx(action1)
        await middleware.plan(ctx1_retry)
        assert not ctx1_retry.blocked

        # Note: In the current implementation, action2 may also be evicted
        # depending on LRU ordering. The main test is that action1 was evicted.


# ---------------------------------------------------------------------------
# TTL eviction
# ---------------------------------------------------------------------------


class TestTTLEviction:
    @pytest.mark.asyncio
    async def test_expired_entries_evicted_automatically(self):
        middleware = IdempotencyMiddleware(ttl_seconds=0.1)

        # Add an entry
        action = CmdRunAction(command="test")
        ctx1 = _mock_ctx(action)
        await middleware.plan(ctx1)
        assert len(middleware._cache) == 1

        # Wait for expiration
        time.sleep(0.15)

        # Add a new entry - should trigger eviction
        new_action = CmdRunAction(command="new")
        ctx2 = _mock_ctx(new_action)
        await middleware.plan(ctx2)

        # Original entry should have been evicted
        assert len(middleware._cache) == 1
        # Only the new action's key should be in cache
        new_key = compute_idempotency_key(new_action)
        assert new_key in middleware._cache
