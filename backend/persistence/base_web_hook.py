"""Base class for FileStore wrappers that interact with webhooks."""

from __future__ import annotations

import httpx
from backend.persistence.files import FileStore


class BaseWebHookFileStore(FileStore):
    """Base class for FileStore implementations that trigger webhooks.

    Attributes:
        file_store: The underlying FileStore implementation.
        base_url: The base URL for webhook requests.
        client: The HTTP client used for requests.
    """

    file_store: FileStore
    base_url: str
    client: httpx.Client

    def __init__(
        self,
        file_store: FileStore,
        base_url: str,
        client: httpx.Client | None = None,
    ) -> None:
        """Initialize the webhook file store.

        Args:
            file_store: The underlying FileStore implementation.
            base_url: The base URL for webhook requests.
            client: Optional HTTP client. If None, a new one is created.
        """
        self.file_store = file_store
        self.base_url = base_url
        if client is None:
            client = httpx.Client()
        self.client = client

    def read(self, path: str) -> str:
        """Read contents from a file."""
        return self.file_store.read(path)

    def list(self, path: str) -> list[str]:
        """List files in a directory."""
        return self.file_store.list(path)

    def delete(self, path: str) -> None:
        """Delete a file."""
        self.file_store.delete(path)
