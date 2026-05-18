"""Shared key-value blackboard for parallel delegate_task workers.

When delegate_task_blackboard_enabled is True, the parent creates a single
Blackboard instance and passes it to each worker controller. Workers use the
blackboard tool to read/write shared state (e.g. schema contracts, status).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile

MAX_BLACKBOARD_KEYS = 256
MAX_BLACKBOARD_KEY_BYTES = 512
MAX_BLACKBOARD_VALUE_BYTES = 16 * 1024
MAX_BLACKBOARD_TOTAL_BYTES = 256 * 1024


def _utf8_len(value: str) -> int:
    return len(value.encode('utf-8'))


class Blackboard:
    """Thread- and async-safe key-value store for sub-agent coordination."""

    def _path(self) -> str:
        from backend.core.workspace_resolution import workspace_agent_state_dir

        return str(workspace_agent_state_dir() / 'blackboard.json')

    def _save(self) -> None:
        path = self._path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        dir_name = os.path.dirname(path)
        fd, tmp_path = tempfile.mkstemp(
            prefix='.blackboard.tmp.',
            dir=dir_name,
            text=True,
        )
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(self._data, f, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
            self._fsync_dir(dir_name)
        except Exception:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise

    @staticmethod
    def _fsync_dir(path: str) -> None:
        if os.name == 'nt':
            return
        with contextlib.suppress(OSError, AttributeError):
            dir_fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)

    def _load(self) -> None:
        import os

        path = self._path()
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    loaded_data = json.load(f)
                    if isinstance(loaded_data, dict):
                        for key, value in loaded_data.items():
                            if not isinstance(key, str) or not isinstance(value, str):
                                continue
                            try:
                                self._validate_limits(key, value)
                            except ValueError:
                                continue
                            self._data[key] = value
            except Exception:
                pass

    def __init__(self) -> None:
        self._data: dict[str, str] = {}
        self._load()
        self._lock = asyncio.Lock()

    def _current_total_bytes(self) -> int:
        return sum(_utf8_len(key) + _utf8_len(value) for key, value in self._data.items())

    def _validate_limits(self, key: str, value: str) -> None:
        key_bytes = _utf8_len(key)
        if key_bytes > MAX_BLACKBOARD_KEY_BYTES:
            raise ValueError(
                f'blackboard key too large ({key_bytes} bytes > {MAX_BLACKBOARD_KEY_BYTES})'
            )

        value_bytes = _utf8_len(value)
        if value_bytes > MAX_BLACKBOARD_VALUE_BYTES:
            raise ValueError(
                f'blackboard value too large ({value_bytes} bytes > {MAX_BLACKBOARD_VALUE_BYTES})'
            )

        if key not in self._data and len(self._data) >= MAX_BLACKBOARD_KEYS:
            raise ValueError(
                f'blackboard key limit exceeded ({MAX_BLACKBOARD_KEYS} keys)'
            )

        previous_value = self._data.get(key, '')
        projected_total = (
            self._current_total_bytes()
            - (_utf8_len(key) + _utf8_len(previous_value) if key in self._data else 0)
            + key_bytes
            + value_bytes
        )
        if projected_total > MAX_BLACKBOARD_TOTAL_BYTES:
            raise ValueError(
                f'blackboard total size limit exceeded ({projected_total} bytes > {MAX_BLACKBOARD_TOTAL_BYTES})'
            )

    async def get(self, key: str | None = None) -> dict[str, str] | str:
        """Get one key's value, or all keys when key is None or 'all'."""
        async with self._lock:
            if key is None or key == '' or key == 'all':
                return dict(self._data)
            return self._data.get(key, '')

    async def set(self, key: str, value: str) -> None:
        """Set a key to a string value."""
        if not key:
            return
        async with self._lock:
            self._validate_limits(key, value)
            self._data[key] = value
            self._save()

    async def keys(self) -> list[str]:
        """Return all keys."""
        async with self._lock:
            return list(self._data.keys())

    async def flush(self) -> None:
        """Force an immediate flush of pending writes."""
        async with self._lock:
            self._save()

    def snapshot(self) -> dict[str, str]:
        """Synchronous snapshot for observation text (no lock; best-effort)."""
        return dict(self._data)
