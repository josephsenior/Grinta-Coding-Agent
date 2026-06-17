"""Image attachment helpers for the Grinta TUI."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

SUPPORTED_IMAGE_SUFFIXES = frozenset(
    {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
)


def is_supported_image_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_IMAGE_SUFFIXES


def encode_image_path_as_data_url(path: str | Path, *, max_bytes: int) -> str:
    """Read an image file and return a ``data:image/...;base64,...`` URL."""
    file_path = Path(path)
    data = file_path.read_bytes()
    if len(data) > max_bytes:
        size_mb = len(data) / (1024 * 1024)
        limit_mb = max_bytes / (1024 * 1024)
        msg = (
            f'Image too large ({size_mb:.1f} MB). '
            f'Maximum attachment size is {limit_mb:.0f} MB.'
        )
        raise ValueError(msg)
    mime_type, _ = mimetypes.guess_type(str(file_path))
    encoded = base64.b64encode(data).decode('ascii')
    return f'data:{mime_type or "image/png"};base64,{encoded}'


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
