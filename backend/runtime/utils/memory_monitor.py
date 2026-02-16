"""Memory monitoring utilities for the runtime."""

import threading

from memory_profiler import memory_usage

from backend.core.logger import FORGE_logger as logger


class LogStream:
    """Stream-like object that redirects writes to a logger."""

    def write(self, message: str) -> None:
        """Write memory usage message to logger.

        Args:
            message: Memory usage message to log

        """
        if message and (not message.isspace()):
            logger.info("[Memory usage] %s", message.strip())

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

    def start_monitoring(self) -> None:
        """Start monitoring memory usage."""
        if not self.enable:
            return
        if self._monitoring_thread is not None:
            return

        def monitor_process() -> None:
            """Monitor memory usage of current process in background thread."""
            try:
                mem_usage = memory_usage(
                    -1,
                    interval=0.1,
                    timeout=3600,
                    max_usage=False,
                    include_children=True,
                    multiprocess=True,
                    stream=self.log_stream,
                    backend="psutil_pss",
                )
                logger.info("Memory usage across time: %s", mem_usage)
            except Exception as e:
                logger.error("Memory monitoring failed: %s", e)

        self._monitoring_thread = threading.Thread(target=monitor_process, daemon=True)
        self._monitoring_thread.start()
        logger.info("Memory monitoring started")

    def stop_monitoring(self) -> None:
        """Stop monitoring memory usage."""
        if not self.enable:
            return
        if self._monitoring_thread is not None:
            self._stop_monitoring.set()
            self._monitoring_thread = None
            logger.info("Memory monitoring stopped")
