"""Shared key-value blackboard for parallel delegate_task workers.

When delegate_task_blackboard_enabled is True, the parent creates a single
Blackboard instance and passes it to each worker controller. Workers use the
blackboard tool to read/write shared state (e.g. schema contracts, status).
"""

from __future__ import annotations

import asyncio
from typing import Any


class Blackboard:
    """Thread- and async-safe key-value store for sub-agent coordination."""

    def _save(self):
        import json, os
        path = '.forge/blackboard.json'
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(self._data, f)

    def _load(self):
        import json, os
        path = '.forge/blackboard.json'
        if os.path.exists(path):
            try:
                with open(path, 'r') as f:
                    loaded_data = json.load(f)
                    self._data.update(loaded_data)
            except Exception:
                pass

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._load()
        self._lock = asyncio.Lock()

    async def get(self, key: str | None = None) -> dict[str, str] | str:
        """Get one key's value, or all keys when key is None or 'all'."""
        async with self._lock:
            if key is None or key == "" or key == "all":
                return dict(self._data)
            return self._data.get(key, "")

    async def set(self, key: str, value: str) -> None:
        """Set a key to a string value."""
        if not key:
            return
        async with self._lock:
            self._data[key] = value
            self._save()

    async def keys(self) -> list[str]:
        """Return all keys."""
        async with self._lock:
            return list(self._data.keys())

    def snapshot(self) -> dict[str, str]:
        """Synchronous snapshot for observation text (no lock; best-effort)."""
        return dict(self._data)
