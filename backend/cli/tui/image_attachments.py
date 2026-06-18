"""Image attachment helpers for the Grinta TUI."""

from __future__ import annotations

import base64
import mimetypes
import platform
import struct
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

SUPPORTED_IMAGE_SUFFIXES = frozenset({'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'})

_IMAGE_ATTACHMENT_STYLE = 'bold #5eead4'


def image_attachment_status_text(count: int, *, rich: bool = False) -> str:
    """Human-readable pending/sent image attachment label."""
    if count <= 0:
        return ''
    label = 'image' if count == 1 else 'images'
    text = f'{count} {label} attached'
    if rich:
        return f'[{_IMAGE_ATTACHMENT_STYLE}]{text}[/]'
    return text


@dataclass(frozen=True)
class ClipboardImage:
    """Raw clipboard image bytes and metadata."""

    data: bytes
    mime_type: str
    label: str


def is_supported_image_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_IMAGE_SUFFIXES


def encode_image_bytes_as_data_url(
    data: bytes,
    mime_type: str,
    *,
    max_bytes: int,
) -> str:
    """Encode raw image bytes as a data URL."""
    if len(data) > max_bytes:
        size_mb = len(data) / (1024 * 1024)
        limit_mb = max_bytes / (1024 * 1024)
        msg = (
            f'Image too large ({size_mb:.1f} MB). '
            f'Maximum attachment size is {limit_mb:.0f} MB.'
        )
        raise ValueError(msg)
    encoded = base64.b64encode(data).decode('ascii')
    return f'data:{mime_type or "image/png"};base64,{encoded}'


def encode_image_path_as_data_url(path: str | Path, *, max_bytes: int) -> str:
    """Read an image file and return a ``data:image/...;base64,...`` URL."""
    file_path = Path(path)
    data = file_path.read_bytes()
    mime_type, _ = mimetypes.guess_type(str(file_path))
    return encode_image_bytes_as_data_url(
        data,
        mime_type or 'image/png',
        max_bytes=max_bytes,
    )


def _dib_to_bmp(dib: bytes) -> bytes | None:
    """Wrap a device-independent bitmap (DIB) in a BMP file header."""
    if len(dib) < 40:
        return None
    header_size = struct.unpack('<I', dib[0:4])[0]
    if header_size < 40 or header_size > len(dib):
        return None
    bit_count = struct.unpack('<H', dib[14:16])[0]
    colors_used = struct.unpack('<I', dib[32:36])[0]
    color_table_size = 0
    if bit_count <= 8:
        palette_entries = colors_used or (1 << bit_count)
        color_table_size = palette_entries * 4
    pixel_offset = 14 + header_size + color_table_size
    file_size = 14 + len(dib)
    return b'BM' + struct.pack('<III', file_size, 0, pixel_offset) + dib


def _read_windows_clipboard_image() -> ClipboardImage | None:
    if sys.platform != 'win32':
        return None
    # Prefer PowerShell: handles CF_DIB / screenshots; ctypes only sees rare PNG formats.
    image = _read_windows_clipboard_image_powershell()
    if image is not None:
        return image
    return _read_windows_clipboard_image_ctypes()


def _read_windows_clipboard_image_ctypes() -> ClipboardImage | None:
    import ctypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    if not user32.OpenClipboard(0):
        return None

    try:
        for fmt_name, mime, label in (
            ('PNG', 'image/png', 'clipboard.png'),
            ('JFIF', 'image/jpeg', 'clipboard.jpg'),
            ('GIF', 'image/gif', 'clipboard.gif'),
        ):
            fmt_id = user32.RegisterClipboardFormatW(fmt_name)
            if not fmt_id or not user32.IsClipboardFormatAvailable(fmt_id):
                continue
            handle = user32.GetClipboardData(fmt_id)
            if not handle:
                continue
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                continue
            try:
                size = kernel32.GlobalSize(handle)
                data = ctypes.string_at(ptr, size)
            finally:
                kernel32.GlobalUnlock(handle)
            if data:
                return ClipboardImage(data=data, mime_type=mime, label=label)

        CF_DIB = 8
        if user32.IsClipboardFormatAvailable(CF_DIB):
            handle = user32.GetClipboardData(CF_DIB)
            if handle:
                ptr = kernel32.GlobalLock(handle)
                if ptr:
                    try:
                        size = kernel32.GlobalSize(handle)
                        dib = ctypes.string_at(ptr, size)
                    finally:
                        kernel32.GlobalUnlock(handle)
                    bmp = _dib_to_bmp(dib)
                    if bmp:
                        return ClipboardImage(
                            data=bmp,
                            mime_type='image/bmp',
                            label='clipboard.bmp',
                        )
        return None
    finally:
        user32.CloseClipboard()


def _read_windows_clipboard_image_powershell() -> ClipboardImage | None:
    script = """
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$img = [System.Windows.Forms.Clipboard]::GetImage()
if ($null -eq $img) { exit 1 }
$ms = New-Object System.IO.MemoryStream
$img.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png)
[Console]::OpenStandardOutput().Write($ms.ToArray(), 0, [int]$ms.Length)
"""
    try:
        completed = subprocess.run(
            ['powershell', '-NoProfile', '-Command', script],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout:
        return None
    return ClipboardImage(
        data=completed.stdout,
        mime_type='image/png',
        label='clipboard.png',
    )


def _read_macos_clipboard_image() -> ClipboardImage | None:
    if platform.system() != 'Darwin':
        return None
    try:
        completed = subprocess.run(
            ['pngpaste', '-'],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout:
        return None
    return ClipboardImage(
        data=completed.stdout,
        mime_type='image/png',
        label='clipboard.png',
    )


def _read_linux_clipboard_image() -> ClipboardImage | None:
    if platform.system() != 'Linux':
        return None
    for command in (
        ['wl-paste', '--type', 'image/png'],
        ['xclip', '-selection', 'clipboard', '-t', 'image/png', '-o'],
    ):
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode == 0 and completed.stdout:
            return ClipboardImage(
                data=completed.stdout,
                mime_type='image/png',
                label='clipboard.png',
            )
    return None


def read_clipboard_image_blocking() -> ClipboardImage | None:
    """Return clipboard image bytes when the OS clipboard holds an image."""
    readers = (
        _read_windows_clipboard_image,
        _read_macos_clipboard_image,
        _read_linux_clipboard_image,
    )
    for reader in readers:
        try:
            image = reader()
        except Exception:
            image = None
        if image is not None:
            return image
    return None


def pick_image_files_blocking() -> tuple[str, ...]:
    """Open a native file picker and return selected image paths."""
    import tkinter as tk
    from tkinter import filedialog

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes('-topmost', True)
    except Exception:
        pass
    try:
        selected = filedialog.askopenfilenames(
            title='Attach images',
            filetypes=[
                ('Images', '*.png *.jpg *.jpeg *.gif *.bmp *.webp'),
                ('All files', '*.*'),
            ],
        )
    finally:
        root.destroy()
    return tuple(str(path) for path in selected if path)
