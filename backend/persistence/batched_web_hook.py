"""FileStore wrapper that batches filesystem events before hitting a webhook."""

from __future__ import annotations

import threading

import httpx
import tenacity

from backend.core.logger import app_logger as logger
from backend.persistence.files import FileStore
from backend.utils.async_utils import EXECUTOR
from backend.utils.tenacity_metrics import (
    tenacity_after_factory,
    tenacity_before_sleep_factory,
)

WEBHOOK_BATCH_TIMEOUT_SECONDS = 5.0
WEBHOOK_BATCH_SIZE_LIMIT_BYTES = 1048576


class BatchedWebHookFileStore(FileStore):
    """File store which batches updates before sending them to a webhook.

    This class wraps another FileStore implementation and sends HTTP requests
    to a specified URL when files are written or deleted. Updates are batched
    and sent together after a certain amount of time or size exceeds a threshold.
    Time is counted from the last insert.

    Attributes:
        file_store: The underlying FileStore implementation
        base_url: The base URL for webhook requests
        client: The HTTP client used to make webhook requests
        batch_timeout_seconds: Time in seconds after which a batch is sent (default: WEBHOOK_BATCH_TIMEOUT_SECONDS)
        batch_size_limit_bytes: Size limit in bytes after which a batch is sent (default: WEBHOOK_BATCH_SIZE_LIMIT_BYTES)
        _batch_lock: Lock for thread-safe access to the batch
        _batch: Dictionary of pending file updates
        _batch_timer: Timer for sending batches after timeout
        _batch_size: Current size of the batch in bytes

    """

    file_store: FileStore
    base_url: str
    client: httpx.Client
    batch_timeout_seconds: float
    batch_size_limit_bytes: int
    _batch_lock: threading.Lock
    _batch: dict[str, tuple[str, str | bytes | None]]
    _batch_timer: threading.Timer | None
    _batch_size: int

    def __init__(
        self,
        file_store: FileStore,
        base_url: str,
        client: httpx.Client | None = None,
        batch_timeout_seconds: float | None = None,
        batch_size_limit_bytes: int | None = None,
    ) -> None:
        """Initialize a BatchedWebHookFileStore.

        Args:
            file_store: The underlying FileStore implementation
            base_url: The base URL for webhook requests
            client: Optional HTTP client to use for requests. If None, a new client will be created.
            batch_timeout_seconds: Time in seconds after which a batch is sent.
                If None, uses the default constant WEBHOOK_BATCH_TIMEOUT_SECONDS.
            batch_size_limit_bytes: Size limit in bytes after which a batch is sent.
                If None, uses the default constant WEBHOOK_BATCH_SIZE_LIMIT_BYTES.

        """
        self.file_store = file_store
        self.base_url = base_url
        if client is None:
            client = httpx.Client()
        self.client = client
        self.batch_timeout_seconds = (
            batch_timeout_seconds or WEBHOOK_BATCH_TIMEOUT_SECONDS
        )
        self.batch_size_limit_bytes = (
            batch_size_limit_bytes or WEBHOOK_BATCH_SIZE_LIMIT_BYTES
        )
        self._batch_lock = threading.Lock()
        self._batch = {}
        self._batch_timer = None
        self._batch_size = 0

    def write(self, path: str, contents: str | bytes) -> None:
        """Write contents to a file and queue a webhook update.

        Args:
            path: The path to write to
            contents: The contents to write

        """
        self.file_store.write(path, contents)
        self._queue_update(path, 'write', contents)

    def read(self, path: str) -> str:
        """Read contents from a file.

        Args:
            path: The path to read from

        Returns:
            The contents of the file

        """
        return self.file_store.read(path)

    def list(self, path: str) -> list[str]:
        """List files in a directory.

        Args:
            path: The directory path to list

        Returns:
            A list of file paths

        """
        return self.file_store.list(path)

    def delete(self, path: str) -> None:
        """Delete a file and queue a webhook update.

        Args:
            path: The path to delete

        """
        self.file_store.delete(path)
        self._queue_update(path, 'delete', None)

    def _queue_update(
        self, path: str, operation: str, contents: str | bytes | None
    ) -> None:
        """Queue an update to be sent to the webhook.

        Args:
            path: The path that was modified
            operation: The operation performed ("write" or "delete")
            contents: The contents that were written (None for delete operations)

        """
        with self._batch_lock:
            content_size = 0
            if contents is not None:
                if isinstance(contents, str):
                    content_size = len(contents.encode('utf-8'))
                else:
                    content_size = len(contents)
            if path in self._batch:
                _prev_op, prev_contents = self._batch[path]
                if prev_contents is not None:
                    if isinstance(prev_contents, str):
                        self._batch_size -= len(prev_contents.encode('utf-8'))
                    else:
                        self._batch_size -= len(prev_contents)
            self._batch_size += content_size
            self._batch[path] = (operation, contents)
            if self._batch_size >= self.batch_size_limit_bytes:
                self._enqueue_batch_from_lock()
                return
            if self._batch_timer is not None:
                self._batch_timer.cancel()
                self._batch_timer = None
            timer = threading.Timer(
                self.batch_timeout_seconds, self._enqueue_batch_from_timer
            )
            timer.daemon = True
            timer.start()
            self._batch_timer = timer

    def _enqueue_batch_from_timer(self) -> None:
        """Send the batch from the timer thread.

        This method is called by the timer and submits the actual sending to the executor.
        """
        with self._batch_lock:
            self._enqueue_batch_from_lock()

    def _enqueue_batch_from_lock(self, background=True) -> None:
        """Must have lock before calling. Will reset the batch state and send the current one.

        Uses executor by default, but can perform synchronously by setting background=False.
        """
        batch_to_send = self._batch
        self._batch = {}
        self._batch_size = 0
        if background:
            EXECUTOR.submit(self._send_batch, batch_to_send)
        else:
            self._send_batch(batch_to_send)
        if self._batch_timer is not None:
            self._batch_timer.cancel()
            self._batch_timer = None

    def _send_batch(
        self, batch_to_send: dict[str, tuple[str, str | bytes | None]]
    ) -> None:
        """Send the current batch of updates to the webhook as a single request.

        This method acquires the batch lock and processes all pending updates in one batch.
        """
        if batch_to_send:
            try:
                self._send_batch_request(batch_to_send)
            except Exception:
                logger.exception('Error sending webhook batch')

    @tenacity.retry(
        wait=tenacity.wait_fixed(1),
        stop=tenacity.stop_after_attempt(3),
        before_sleep=tenacity_before_sleep_factory(
            'storage.batched_webhook.send_batch'
        ),
        after=tenacity_after_factory('storage.batched_webhook.send_batch'),
    )
    def _send_batch_request(
        self, batch: dict[str, tuple[str, str | bytes | None]]
    ) -> None:
        """Send a single batch request to the webhook URL with all updates.

        This method is retried up to 3 times with a 1-second delay between attempts.

        Args:
            batch: Dictionary mapping paths to (operation, contents) tuples

        Raises:
            httpx.HTTPStatusError: If the webhook request fails

        """
        batch_payload = []
        for path, (operation, contents) in batch.items():
            item = {
                'method': 'POST' if operation == 'write' else 'DELETE',
                'path': path,
            }
            if operation == 'write' and contents is not None:
                if isinstance(contents, bytes):
                    try:
                        item['content'] = contents.decode('utf-8')
                    except UnicodeDecodeError:
                        import base64

                        item['content'] = base64.b64encode(contents).decode('ascii')
                        item['encoding'] = 'base64'
                else:
                    item['content'] = contents
            batch_payload.append(item)
        response = self.client.post(self.base_url, json=batch_payload)
        response.raise_for_status()

    def flush(self) -> None:
        """Immediately send any pending updates to the webhook.

        This can be called to ensure all updates are sent before shutting down.
        """
        with self._batch_lock:
            self._enqueue_batch_from_lock(background=False)
