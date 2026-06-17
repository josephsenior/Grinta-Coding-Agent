"""Tests for TUI image attachment helpers."""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

from backend.cli.tui.image_attachments import (
    encode_image_path_as_data_url,
    is_supported_image_path,
)


def test_is_supported_image_path() -> None:
    assert is_supported_image_path('photo.PNG')
    assert not is_supported_image_path('notes.pdf')


def test_encode_image_path_as_data_url() -> None:
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as handle:
        handle.write(b'\x89PNG\r\n\x1a\n')
        path = handle.name
    try:
        url = encode_image_path_as_data_url(path, max_bytes=1024)
        assert url.startswith('data:image/png;base64,')
        payload = url.split(',', 1)[1]
        assert base64.b64decode(payload).startswith(b'\x89PNG')
    finally:
        Path(path).unlink(missing_ok=True)
