"""FileStore wrapper that fires webhook requests on write/delete events."""

from __future__ import annotations

import tenacity

from backend.persistence.base_web_hook import BaseWebHookFileStore
from backend.utils.async_utils import EXECUTOR
from backend.utils.tenacity_metrics import (
    tenacity_after_factory,
    tenacity_before_sleep_factory,
)


class WebHookFileStore(BaseWebHookFileStore):
    """File store which includes a web hook to be invoked after any changes occur.

    This class wraps another FileStore implementation and sends HTTP requests
    to a specified URL whenever files are written or deleted.
    """

    def write(self, path: str, contents: str | bytes) -> None:
        """Write contents to a file and trigger a webhook.

        Args:
            path: The path to write to
            contents: The contents to write

        """
        self.file_store.write(path, contents)
        EXECUTOR.submit(self._on_write, path, contents)

    def delete(self, path: str) -> None:
        """Delete a file and trigger a webhook.

        Args:
            path: The path to delete

        """
        self.file_store.delete(path)
        EXECUTOR.submit(self._on_delete, path)

    @tenacity.retry(
        wait=tenacity.wait_fixed(1),
        stop=tenacity.stop_after_attempt(3),
        before_sleep=tenacity_before_sleep_factory('storage.webhook.on_write'),
        after=tenacity_after_factory('storage.webhook.on_write'),
    )
    def _on_write(self, path: str, contents: str | bytes) -> None:
        """Send a POST request to the webhook URL when a file is written.

        This method is retried up to 3 times with a 1-second delay between attempts.

        Args:
            path: The path that was written to
            contents: The contents that were written

        Raises:
            httpx.HTTPStatusError: If the webhook request fails

        """
        base_url = self.base_url + path
        response = self.client.post(base_url, content=contents)
        response.raise_for_status()

    @tenacity.retry(
        wait=tenacity.wait_fixed(1),
        stop=tenacity.stop_after_attempt(3),
        before_sleep=tenacity_before_sleep_factory('storage.webhook.on_delete'),
        after=tenacity_after_factory('storage.webhook.on_delete'),
    )
    def _on_delete(self, path: str) -> None:
        """Send a DELETE request to the webhook URL when a file is deleted.

        This method is retried up to 3 times with a 1-second delay between attempts.

        Args:
            path: The path that was deleted

        Raises:
            httpx.HTTPStatusError: If the webhook request fails

        """
        base_url = self.base_url + path
        response = self.client.delete(base_url)
        response.raise_for_status()
