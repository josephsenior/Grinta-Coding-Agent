"""Tests for backend.engines.auditor.tools.file_cache — FileCache 2-tier caching."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True, scope="module")
def _patch_engines_init():
    """Prevent heavy engine imports (browsergym etc.) during file_cache tests."""
    # Pre-populate sys.modules to bypass costly import chains
    engines_mod = type(sys)("backend.engines")
    engines_mod.__path__ = []
    auditor_mod = type(sys)("backend.engines.auditor")
    auditor_mod.__path__ = []
    tools_mod = type(sys)("backend.engines.auditor.tools")
    tools_mod.__path__ = []

    saved = {}
    for name in (
        "backend.engines",
        "backend.engines.auditor",
        "backend.engines.auditor.tools",
    ):
        saved[name] = sys.modules.get(name)

    sys.modules.setdefault("backend.engines", engines_mod)
    sys.modules.setdefault("backend.engines.auditor", auditor_mod)
    sys.modules.setdefault("backend.engines.auditor.tools", tools_mod)

    yield

    for name, old in saved.items():
        if old is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = old


from backend.engines.auditor.tools.file_cache import FileCache


@pytest.fixture
def cache():
    """FileCache with distributed cache disabled."""
    with patch(
        "backend.engines.auditor.tools.file_cache.create_distributed_cache",
        return_value=None,
    ):
        return FileCache(
            max_cache_size=5,
            ttl_seconds=60,
            enable_mtime_check=False,
            use_distributed=False,
        )


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------
class TestInit:
    def test_defaults(self, cache):
        assert cache.max_cache_size == 5
        assert cache.distributed_cache is None
        assert cache.stats["hits"] == 0

    def test_with_distributed(self):
        mock_dc = MagicMock()
        with patch(
            "backend.engines.auditor.tools.file_cache.create_distributed_cache",
            return_value=mock_dc,
        ):
            c = FileCache(use_distributed=True)
            assert c.distributed_cache is mock_dc


# ---------------------------------------------------------------------------
# Content caching (local L1)
# ---------------------------------------------------------------------------
class TestContentCache:
    def test_cache_and_get(self, cache):
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as f:
            f.write(b"print('hi')")
            f.flush()
            cache.cache_content(f.name, "print('hi')")
            assert cache.get_content(f.name) == "print('hi')"
            assert cache.stats["hits"] == 1
        os.unlink(f.name)

    def test_miss(self, cache):
        assert cache.get_content("/nonexistent") is None
        assert cache.stats["misses"] >= 1

    def test_ttl_expiration(self):
        with patch(
            "backend.engines.auditor.tools.file_cache.create_distributed_cache",
            return_value=None,
        ):
            c = FileCache(
                ttl_seconds=0, enable_mtime_check=False, use_distributed=False
            )
        # Manually insert expired entry
        c.content_cache["/test.py"] = (
            "content",
            datetime.now() - timedelta(seconds=10),
            0.0,
        )
        assert c.get_content("/test.py") is None

    def test_mtime_invalidation(self):
        with patch(
            "backend.engines.auditor.tools.file_cache.create_distributed_cache",
            return_value=None,
        ):
            c = FileCache(
                ttl_seconds=300, enable_mtime_check=True, use_distributed=False
            )
        with tempfile.NamedTemporaryFile(delete=False, suffix=".py") as f:
            f.write(b"v1")
            f.flush()
            c.cache_content(f.name, "v1")
            # Modify file to change mtime
            time.sleep(0.05)
            with open(f.name, "w", encoding="utf-8") as fh:
                fh.write("v2")
            # Now local check should return None (mtime changed)
            assert c.get_content(f.name) is None
        os.unlink(f.name)


# ---------------------------------------------------------------------------
# Symbol / structure caching
# ---------------------------------------------------------------------------
class TestSymbolAndStructureCache:
    def test_symbol_cache(self, cache):
        symbols = {"MyClass": {"line": 10}, "my_func": {"line": 20}}
        cache.cache_symbols("/a.py", symbols)
        assert cache.get_symbols("/a.py") == symbols
        assert cache.stats["hits"] == 1

    def test_symbol_miss(self, cache):
        assert cache.get_symbols("/nope") is None
        assert cache.stats["misses"] == 1

    def test_structure_cache(self, cache):
        struct = {"classes": ["Foo"], "functions": ["bar"]}
        cache.cache_structure("/b.py", struct)
        assert cache.get_structure("/b.py") == struct

    def test_structure_miss(self, cache):
        assert cache.get_structure("/nope") is None


# ---------------------------------------------------------------------------
# LRU eviction
# ---------------------------------------------------------------------------
class TestLRUEviction:
    def test_evicts_lru_on_overflow(self, cache):
        for i in range(6):  # max_cache_size = 5
            path = f"/file{i}.py"
            cache.content_cache[path] = (f"content{i}", datetime.now(), 0.0)
            cache.access_times[path] = datetime.now()
            if i == 0:
                # Make file0 the oldest access
                cache.access_times[path] = datetime(2000, 1, 1)
        # The next cache_content triggers eviction
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
            f.flush()
            cache.cache_content(f.name, "newest")
        os.unlink(f.name)
        assert cache.stats["evictions"] >= 1

    def test_evict_empty_access_times(self, cache):
        # Should not raise
        cache._evict_lru()


# ---------------------------------------------------------------------------
# Invalidation / clear
# ---------------------------------------------------------------------------
class TestInvalidation:
    def test_invalidate_removes_all(self, cache):
        cache.content_cache["/x.py"] = ("c", datetime.now(), 0.0)
        cache.symbol_cache["/x.py"] = {"s": {}}
        cache.structure_cache["/x.py"] = {"f": []}
        cache.access_times["/x.py"] = datetime.now()
        cache._invalidate_file("/x.py")
        assert "/x.py" not in cache.content_cache
        assert "/x.py" not in cache.symbol_cache
        assert "/x.py" not in cache.structure_cache
        assert cache.stats["invalidations"] == 1

    def test_clear(self, cache):
        cache.content_cache["/a.py"] = ("c", datetime.now(), 0.0)
        cache.symbol_cache["/a.py"] = {}
        cache.clear()
        assert not cache.content_cache
        assert not cache.symbol_cache


# ---------------------------------------------------------------------------
# get_stats
# ---------------------------------------------------------------------------
class TestStats:
    def test_stats_structure(self, cache):
        cache.stats["hits"] = 10
        cache.stats["misses"] = 5
        cache.content_cache["/a.py"] = ("", datetime.now(), 0.0)
        cache.symbol_cache["/b.py"] = {}
        cache.structure_cache["/c.py"] = {}
        stats = cache.get_stats()
        assert stats["cached_files"] == 1
        assert stats["cached_symbols"] == 1
        assert stats["cached_structures"] == 1
        assert stats["total_requests"] == 15
        assert abs(stats["hit_rate_percent"] - 66.7) < 0.1

    def test_stats_zero_requests(self, cache):
        stats = cache.get_stats()
        assert stats["hit_rate_percent"] == 0


# ---------------------------------------------------------------------------
# Distributed cache L2 path (mocked)
# ---------------------------------------------------------------------------
class TestDistributedCachePath:
    @pytest.fixture
    def dist_cache(self):
        mock_dc = MagicMock()
        with patch(
            "backend.engines.auditor.tools.file_cache.create_distributed_cache",
            return_value=mock_dc,
        ):
            c = FileCache(enable_mtime_check=False, use_distributed=True)
            yield c

    def test_check_distributed_hit(self, dist_cache):
        dist_cache.distributed_cache.get.return_value = (
            "cached_content",
            datetime.now().isoformat(),
            0.0,
        )
        result = dist_cache._check_distributed_cache("/test.py")
        assert result == "cached_content"
        assert dist_cache.stats["distributed_hits"] == 1

    def test_check_distributed_miss(self, dist_cache):
        dist_cache.distributed_cache.get.return_value = None
        result = dist_cache._check_distributed_cache("/test.py")
        assert result is None
        assert dist_cache.stats["distributed_misses"] == 1

    def test_check_distributed_error(self, dist_cache):
        dist_cache.distributed_cache.get.side_effect = Exception("conn error")
        result = dist_cache._check_distributed_cache("/test.py")
        assert result is None

    def test_validate_mtime_match(self, dist_cache):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
            f.flush()
            mtime = os.path.getmtime(f.name)
            dist_cache.enable_mtime_check = True
            assert dist_cache._validate_mtime(f.name, mtime) is True
        os.unlink(f.name)

    def test_validate_mtime_mismatch(self, dist_cache):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"x")
            f.flush()
            dist_cache.enable_mtime_check = True
            assert dist_cache._validate_mtime(f.name, 0.0) is False
        os.unlink(f.name)

    def test_validate_mtime_file_gone(self, dist_cache):
        dist_cache.enable_mtime_check = True
        assert dist_cache._validate_mtime("/gone/file.py", 123.0) is False

    def test_get_content_l2_fallback(self, dist_cache):
        """Miss L1, hit L2."""
        dist_cache.distributed_cache.get.return_value = (
            "from_redis",
            datetime.now().isoformat(),
            0.0,
        )
        result = dist_cache.get_content("/test.py")
        assert result == "from_redis"

    def test_cache_content_writes_to_distributed(self, dist_cache):
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"data")
            f.flush()
            dist_cache.cache_content(f.name, "data")
            dist_cache.distributed_cache.set.assert_called_once()
        os.unlink(f.name)
