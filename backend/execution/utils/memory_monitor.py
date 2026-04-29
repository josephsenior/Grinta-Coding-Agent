"""Memory monitoring utilities for the runtime."""

import threading
import time

import psutil

from backend.core.logger import app_logger as logger


class LogStream:
    """Stream-like object that redirects writes to a logger."""

    def write(self, message: str) -> None:
        """Write memory usage message to logger.

        Args:
            message: Memory usage message to log

        """
        if message and (not message.isspace()):
            logger.info('[Memory usage] %s', message.strip())

    def flush(self) -> None:
        """Flush log stream (no-op for logger redirect)."""


class MemoryMonitor:
    """Threaded helper that watches process RSS and logs threshold breaches."""

    def __init__(self, enable: bool = False) -> None:
        """Memory monitor for the runtime."""
        self._monitoring_thread: threading.Thread | None = None
        self._stop_monitoring = threading.Event()
        self.log_stream = LogStream()
        self.enable = enable
        self._sample_interval = 0.1
        self._max_runtime_seconds = 3600

    def start_monitoring(self) -> None:
        """Start monitoring memory usage."""
        if not self.enable:
            return
        if self._monitoring_thread is not None:
            return

        def monitor_process() -> None:
            """Sample RSS (incl. children) using psutil and log via LogStream."""
            try:
                proc = psutil.Process()
                samples: list[float] = []
                deadline = time.monotonic() + self._max_runtime_seconds
                while not self._stop_monitoring.is_set() and time.monotonic() < deadline:
                    try:
                        rss = proc.memory_info().rss
                        for child in proc.children(recursive=True):
                            try:
                                rss += child.memory_info().rss
                            except (psutil.NoSuchProcess, psutil.AccessDenied):
                                continue
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        break
                    rss_mib = rss / (1024 * 1024)
                    samples.append(rss_mib)
                    self.log_stream.write(f'{rss_mib:.1f} MiB')
                    if self._stop_monitoring.wait(self._sample_interval):
                        break
                logger.info('Memory usage across time: %s', samples)
            except Exception as e:
                logger.error('Memory monitoring failed: %s', e)

        self._monitoring_thread = threading.Thread(target=monitor_process, daemon=True)
        self._monitoring_thread.start()
        logger.info('Memory monitoring started')

    def stop_monitoring(self) -> None:
        """Stop monitoring memory usage."""
        if not self.enable:
            return
        if self._monitoring_thread is not None:
            self._stop_monitoring.set()
            self._monitoring_thread = None
            logger.info('Memory monitoring stopped')
