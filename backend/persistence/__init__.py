"""Factory helpers and exports for App file storage backends."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from backend.persistence.in_memory_file_store import InMemoryFileStore
from backend.persistence.local_file_store import LocalFileStore

if TYPE_CHECKING:
    from backend.persistence.files import FileStore


def get_file_store(
    file_store_type: str,
    local_data_root: str | None = None,
) -> FileStore:
    """Create and configure a file store instance based on the specified type.

    Args:
        file_store_type: Type of file store ("local" or defaults to in-memory).
        local_data_root: Root directory for local disk-backed storage.

    Returns:
        FileStore: Configured file store instance.

    Raises:
        ValueError: If local path is required but not usable for local storage.

    """
    store: FileStore
    if file_store_type == 'local':
        path = (local_data_root or '').strip()
        if not path:
            # Do not fall back to get_app_settings_root(): when settings.json lives in the
            # project folder that becomes the store root and creates a top-level sessions/
            # tree in the user's repo. Default matches AppConfig.local_data_root.
            from backend.core.constants import DEFAULT_LOCAL_DATA_ROOT

            path = os.path.expanduser(DEFAULT_LOCAL_DATA_ROOT)
        store = LocalFileStore(path)
    else:
        store = InMemoryFileStore()
    return store
