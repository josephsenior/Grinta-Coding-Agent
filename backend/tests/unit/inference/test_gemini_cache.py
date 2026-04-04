"""Tests for GeminiCacheManager (singleton, hash-based context caching)."""

import unittest
from typing import Any, cast
from unittest.mock import MagicMock, patch

from backend.inference.gemini_cache import GeminiCacheManager


class TestGeminiCacheManager(unittest.TestCase):
    """Tests for GeminiCacheManager – singleton, _get_hash, get_or_create_cache, cleanup."""

    def setUp(self) -> None:
        # Reset singleton between tests
        GeminiCacheManager._instance = None
        self.manager = GeminiCacheManager()
        self.manager._caches = {}
        self.mock_client = MagicMock()

    def tearDown(self) -> None:
        GeminiCacheManager._instance = None

    # -- Singleton -----------------------------------------------------------

    def test_singleton(self):
        m1 = GeminiCacheManager()
        m2 = GeminiCacheManager()
        self.assertIs(m1, m2)

    def test_instance_has_caches_dict(self):
        self.assertIsInstance(self.manager._caches, dict)

    # -- _get_hash -----------------------------------------------------------

    def test_hash_deterministic(self):
        h1 = self.manager._get_hash('sys', [{'role': 'user', 'content': 'hi'}])
        h2 = self.manager._get_hash('sys', [{'role': 'user', 'content': 'hi'}])
        self.assertEqual(h1, h2)

    def test_hash_changes_with_system(self):
        h1 = self.manager._get_hash('a', [])
        h2 = self.manager._get_hash('b', [])
        self.assertNotEqual(h1, h2)

    def test_hash_changes_with_messages(self):
        h1 = self.manager._get_hash(None, [{'role': 'user', 'content': 'x'}])
        h2 = self.manager._get_hash(None, [{'role': 'user', 'content': 'y'}])
        self.assertNotEqual(h1, h2)

    def test_hash_none_system(self):
        h = self.manager._get_hash(None, [])
        self.assertIsInstance(h, str)
        self.assertTrue(h)

    # -- get_or_create_cache (cache hit) ------------------------------------

    def test_cache_hit_returns_name(self):
        """If hash already in _caches and Google confirms it, return name."""
        self.manager._caches['somehash'] = 'cache/abc'
        # Patch _get_hash to return our known hash
        cast(Any, self.manager)._get_hash = MagicMock(return_value='somehash')
        self.mock_client.caches.get.return_value = MagicMock()

        result = self.manager.get_or_create_cache(
            client=self.mock_client,
            model='gemini-1.5-pro',
            system_instruction='sys',
            messages=[],
        )
        self.assertEqual(result, 'cache/abc')
        self.mock_client.caches.get.assert_called_once_with(name='cache/abc')

    @patch('backend.inference.gemini_cache.time')
    def test_cache_hit_expired_recreates(self, mock_time):
        """If cached name is gone from Google, delete and create new."""
        mock_time.time.return_value = 1000000
        self.manager._caches['somehash'] = 'cache/old'
        cast(Any, self.manager)._get_hash = MagicMock(return_value='somehash')
        self.mock_client.caches.get.side_effect = Exception('not found')

        mock_cache_obj = MagicMock()
        mock_cache_obj.name = 'cache/new'
        self.mock_client.caches.create.return_value = mock_cache_obj

        result = self.manager.get_or_create_cache(
            client=self.mock_client,
            model='gemini-1.5-pro',
            system_instruction='sys',
            messages=[{'role': 'user', 'content': 'hi'}],
        )
        self.assertEqual(result, 'cache/new')
        self.assertEqual(self.manager._caches['somehash'], 'cache/new')

    # -- get_or_create_cache (cache miss) -----------------------------------

    @patch('backend.inference.gemini_cache.time')
    def test_cache_miss_creates_new(self, mock_time):
        """No existing cache → creates new one."""
        mock_time.time.return_value = 1000000
        mock_cache_obj = MagicMock()
        mock_cache_obj.name = 'cache/fresh'
        self.mock_client.caches.create.return_value = mock_cache_obj

        result = self.manager.get_or_create_cache(
            client=self.mock_client,
            model='gemini-1.5-pro',
            system_instruction='hello',
            messages=[{'role': 'user', 'content': 'test'}],
            ttl_minutes=30,
        )
        self.assertEqual(result, 'cache/fresh')
        self.mock_client.caches.create.assert_called_once()
        # Verify the call shape for new SDK
        call_kwargs = self.mock_client.caches.create.call_args.kwargs
        self.assertEqual(call_kwargs['config']['ttl'], '1800s')
        self.assertEqual(call_kwargs['config']['system_instruction'], 'hello')

    def test_create_failure_returns_none(self):
        """If creation fails, return None."""
        self.mock_client.caches.create.side_effect = RuntimeError('fail')

        result = self.manager.get_or_create_cache(
            client=self.mock_client,
            model='gemini-1.5-pro',
            system_instruction=None,
            messages=[],
        )
        self.assertIsNone(result)

    # -- message role mapping -----------------------------------------------

    @patch('backend.inference.gemini_cache.time')
    def test_role_mapping(self, mock_time):
        """User stays user, non-user becomes model."""
        mock_time.time.return_value = 1000000
        mock_cache_obj = MagicMock()
        mock_cache_obj.name = 'cache/role'
        self.mock_client.caches.create.return_value = mock_cache_obj

        messages = [
            {'role': 'user', 'content': 'q'},
            {'role': 'assistant', 'content': 'a'},
            {'role': 'system', 'content': 's'},
        ]
        self.manager.get_or_create_cache(
            client=self.mock_client,
            model='gemini-1.5-pro',
            system_instruction='sys',
            messages=messages,
        )
        call_kwargs = self.mock_client.caches.create.call_args.kwargs
        contents = call_kwargs.get('contents')
        roles = [c['role'] for c in contents]
        self.assertEqual(roles, ['user', 'model', 'model'])

    # -- cleanup_old_caches -------------------------------------------------

    def test_cleanup_lists_caches(self):
        self.mock_client.caches.list.return_value = [MagicMock(), MagicMock()]
        self.manager.cleanup_old_caches(self.mock_client)
        self.mock_client.caches.list.assert_called_once()

    def test_cleanup_handles_error(self):
        self.mock_client.caches.list.side_effect = Exception('network')
        # Should not raise
        self.manager.cleanup_old_caches(self.mock_client)

    # -- cache stores hash correctly ----------------------------------------

    @patch('backend.inference.gemini_cache.time')
    def test_cache_stores_hash(self, mock_time):
        mock_time.time.return_value = 1000000
        mock_cache_obj = MagicMock()
        mock_cache_obj.name = 'cache/stored'
        self.mock_client.caches.create.return_value = mock_cache_obj

        self.manager.get_or_create_cache(
            client=self.mock_client,
            model='gemini-1.5-pro',
            system_instruction='test',
            messages=[],
        )
        h = self.manager._get_hash('test', [])
        self.assertEqual(self.manager._caches[h], 'cache/stored')

    @patch('backend.inference.gemini_cache.time')
    def test_default_ttl(self, mock_time):
        mock_time.time.return_value = 1000000
        mock_cache_obj = MagicMock()
        mock_cache_obj.name = 'cache/ttl'
        self.mock_client.caches.create.return_value = mock_cache_obj

        self.manager.get_or_create_cache(
            client=self.mock_client,
            model='gemini-1.5-pro',
            system_instruction=None,
            messages=[],
        )
        # default ttl_minutes=60
        self.assertTrue(self.mock_client.caches.create.called)


if __name__ == '__main__':
    unittest.main()
