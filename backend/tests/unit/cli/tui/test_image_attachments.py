"""Tests for TUI image attachment helpers."""

from __future__ import annotations

import base64
import struct
import tempfile
from pathlib import Path

from backend.cli.tui.image_attachments import (
    ClipboardImage,
    encode_image_bytes_as_data_url,
    encode_image_path_as_data_url,
    is_supported_image_path,
)


def test_dib_to_bmp_wraps_header() -> None:
    from backend.cli.tui.image_attachments import _dib_to_bmp

    # Minimal 1x1 24-bit DIB header + pixel data.
    dib = (
        struct.pack(
            '<IiiHHIIiiII',
            40,
            1,
            1,
            1,
            24,
            0,
            4,
            0,
            0,
            0,
            0,
        )
        + b'\x00\x00\x00\x00'
    )
    bmp = _dib_to_bmp(dib)
    assert bmp is not None
    assert bmp.startswith(b'BM')


def test_is_supported_image_path() -> None:
    assert is_supported_image_path('photo.PNG')
    assert not is_supported_image_path('notes.pdf')


def test_image_attachment_status_text() -> None:
    from backend.cli.tui.image_attachments import image_attachment_status_text

    assert image_attachment_status_text(1) == '1 image attached'
    assert image_attachment_status_text(2) == '2 images attached'
    assert '[bold #5eead4]1 image attached[/]' == image_attachment_status_text(
        1, rich=True
    )


async def test_encode_image_path_as_data_url() -> None:
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as handle:
        handle.write(b'\x89PNG\r\n\x1a\n')
        path = handle.name
    try:
        url = await encode_image_path_as_data_url(path, max_bytes=1024)
        assert url.startswith('data:image/png;base64,')
        payload = url.split(',', 1)[1]
        assert base64.b64decode(payload).startswith(b'\x89PNG')
    finally:
        Path(path).unlink(missing_ok=True)


def test_encode_image_bytes_as_data_url() -> None:
    payload = b'\x89PNG\r\n\x1a\n'
    url = encode_image_bytes_as_data_url(payload, 'image/png', max_bytes=1024)
    assert url.startswith('data:image/png;base64,')


def test_read_clipboard_image_returns_none_when_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        'backend.cli.tui.image_attachments._read_windows_clipboard_image',
        lambda: None,
    )
    monkeypatch.setattr(
        'backend.cli.tui.image_attachments._read_macos_clipboard_image',
        lambda: None,
    )
    monkeypatch.setattr(
        'backend.cli.tui.image_attachments._read_linux_clipboard_image',
        lambda: None,
    )
    from backend.cli.tui.image_attachments import _read_clipboard_image_sync

    assert _read_clipboard_image_sync() is None


def test_read_clipboard_image_prefers_first_available_reader(monkeypatch) -> None:
    sample = ClipboardImage(
        data=b'\x89PNG\r\n',
        mime_type='image/png',
        label='clipboard.png',
    )
    monkeypatch.setattr(
        'backend.cli.tui.image_attachments._read_windows_clipboard_image',
        lambda: sample,
    )
    from backend.cli.tui.image_attachments import _read_clipboard_image_sync

    assert _read_clipboard_image_sync() == sample
