"""Factory helpers and exports for Forge file storage backends."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from backend.storage.local import LocalFileStore
from backend.storage.in_memory import InMemoryFileStore

if TYPE_CHECKING:
    from backend.storage.files import FileStore


def get_file_store(
    file_store_type: str,
    file_store_path: str | None = None,
    file_store_web_hook_url: str | None = None,
    file_store_web_hook_headers: dict | None = None,
    file_store_web_hook_batch: bool = False,
) -> FileStore:
    """Create and configure a file store instance based on the specified type.

    Args:
        file_store_type: Type of file store ("local" or defaults to in-memory).
        file_store_path: Path for local file store.
        file_store_web_hook_url: Optional webhook URL for file store events.
        file_store_web_hook_headers: Optional headers for webhook requests.
        file_store_web_hook_batch: Whether to batch webhook requests.

    Returns:
        FileStore: Configured file store instance.

    Raises:
        ValueError: If file_store_path is required but not provided for local storage.

    """
    store: FileStore
    if file_store_type == "local":
        if file_store_path is None:
            msg = "file_store_path is required for local file store"
            raise ValueError(msg)
        store = LocalFileStore(file_store_path)
    else:
        store = InMemoryFileStore()
    if file_store_web_hook_url:
        import httpx

        from backend.storage.batched_web_hook import BatchedWebHookFileStore
        from backend.storage.web_hook import WebHookFileStore

        if file_store_web_hook_headers is None:
            file_store_web_hook_headers = {}
            if os.getenv("SESSION_API_KEY"):
                file_store_web_hook_headers["X-Session-API-Key"] = os.getenv(
                    "SESSION_API_KEY"
                )
        client = httpx.Client(headers=file_store_web_hook_headers or {})
        if file_store_web_hook_batch:
            store = BatchedWebHookFileStore(store, file_store_web_hook_url, client)
        else:
            store = WebHookFileStore(store, file_store_web_hook_url, client)
    return store
