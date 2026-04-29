from __future__ import annotations

import time
from unittest.mock import patch

from backend.integrations.mcp import cache


def test_is_cacheable_respects_allowlist() -> None:
    with patch.object(cache, '_CACHEABLE_TOOLS', frozenset({'a', 'b'})):
        assert cache.is_cacheable('a') is True
        assert cache.is_cacheable('x') is False


def test_stable_args_json_drops_refresh_and_no_cache() -> None:
    out = cache._stable_args_json({'z': 1, 'refresh': True, 'a': 2, 'no_cache': True})
    assert out == '{"a":2,"z":1}'


def test_build_cache_key_uses_normalized_args() -> None:
    key = cache.build_cache_key('tool', {'b': 2, 'a': 1})
    assert key == 'tool::{"a":1,"b":2}'


def test_get_cached_miss_and_refresh_bypass() -> None:
    with patch.object(cache, '_CACHEABLE_TOOLS', frozenset({'t'})):
        cache.clear_cache()
        assert cache.get_cached('x', {}) is None
        assert cache.get_cached('t', {'refresh': True}) is None
        assert cache.get_cached('t', {'no_cache': True}) is None


def test_set_cache_and_get_cache_hit_and_ttl_expiry() -> None:
    with patch.object(cache, '_CACHEABLE_TOOLS', frozenset({'t'})):
        cache.clear_cache()
        cache.set_cache('t', {'q': 1}, {'content': 'ok'}, ttl=1)
        assert cache.get_cached('t', {'q': 1}) == {'content': 'ok'}

        key = cache.build_cache_key('t', {'q': 1})
        cache._tool_cache[key].expires_at = time.time() - 10
        assert cache.get_cached('t', {'q': 1}) is None


def test_set_cache_skips_errors_and_large_payloads() -> None:
    with (
        patch.object(cache, '_CACHEABLE_TOOLS', frozenset({'t'})),
        patch.object(cache, 'MAX_CACHE_ENTRY_BYTES', 10),
    ):
        cache.clear_cache()
        cache.set_cache('t', {'q': 1}, {'isError': True})
        assert cache.get_cached('t', {'q': 1}) is None
        cache.set_cache('t', {'q': 1}, {'content': {'isError': True}})
        assert cache.get_cached('t', {'q': 1}) is None
        cache.set_cache('t', {'q': 1}, {'content': 'x' * 100})
        assert cache.get_cached('t', {'q': 1}) is None


def test_clear_cache_prefix_and_all() -> None:
    with patch.object(cache, '_CACHEABLE_TOOLS', frozenset({'t', 'u'})):
        cache.clear_cache()
        cache.set_cache('t', {'a': 1}, {'content': '1'})
        cache.set_cache('u', {'a': 2}, {'content': '2'})
        removed = cache.clear_cache(prefix='t')
        assert removed == 1
        assert cache.get_cached('t', {'a': 1}) is None
        assert cache.get_cached('u', {'a': 2}) == {'content': '2'}
        removed_all = cache.clear_cache()
        assert removed_all >= 1

