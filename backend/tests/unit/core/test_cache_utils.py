"""Tests for backend.core.cache.cache_utils."""

from __future__ import annotations

from types import SimpleNamespace

from backend.core.cache.cache_utils import merge_settings_with_cache


# ── merge_settings_with_cache ────────────────────────────────────────


class TestMergeSettingsWithCache:
    def _make_settings(self, val='base'):
        """Create a settings-like object with merge_with_config_settings."""
        s = SimpleNamespace(val=val)
        s.merge_with_config_settings = lambda: SimpleNamespace(val=val + '_merged')
        return s

    def test_merges_when_global_config_present(self):
        settings = self._make_settings('x')
        cache: dict = {}
        result = merge_settings_with_cache(
            'user1', settings, 'some-config', cache, 100.0
        )
        assert result.val == 'x_merged'
        assert 'user1' in cache

    def test_no_merge_when_global_config_none(self):
        settings = self._make_settings('y')
        cache: dict = {}
        result = merge_settings_with_cache('user2', settings, None, cache, 100.0)
        assert result.val == 'y'
        assert 'user2' in cache

    def test_cache_stores_timestamp(self):
        settings = self._make_settings('z')
        cache: dict = {}
        merge_settings_with_cache('u', settings, None, cache, 42.5)
        _, ts = cache['u']
        assert ts == 42.5

    def test_lru_eviction_at_256(self):
        cache: dict = {}
        # Fill cache to 256 entries
        for i in range(256):
            cache[f'user_{i}'] = (SimpleNamespace(), float(i))
        assert len(cache) == 256

        settings = self._make_settings('new')
        merge_settings_with_cache('new_user', settings, None, cache, 999.0)
        # One old entry should have been evicted, new one added
        assert 'new_user' in cache
        assert len(cache) == 256  # Still 256, one evicted + one added

    def test_existing_user_not_evicted(self):
        cache: dict = {}
        for i in range(256):
            cache[f'user_{i}'] = (SimpleNamespace(), float(i))

        # Update existing user — no eviction needed
        settings = self._make_settings('upd')
        merge_settings_with_cache('user_0', settings, None, cache, 999.0)
        assert len(cache) == 256


