"""Factory helpers and exports for Forge file storage backends."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.persistence.local_file_store import LocalFileStore
from backend.persistence.in_memory_file_store import InMemoryFileStore

if TYPE_CHECKING:
    from backend.persistence.files import FileStore


def get_file_store(
    file_store_type: str,
    local_data_root: str | None = None,
    file_store_web_hook_url: str | None = None,
    file_store_web_hook_headers: dict | None = None,
    file_store_web_hook_batch: bool = False,
) -> FileStore:
    """Create and configure a file store instance based on the specified type.

    Args:
        file_store_type: Type of file store ("local" or defaults to in-memory).
        local_data_root: Root directory for local disk-backed storage.
        file_store_web_hook_url: Optional webhook URL for file store events.
        file_store_web_hook_headers: Optional headers for webhook requests.
        file_store_web_hook_batch: Whether to batch webhook requests.

    Returns:
        FileStore: Configured file store instance.

    Raises:
        ValueError: If local path is required but not usable for local storage.

    """
    store: FileStore
    if file_store_type == "local":
        path = (local_data_root or "").strip()
        if not path:
            from backend.core.app_paths import get_app_settings_root

            path = get_app_settings_root()
        store = LocalFileStore(path)
    else:
        store = InMemoryFileStore()
    if file_store_web_hook_url:
        import httpx

        from backend.persistence.batched_web_hook import BatchedWebHookFileStore
        from backend.persistence.web_hook import WebHookFileStore

        if file_store_web_hook_headers is None:
            file_store_web_hook_headers = {}
        client = httpx.Client(headers=file_store_web_hook_headers or {})
        if file_store_web_hook_batch:
            store = BatchedWebHookFileStore(store, file_store_web_hook_url, client)
        else:
            store = WebHookFileStore(store, file_store_web_hook_url, client)
    return store

