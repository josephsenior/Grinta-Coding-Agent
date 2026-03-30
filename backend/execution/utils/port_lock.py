"""File-based port locking system for preventing race conditions in port allocation."""

from __future__ import annotations

import contextlib
import os
import random
import socket
import tempfile
import time
from typing import Any, Self, cast

from backend.core.logger import app_logger as logger

try:
    import fcntl  # type: ignore[import-not-found, unused-ignore]

    HAS_FCNTL = True
except ImportError:
    HAS_FCNTL = False
    fcntl = None  # type: ignore[assignment]


class PortLock:
    """File-based lock for a specific port to prevent race conditions."""

    def __init__(self, port: int, lock_dir: str | None = None) -> None:
        """Prepare filesystem lock state for the given port under the optional directory."""
        self.port = port
        self.lock_dir = lock_dir or os.path.join(
            tempfile.gettempdir(), "app_port_locks"
        )
        self.lock_file_path = os.path.join(self.lock_dir, f"port_{port}.lock")
        self.lock_fd: int | None = None
        self._locked = False
        os.makedirs(self.lock_dir, exist_ok=True)

    def _write_lock_info(self) -> None:
        """Write port information to the lock file."""
        if self.lock_fd is None:
            msg = "Lock file descriptor is not open"
            raise RuntimeError(msg)
        os.write(self.lock_fd, f"{self.port}\n".encode())
        os.fsync(self.lock_fd)

    def _acquire_with_fcntl(self, timeout: float) -> bool:
        """Acquire lock using fcntl (Unix systems).

        Args:
            timeout: Maximum time to wait for the lock.

        Returns:
            bool: True if lock was acquired, False otherwise.

        """
        if not HAS_FCNTL or fcntl is None:
            msg = "fcntl is not available on this platform"
            raise RuntimeError(msg)

        self.lock_fd = os.open(
            self.lock_file_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC
        )
        assert fcntl is not None
        fcntl_module = cast(Any, fcntl)
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                fcntl_module.flock(
                    self.lock_fd, fcntl_module.LOCK_EX | fcntl_module.LOCK_NB
                )
                self._locked = True
                self._write_lock_info()
                logger.debug("Acquired lock for port %s", self.port)
                return True
            except OSError:
                time.sleep(0.01)

        # Timeout reached, clean up
        if self.lock_fd:
            os.close(self.lock_fd)
            self.lock_fd = None

        return False

    def _acquire_without_fcntl(self, timeout: float) -> bool:
        """Acquire lock using file creation (Windows/fallback).

        Args:
            timeout: Maximum time to wait for the lock.

        Returns:
            bool: True if lock was acquired, False otherwise.

        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                self.lock_fd = os.open(
                    self.lock_file_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                )
                self._locked = True
                self._write_lock_info()
                logger.debug("Acquired lock for port %s", self.port)
                return True
            except OSError:
                time.sleep(0.01)

        return False

    def _cleanup_on_failure(self) -> None:
        """Clean up lock file descriptor on failure."""
        if self.lock_fd:
            with contextlib.suppress(OSError):
                os.close(self.lock_fd)
            self.lock_fd = None

    def acquire(self, timeout: float = 1.0) -> bool:
        """Acquire the lock for this port.

        Args:
            timeout: Maximum time to wait for the lock.

        Returns:
            bool: True if lock was acquired, False otherwise.

        """
        if self._locked:
            return True

        try:
            if HAS_FCNTL:
                return self._acquire_with_fcntl(timeout)
            return self._acquire_without_fcntl(timeout)
        except Exception as e:
            logger.debug("Failed to acquire lock for port %s: %s", self.port, e)
            self._cleanup_on_failure()
            return False

    def release(self) -> None:
        """Release the lock."""
        if self.lock_fd is None:
            return
        try:
            if HAS_FCNTL and fcntl is not None:
                fcntl_module = cast(Any, fcntl)
                fcntl_module.flock(self.lock_fd, fcntl_module.LOCK_UN)
            os.close(self.lock_fd)
            with contextlib.suppress(FileNotFoundError):
                os.unlink(self.lock_file_path)
            logger.debug("Released lock for port %s", self.port)
        except Exception as e:
            logger.warning("Error releasing lock for port %s: %s", self.port, e)
        finally:
            self.lock_fd = None
            self._locked = False

    def __enter__(self) -> Self:
        """Acquire the port lock when entering a context manager block."""
        if not self.acquire():
            msg = f"Could not acquire lock for port {self.port}"
            raise OSError(msg)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Release the port lock when leaving a context manager block."""
        self.release()

    @property
    def is_locked(self) -> bool:
        """Check if port is currently locked.

        Returns:
            True if port is locked, False otherwise

        """
        return self._locked


def find_available_port_with_lock(
    min_port: int = 30000,
    max_port: int = 39999,
    max_attempts: int = 20,
    bind_address: str = "0.0.0.0",  # nosec B104 - Safe: configurable bind address for port availability check
    lock_timeout: float = 1.0,
) -> tuple[int, PortLock] | None:
    """Find an available port and acquire a lock for it.

    This function combines file-based locking with port availability checking
    to prevent race conditions in multi-process scenarios.

    Args:
        min_port: Minimum port number to try
        max_port: Maximum port number to try
        max_attempts: Maximum number of ports to try
        bind_address: Address to bind to when checking availability
        lock_timeout: Timeout for acquiring port lock

    Returns:
        Tuple of (port, lock) if successful, None otherwise

    """
    rng = random.SystemRandom()
    random_attempts = min(max_attempts // 2, 10)
    for _ in range(random_attempts):
        port = rng.randint(min_port, max_port)
        lock = PortLock(port)
        if lock.acquire(timeout=lock_timeout):
            if _check_port_available(port, bind_address):
                logger.debug("Found and locked available port %s", port)
                return (port, lock)
            lock.release()
        time.sleep(0.001)
    remaining_attempts = max_attempts - random_attempts
    start_port = rng.randint(min_port, max_port - remaining_attempts)
    for i in range(remaining_attempts):
        port = start_port + i
        if port > max_port:
            port = min_port + (port - max_port - 1)
        lock = PortLock(port)
        if lock.acquire(timeout=lock_timeout):
            if _check_port_available(port, bind_address):
                logger.debug("Found and locked available port %s", port)
                return (port, lock)
            lock.release()
        time.sleep(0.001)
    logger.error(
        "Could not find and lock available port in range %s-%s after %s attempts",
        min_port,
        max_port,
        max_attempts,
    )
    return None


def _check_port_available(
    port: int,
    bind_address: str = "0.0.0.0",
) -> bool:  # nosec B104 - Safe: configurable bind address for port checking
    """Check if a port is available by trying to bind to it."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((bind_address, port))
        sock.close()
        return True
    except OSError:
        return False


def cleanup_stale_locks(max_age_seconds: int = 300) -> int:
    """Clean up stale lock files.

    Args:
        max_age_seconds: Maximum age of lock files before they're considered stale

    Returns:
        Number of lock files cleaned up

    """
    lock_dir = os.path.join(tempfile.gettempdir(), "app_port_locks")
    if not os.path.exists(lock_dir):
        return 0
    cleaned = 0
    current_time = time.time()
    try:
        for filename in os.listdir(lock_dir):
            if filename.startswith("port_") and filename.endswith(".lock"):
                lock_path = os.path.join(lock_dir, filename)
                try:
                    stat = os.stat(lock_path)
                    if current_time - stat.st_mtime > max_age_seconds:
                        os.unlink(lock_path)
                        cleaned += 1
                        logger.debug("Cleaned up stale lock file: %s", filename)
                except OSError:
                    pass
    except OSError:
        pass
    if cleaned > 0:
        logger.info("Cleaned up %s stale port lock files", cleaned)
    return cleaned
