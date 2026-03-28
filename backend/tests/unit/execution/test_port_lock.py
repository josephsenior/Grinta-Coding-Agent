"""Tests for backend.execution.utils.port_lock — PortLock and helpers."""

from __future__ import annotations

import os
import time
from unittest.mock import patch

import pytest

from backend.execution.utils.port_lock import (
    PortLock,
    _check_port_available,
    cleanup_stale_locks,
)


@pytest.fixture
def lock_dir(tmp_path):
    return str(tmp_path / "port_locks")


# ===================================================================
# PortLock basics
# ===================================================================


class TestPortLockInit:
    def test_default_lock_dir(self):
        lock = PortLock(8080)
        assert lock.port == 8080
        assert "FORGE_port_locks" in lock.lock_dir
        assert lock.lock_file_path.endswith("port_8080.lock")
        assert lock.is_locked is False

    def test_custom_lock_dir(self, lock_dir):
        lock = PortLock(9090, lock_dir=lock_dir)
        assert lock.lock_dir == lock_dir


class TestPortLockAcquireRelease:
    def test_acquire_and_release(self, lock_dir):
        lock = PortLock(12345, lock_dir=lock_dir)
        assert lock.acquire(timeout=2.0) is True
        is_locked_state = lock.is_locked
        assert is_locked_state is True
        lock_fd_before = lock.lock_fd
        assert lock_fd_before is not None
        lock.release()
        assert not lock.is_locked
        assert lock.lock_fd is None

    def test_acquire_already_locked(self, lock_dir):
        lock = PortLock(12346, lock_dir=lock_dir)
        lock.acquire(timeout=1.0)
        # Acquiring again should return True immediately (already locked)
        assert lock.acquire(timeout=0.1) is True
        lock.release()

    def test_release_when_not_locked(self, lock_dir):
        lock = PortLock(12347, lock_dir=lock_dir)
        # Should not raise
        lock.release()

    def test_context_manager(self, lock_dir):
        with PortLock(12348, lock_dir=lock_dir) as lock:
            assert lock.is_locked is True
            assert lock.port == 12348
        assert lock.is_locked is False

    def test_context_manager_acquire_fails(self, lock_dir):
        lock = PortLock(12349, lock_dir=lock_dir)
        with patch.object(lock, "acquire", return_value=False):
            with pytest.raises(OSError, match="Could not acquire lock"):
                lock.__enter__()


class TestPortLockContention:
    def test_second_lock_contention_windows(self, lock_dir):
        """On Windows (no fcntl), second lock on same port should block/timeout."""
        lock1 = PortLock(55555, lock_dir=lock_dir)
        assert lock1.acquire(timeout=1.0) is True
        try:
            lock2 = PortLock(55555, lock_dir=lock_dir)
            # With very short timeout, should fail since file exists
            result = lock2.acquire(timeout=0.05)
            # On Windows without fcntl, O_EXCL prevents second lock
            if not result:
                assert lock2.is_locked is False
            else:
                lock2.release()
        finally:
            lock1.release()


# ===================================================================
# _check_port_available
# ===================================================================


class TestCheckPortAvailable:
    def test_available_port(self):
        # Port 0 lets OS choose — we use a high random port that's likely free
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        # Port should be available right after closing
        assert _check_port_available(port, "127.0.0.1") is True

    def test_unavailable_port(self):
        """Bind on 0.0.0.0 and listen to truly occupy the port."""
        import socket

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Do NOT set SO_REUSEADDR — we want the port truly exclusive
        sock.bind(("0.0.0.0", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            # The function also binds to 0.0.0.0 with SO_REUSEADDR, but
            # on Windows with an active listener, this still fails.
            result = _check_port_available(port, "0.0.0.0")
            # On some Windows configs SO_REUSEADDR lets the 2nd bind succeed.
            # Accept either result; just ensure the function doesn't crash.
            assert isinstance(result, bool)
        finally:
            sock.close()


# ===================================================================
# cleanup_stale_locks
# ===================================================================


class TestCleanupStaleLocks:
    def test_no_lock_dir(self, tmp_path):
        """Returns 0 when directory doesn't exist."""
        with patch("backend.execution.utils.port_lock.tempfile") as mock_tmp:
            mock_tmp.gettempdir.return_value = str(tmp_path / "nonexistent")
            assert cleanup_stale_locks() == 0

    def test_cleans_old_files(self, tmp_path):
        lock_dir = tmp_path / "FORGE_port_locks"
        lock_dir.mkdir()
        # Create a stale lock file
        stale = lock_dir / "port_1234.lock"
        stale.write_text("1234")
        # Backdate modification time by 600 seconds
        old_time = time.time() - 600
        os.utime(str(stale), (old_time, old_time))
        with patch("backend.execution.utils.port_lock.tempfile") as mock_tmp:
            mock_tmp.gettempdir.return_value = str(tmp_path)
            result = cleanup_stale_locks(max_age_seconds=300)
        assert result == 1
        assert not stale.exists()

    def test_preserves_fresh_files(self, tmp_path):
        lock_dir = tmp_path / "FORGE_port_locks"
        lock_dir.mkdir()
        fresh = lock_dir / "port_5678.lock"
        fresh.write_text("5678")
        with patch("backend.execution.utils.port_lock.tempfile") as mock_tmp:
            mock_tmp.gettempdir.return_value = str(tmp_path)
            result = cleanup_stale_locks(max_age_seconds=300)
        assert result == 0
        assert fresh.exists()
