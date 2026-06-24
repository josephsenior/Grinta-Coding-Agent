"""Toggle Textual host mouse reporting.

Optional helper for future use; the TUI keeps ``mouse=True`` by default.
"""

from __future__ import annotations

from typing import Any


def set_textual_mouse_reporting(app: Any | None, *, enabled: bool) -> None:
    """Enable or disable the Textual driver's host mouse reporting."""
    if app is None:
        return
    driver = getattr(app, '_driver', None)
    if driver is None:
        return
    method_name = '_enable_mouse_support' if enabled else '_disable_mouse_support'
    method = getattr(driver, method_name, None)
    if not callable(method):
        return
    try:
        method()
    except Exception:
        pass
