"""OS clipboard helper used by ``/copy``.

Tries ``pyperclip`` first (cross-platform), then falls back to the
platform's native clipboard tool (``clip`` on Windows, ``pbcopy`` on
macOS, ``wl-copy``/``xclip``/``xsel`` on Linux).
"""

from __future__ import annotations

import shutil
import subprocess

from backend.core.os_capabilities import OS_CAPS


def copy_to_system_clipboard(text: str) -> tuple[bool, str]:
    """Copy plain text to OS clipboard with multi-platform fallbacks."""
    if not text.strip():
        return False, 'No assistant reply available to copy yet.'

    try:
        import pyperclip  # type: ignore

        pyperclip.copy(text)
        return True, 'Copied last assistant reply to clipboard.'
    except Exception:
        pass

    candidates: list[list[str]] = []
    if OS_CAPS.is_windows:
        candidates = [['clip']]
    elif OS_CAPS.is_macos:
        candidates = [['pbcopy']]
    else:
        candidates = [
            ['wl-copy'],
            ['xclip', '-selection', 'clipboard'],
            ['xsel', '--clipboard', '--input'],
        ]

    for cmd in candidates:
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.run(cmd, input=text, text=True, check=True)
            return True, 'Copied last assistant reply to clipboard.'
        except Exception:
            continue

    return (
        False,
        'Clipboard copy failed. Install `pyperclip` (recommended) or a system clipboard tool and retry.',
    )
