"""Secret masking for event payloads.

Provides :class:`SecretMasker` which replaces sensitive values in
serialized event dictionaries before they are persisted or dispatched.

Extracted from ``stream.py`` to keep the event-stream core focused on
pub/sub and backpressure while preserving stable event formatting.
"""

from __future__ import annotations

import re
from typing import Any


class SecretMasker:
    """Masks secret strings inside nested dicts, lists, and byte values.

    Usage::

        masker = SecretMasker()
        masker.set_secrets({"MY_API_KEY": "sk-123..."})
        sanitised = masker.replace_secrets(raw_event_dict)

    """

    PLACEHOLDER = '<secret_hidden>'
    # Top-level event fields that must never be masked so the event
    # structure (type, id, source, etc.) stays intact.
    TOP_LEVEL_PROTECTED_FIELDS = frozenset(
        {'timestamp', 'id', 'source', 'cause', 'action', 'observation', 'message'}
    )

    def __init__(self) -> None:
        self.secrets: dict[str, str] = {}
        self._secret_pattern: re.Pattern[str] | None = None
        self._secret_bytes: list[bytes] = []

    # ------------------------------------------------------------------ #
    # Public API                                                          #
    # ------------------------------------------------------------------ #
    def set_secrets(self, secrets: dict[str, str]) -> None:
        """Replace the full secrets dictionary and recompile patterns."""
        self.secrets = secrets.copy()
        self._rebuild_cache()

    def update_secrets(self, secrets: dict[str, str]) -> None:
        """Merge additional secrets and recompile patterns."""
        self.secrets.update(secrets)
        self._rebuild_cache()

    def replace_secrets(
        self, data: dict[str, Any], *, is_top_level: bool = True
    ) -> dict[str, Any]:
        """Recursively replace secret values with a masked placeholder.

        Top-level event fields are protected so event structure is preserved.
        """
        for key in list(data.keys()):
            if is_top_level and key in self.TOP_LEVEL_PROTECTED_FIELDS:
                continue
            data[key] = self._sanitize_value(data[key])
        return data

    # ------------------------------------------------------------------ #
    # Internals                                                           #
    # ------------------------------------------------------------------ #
    def _rebuild_cache(self) -> None:
        """Precompile a single regex from all non-empty secret values."""
        tokens = [str(s) for s in self.secrets.values() if isinstance(s, str) and s]
        unique = sorted(set(tokens), key=len, reverse=True)
        if unique:
            self._secret_pattern = re.compile(
                '|'.join(re.escape(t) for t in unique), flags=re.IGNORECASE
            )
            self._secret_bytes = [t.encode('utf-8') for t in unique]
        else:
            self._secret_pattern = None
            self._secret_bytes = []

    def _sanitize_value(self, value: Any) -> Any:
        if isinstance(value, dict):
            return self.replace_secrets(value, is_top_level=False)
        if isinstance(value, list):
            return [self._sanitize_value(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self._sanitize_value(item) for item in value)
        if isinstance(value, str):
            return self._mask_string(value)
        if isinstance(value, bytes):
            return self._mask_bytes(value)
        return value

    def _mask_string(self, value: str) -> str:
        if not value or not self._secret_pattern:
            return value
        return self._secret_pattern.sub(self.PLACEHOLDER, value)

    def _mask_bytes(self, value: bytes) -> bytes:
        if not value or not self._secret_bytes:
            return value
        masked = value
        for token in self._secret_bytes:
            if token:
                masked = masked.replace(token, self.PLACEHOLDER.encode('utf-8'))
        return masked
