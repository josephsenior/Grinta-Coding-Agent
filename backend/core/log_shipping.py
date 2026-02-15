"""Log shipping module for sending logs to external services (Datadog, ELK, etc.)."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import deque
from typing import Any
from urllib.parse import ParseResult

import aiohttp

logger = logging.getLogger(__name__)


from backend.core.external_service import ExternalServiceBase


class LogShipper(ExternalServiceBase):
    """Ship logs to external services (Datadog, ELK, etc.) with batching and retry logic."""

    def __init__(
        self,
        endpoint: str | None = None,
        api_key: str | None = None,
        batch_size: int = 100,
        batch_timeout: float = 5.0,
        max_retries: int = 3,
        retry_delay: float = 1.0,
        enabled: bool = False,
    ) -> None:
        """Initialize log shipper.

        Args:
            endpoint: Log shipping endpoint URL
            api_key: API key for log shipping service
            batch_size: Number of logs to batch before shipping
            batch_timeout: Maximum time to wait before shipping batch (seconds)
            max_retries: Maximum number of retries for failed shipments
            retry_delay: Delay between retries (seconds)
            enabled: Whether log shipping is enabled

        """
        super().__init__(endpoint=endpoint, api_key=api_key, enabled=enabled)
        self.batch_size = batch_size
        self.batch_timeout = batch_timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self._log_queue: deque[dict[str, Any]] = deque(maxlen=batch_size * 10)
        self._last_ship_time = time.time()
        self._ship_task: asyncio.Task | None = None
        self._shutdown_event = asyncio.Event()

    async def _ship_logs(self, logs: list[dict[str, Any]]) -> bool:
        """Ship logs to external service."""

        def build_payload(parsed_endpoint: ParseResult) -> dict[str, Any]:
            return self._build_payload(parsed_endpoint, logs)

        async def execute_request(
            session: aiohttp.ClientSession, payload: Any, headers: dict[str, str]
        ) -> bool:
            return await self._post_payload(session, payload, headers, len(logs))

        return await self._send_request(
            build_payload=build_payload,
            execute_request=execute_request,
            error_msg=f"Error shipping logs to {self.endpoint}",
        )

    def _build_payload(
        self, parsed_endpoint: ParseResult, logs: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if "datadog" in parsed_endpoint.netloc.lower():
            return self._datadog_payload(logs)
        return {"logs": logs}

    def _datadog_payload(self, logs: list[dict[str, Any]]) -> dict[str, Any]:
        env = os.getenv("ENV", "production")
        hostname = os.getenv("HOSTNAME", "forge")
        service = os.getenv("SERVICE_NAME", "forge")
        return {
            "logs": [
                {
                    "ddsource": "forge",
                    "ddtags": f"env:{env}",
                    "hostname": hostname,
                    "service": service,
                    **log,
                }
                for log in logs
            ]
        }

    async def _post_payload(
        self,
        session: aiohttp.ClientSession,
        payload: dict[str, Any],
        headers: dict[str, str],
        log_count: int,
    ) -> bool:
        assert self.endpoint is not None  # For type checkers
        async with session.post(
            self.endpoint, json=payload, headers=headers
        ) as response:
            if response.status in (200, 201):
                logger.debug("Shipped %s logs to %s", log_count, self.endpoint)
                return True
            error_text = await response.text()
            logger.warning(
                "Failed to ship logs to %s: %s - %s",
                self.endpoint,
                response.status,
                error_text,
            )
            return False

    async def _ship_batch(self) -> None:
        """Ship batched logs periodically."""
        while not self._shutdown_event.is_set():
            if await self._wait_for_batch_window():
                break
            await self._ship_available_logs()

    async def _wait_for_batch_window(self) -> bool:
        try:
            await asyncio.wait_for(
                self._shutdown_event.wait(), timeout=self.batch_timeout
            )
            return True
        except TimeoutError:
            return False

    async def _ship_available_logs(self) -> None:
        logs_to_ship = self._dequeue_batch()
        if not logs_to_ship:
            return
        if not await self._attempt_ship_with_retries(logs_to_ship):
            logger.error(
                "Failed to ship %s logs after %s attempts",
                len(logs_to_ship),
                self.max_retries,
            )

    def _dequeue_batch(self) -> list[dict[str, Any]]:
        logs_to_ship: list[dict[str, Any]] = []
        while self._log_queue and len(logs_to_ship) < self.batch_size:
            logs_to_ship.append(self._log_queue.popleft())
        return logs_to_ship

    async def _attempt_ship_with_retries(
        self, logs_to_ship: list[dict[str, Any]]
    ) -> bool:
        for attempt in range(self.max_retries):
            if await self._ship_logs(logs_to_ship):
                return True
            if attempt < self.max_retries - 1:
                await asyncio.sleep(self.retry_delay * (2**attempt))
        return False

    def enqueue(self, log_entry: dict[str, Any]) -> None:
        """Enqueue log entry for shipping.

        Args:
            log_entry: Log entry to ship

        """
        if not self.enabled:
            return

        self._log_queue.append(log_entry)

        # Ship immediately if batch is full
        if len(self._log_queue) >= self.batch_size:
            if self._ship_task is None or self._ship_task.done():
                self._ship_task = asyncio.create_task(self._ship_batch())

    async def flush(self) -> None:
        """Flush all queued logs."""
        if not self.enabled or not self._log_queue:
            return

        logs_to_ship = list(self._log_queue)
        self._log_queue.clear()

        if logs_to_ship:
            await self._ship_logs(logs_to_ship)

    async def start(self) -> None:
        """Start log shipping background task."""
        if not self.enabled:
            return

        self._shutdown_event.clear()
        self._ship_task = asyncio.create_task(self._ship_batch())
        logger.info("Log shipping started for %s", self.endpoint)

    async def stop(self) -> None:
        """Stop log shipping and flush remaining logs."""
        if not self.enabled:
            return

        self._shutdown_event.set()
        if self._ship_task:
            await self._ship_task
        await self.flush()

        if self._session and not self._session.closed:
            await self._session.close()

        logger.info("Log shipping stopped")


# Global log shipper instance
_log_shipper: LogShipper | None = None


def get_log_shipper() -> LogShipper | None:
    """Get or create global log shipper instance."""
    global _log_shipper
    if _log_shipper is None:
        endpoint = os.getenv("LOG_SHIPPING_ENDPOINT")
        api_key = os.getenv("LOG_SHIPPING_API_KEY")
        enabled = os.getenv("LOG_SHIPPING_ENABLED", "false").lower() == "true"

        if enabled and endpoint:
            _log_shipper = LogShipper(
                endpoint=endpoint,
                api_key=api_key,
                batch_size=int(os.getenv("LOG_SHIPPING_BATCH_SIZE", "100")),
                batch_timeout=float(os.getenv("LOG_SHIPPING_BATCH_TIMEOUT", "5.0")),
                max_retries=int(os.getenv("LOG_SHIPPING_MAX_RETRIES", "3")),
                retry_delay=float(os.getenv("LOG_SHIPPING_RETRY_DELAY", "1.0")),
                enabled=True,
            )
            logger.info("Log shipper initialized for %s", endpoint)
        else:
            logger.debug("Log shipping not configured")

    return _log_shipper


class LogShippingHandler(logging.Handler):
    """Logging handler that ships logs to external services."""

    def __init__(self, shipper: LogShipper | None = None) -> None:
        """Initialize log shipping handler.

        Args:
            shipper: Log shipper instance (defaults to global instance)

        """
        super().__init__()
        self.shipper = shipper or get_log_shipper()

    def emit(self, record: logging.LogRecord) -> None:
        """Emit log record to shipping queue.

        Args:
            record: Log record to ship

        """
        if not self.shipper or not self.shipper.enabled:
            return

        try:
            # Convert log record to dictionary
            log_entry = {
                "timestamp": record.created,
                "level": record.levelname,
                "message": record.getMessage(),
                "logger": record.name,
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno,
                "path": record.pathname,
            }

            # Add extra fields
            for key, value in record.__dict__.items():
                if key not in (
                    "name",
                    "msg",
                    "args",
                    "created",
                    "filename",
                    "funcName",
                    "levelname",
                    "levelno",
                    "lineno",
                    "module",
                    "msecs",
                    "message",
                    "pathname",
                    "process",
                    "processName",
                    "relativeCreated",
                    "thread",
                    "threadName",
                    "exc_info",
                    "exc_text",
                    "stack_info",
                ):
                    log_entry[key] = value

            # Add exception info if present
            if record.exc_info:
                import traceback

                log_entry["exception"] = traceback.format_exception(*record.exc_info)

            # Enqueue for shipping
            self.shipper.enqueue(log_entry)

        except Exception as e:
            # Don't let log shipping errors break logging
            logger.error("Error in log shipping handler: %s", e, exc_info=True)
