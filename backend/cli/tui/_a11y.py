"""Accessibility helpers for the TUI.

Single source of truth for the ``accessible_mode`` flag and the related
``animations_enabled`` and ``ascii_glyphs_enabled`` predicates. The
``GrintaScreen`` instance stores ``_accessible_mode`` (set at construction
from the ``--accessible`` CLI flag); widget classes that do not have a
direct reference to the screen fall back to the env-var lookup
(``theme.env.accessible_mode_enabled``).
"""

from __future__ import annotations

from backend.cli.theme import (
    accessible_mode_enabled,
    splash_anim_disabled,
    use_ascii_cli_symbols,
)


def _host_accessible(host: object | None) -> bool:
    """Read the screen's ``_accessible_mode`` flag, falling back to env."""
    if host is not None:
        flag = getattr(host, '_accessible_mode', None)
        if isinstance(flag, bool):
            return flag
    return accessible_mode_enabled()


def animations_enabled(host: object | None = None) -> bool:
    """Whether the TUI should run pulse / cascade / mount animations.

    Returns ``False`` if the user passed ``--accessible`` (or set
    ``GRINTA_ACCESSIBLE=1``) **or** if splash animations are disabled via
    ``GRINTA_NO_SPLASH_ANIM=1``.
    """
    if _host_accessible(host):
        return False
    return not splash_anim_disabled()


def ascii_glyphs_enabled(host: object | None = None) -> bool:
    """Whether the TUI should render ASCII glyphs instead of Unicode."""
    if _host_accessible(host):
        return True
    return use_ascii_cli_symbols()
