"""Tests for backend.mcp.cache — in-process caching for MCP tool results."""

from __future__ import annotations

import json
import time
from unittest.mock import patch


from backend.mcp.cache import (
    CacheEntry,
    _stable_args_json,
    _tool_cache,
    build_cache_key,
    clear_cache,
    get_cached,
    is_cacheable,
    set_cache,
)


# ── CacheEntry dataclass ───────────────────────────────────────────────


class TestCacheEntry:
    """Test CacheEntry dataclass structure."""

    def test_create_entry(self):
        """Test creating a cache entry."""
        entry = CacheEntry(
            value={"result": "data"}, expires_at=time.time() + 60, size=100
        )
        assert entry.value == {"result": "data"}
        assert entry.expires_at > time.time()
        assert entry.size == 100

    def test_entry_is_dataclass(self):
        """Test CacheEntry is a dataclass."""
        entry = CacheEntry(value={}, expires_at=0.0, size=0)
        assert hasattr(entry, "__dataclass_fields__")


# ── is_cacheable function ──────────────────────────────────────────────


class TestIsCacheable:
    """Test tool name cacheable check."""

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"search_components", "get_component"})
    def test_returns_true_for_cacheable_tool(self):
        """Test returns True for tools in cacheable list."""
        assert is_cacheable("search_components") is True
        assert is_cacheable("get_component") is True

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"search_components"})
    def test_returns_false_for_non_cacheable_tool(self):
        """Test returns False for tools not in cacheable list."""
        assert is_cacheable("other_tool") is False
        assert is_cacheable("unknown") is False


# ── _stable_args_json function ─────────────────────────────────────────


class TestStableArgsJson:
    """Test argument serialization with filtering."""

    def test_serializes_simple_args(self):
        """Test serializes simple arguments deterministically."""
        args = {"query": "test", "limit": 10}
        result = _stable_args_json(args)
        assert json.loads(result) == {"query": "test", "limit": 10}

    def test_sorts_keys(self):
        """Test keys are sorted for deterministic output."""
        args = {"z": 1, "a": 2, "m": 3}
        result = _stable_args_json(args)
        # JSON should have sorted keys
        assert result == '{"a":2,"m":3,"z":1}'

    def test_filters_refresh_flag(self):
        """Test filters out 'refresh' flag."""
        args = {"query": "test", "refresh": True}
        result = _stable_args_json(args)
        parsed = json.loads(result)
        assert "refresh" not in parsed
        assert parsed == {"query": "test"}

    def test_filters_no_cache_flag(self):
        """Test filters out 'no_cache' flag."""
        args = {"query": "test", "no_cache": True}
        result = _stable_args_json(args)
        parsed = json.loads(result)
        assert "no_cache" not in parsed
        assert parsed == {"query": "test"}

    def test_filters_both_flags(self):
        """Test filters both flags together."""
        args = {"query": "test", "refresh": True, "no_cache": False}
        result = _stable_args_json(args)
        assert json.loads(result) == {"query": "test"}

    def test_handles_nested_structures(self):
        """Test handles nested dicts and lists."""
        args = {"filter": {"name": "test"}, "ids": [1, 2, 3]}
        result = _stable_args_json(args)
        parsed = json.loads(result)
        assert parsed["filter"] == {"name": "test"}
        assert parsed["ids"] == [1, 2, 3]

    def test_handles_unicode(self):
        """Test handles unicode characters."""
        args = {"text": "Hello 世界 🚀"}
        result = _stable_args_json(args)
        parsed = json.loads(result)
        assert parsed["text"] == "Hello 世界 🚀"


# ── build_cache_key function ───────────────────────────────────────────


class TestBuildCacheKey:
    """Test cache key construction."""

    def test_builds_key_with_tool_name(self):
        """Test key includes tool name."""
        key = build_cache_key("search_components", {"query": "test"})
        assert key.startswith("search_components::")

    def test_builds_key_with_args(self):
        """Test key includes serialized args."""
        key = build_cache_key("tool", {"arg": "value"})
        assert '{"arg":"value"}' in key

    def test_same_args_produce_same_key(self):
        """Test same args produce identical key."""
        key1 = build_cache_key("tool", {"a": 1, "b": 2})
        key2 = build_cache_key("tool", {"b": 2, "a": 1})  # different order
        assert key1 == key2

    def test_different_args_produce_different_keys(self):
        """Test different args produce different keys."""
        key1 = build_cache_key("tool", {"query": "test1"})
        key2 = build_cache_key("tool", {"query": "test2"})
        assert key1 != key2


# ── get_cached function ────────────────────────────────────────────────


class TestGetCached:
    """Test cache retrieval."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_cache()

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"test_tool"})
    def test_returns_nonewhen_empty(self):
        """Test returns None when cache is empty."""
        result = get_cached("test_tool", {"query": "test"})
        assert result is None

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"test_tool"})
    def test_returns_cached_value(self):
        """Test returns cached value when present and valid."""
        args = {"query": "test"}
        set_cache("test_tool", args, {"result": "data"}, ttl=60)

        result = get_cached("test_tool", args)
        assert result == {"result": "data"}

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"test_tool"})
    def test_returns_none_for_expired_entry(self):
        """Test returns None for expired entries."""
        args = {"query": "test"}
        # Set with negative TTL (already expired)
        set_cache("test_tool", args, {"result": "data"}, ttl=-1)
        time.sleep(0.1)  # Ensure expiry

        result = get_cached("test_tool", args)
        assert result is None

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"test_tool"})
    def test_returns_none_for_non_cacheable_tool(self):
        """Test returns None for non-cacheable tools."""
        result = get_cached("other_tool", {"query": "test"})
        assert result is None

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"test_tool"})
    def test_returns_none_with_refresh_flag(self):
        """Test returns None when refresh flag is set."""
        args = {"query": "test"}
        set_cache("test_tool", args, {"result": "data"})

        result = get_cached("test_tool", {"query": "test", "refresh": True})
        assert result is None

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"test_tool"})
    def test_returns_none_with_no_cache_flag(self):
        """Test returns None when no_cache flag is set."""
        args = {"query": "test"}
        set_cache("test_tool", args, {"result": "data"})

        result = get_cached("test_tool", {"query": "test", "no_cache": True})
        assert result is None


# ── set_cache function ─────────────────────────────────────────────────


class TestSetCache:
    """Test cache storage."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_cache()

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"test_tool"})
    def test_stores_result_in_cache(self):
        """Test stores result in cache."""
        args = {"query": "test"}
        result_dict = {"result": "data"}
        set_cache("test_tool", args, result_dict)

        # Verify stored
        cached = get_cached("test_tool", args)
        assert cached == result_dict

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"test_tool"})
    def test_does_not_cache_non_cacheable_tool(self):
        """Test does not cache non-cacheable tools."""
        set_cache("other_tool", {"query": "test"}, {"result": "data"})

        # Should not be in cache
        assert not _tool_cache

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"test_tool"})
    def test_does_not_cache_with_refresh_flag(self):
        """Test does not cache when refresh flag is set."""
        set_cache("test_tool", {"query": "test", "refresh": True}, {"result": "data"})

        assert not _tool_cache

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"test_tool"})
    def test_does_not_cache_with_no_cache_flag(self):
        """Test does not cache when no_cache flag is set."""
        set_cache("test_tool", {"query": "test", "no_cache": True}, {"result": "data"})

        assert not _tool_cache

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"test_tool"})
    def test_does_not_cache_errors(self):
        """Test does not cache results with isError flag."""
        set_cache("test_tool", {"query": "test"}, {"isError": True, "error": "failed"})

        assert not _tool_cache

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"test_tool"})
    def test_does_not_cache_nested_errors(self):
        """Test does not cache results with nested isError in content."""
        set_cache("test_tool", {"query": "test"}, {"content": {"isError": True}})

        assert not _tool_cache

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"test_tool"})
    @patch("backend.mcp.cache.MAX_CACHE_ENTRY_BYTES", 50)
    def test_does_not_cache_large_payloads(self):
        """Test does not cache payloads exceeding size limit."""
        large_result = {"data": "x" * 1000}  # Large payload
        set_cache("test_tool", {"query": "test"}, large_result)

        assert not _tool_cache

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"test_tool"})
    def test_sets_expiry_with_ttl(self):
        """Test sets expiry timestamp based on TTL."""
        args = {"query": "test"}
        result_dict = {"result": "data"}
        before_time = time.time()
        set_cache("test_tool", args, result_dict, ttl=30)
        after_time = time.time()

        key = build_cache_key("test_tool", args)
        entry = _tool_cache[key]
        # Expiry should be current time + 30 seconds
        assert before_time + 30 <= entry.expires_at <= after_time + 30


# ── clear_cache function ───────────────────────────────────────────────


class TestClearCache:
    """Test cache clearing."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_cache()

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"tool1", "tool2"})
    def test_clears_all_entries(self):
        """Test clears all cache entries."""
        set_cache("tool1", {"a": 1}, {"result": "1"})
        set_cache("tool2", {"b": 2}, {"result": "2"})

        count = clear_cache()

        assert count == 2
        assert not _tool_cache

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"tool1", "tool2"})
    def test_clears_entries_by_prefix(self):
        """Test clears only entries matching prefix."""
        set_cache("tool1", {"a": 1}, {"result": "1"})
        set_cache("tool2", {"b": 2}, {"result": "2"})

        count = clear_cache(prefix="tool1")

        assert count == 1
        # tool2 entry should remain
        assert get_cached("tool2", {"b": 2}) == {"result": "2"}
        assert get_cached("tool1", {"a": 1}) is None

    def test_returns_zero_when_empty(self):
        """Test returns 0 when cache is already empty."""
        count = clear_cache()
        assert count == 0

    @patch("backend.mcp.cache._CACHEABLE_TOOLS", {"some_tool"})
    def test_clears_with_non_matching_prefix(self):
        """Test clears nothing when prefix doesn't match."""
        set_cache("some_tool", {"x": 1}, {"result": "data"})

        count = clear_cache(prefix="other_tool")

        assert count == 0
        # Entry should still exist
        assert get_cached("some_tool", {"x": 1}) == {"result": "data"}
