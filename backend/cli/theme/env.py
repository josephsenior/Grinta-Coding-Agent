"""Environment-driven theme behavior (NO_COLOR, presets, accessibility)."""

from __future__ import annotations

import os

_THEME_PRESET: str | None = None

THEME_PRESETS = frozenset(
    {
        'default',
        'dark',
        'light',
        'high-contrast',
        'ocean',
        'mono',
        'deep-system-instrumentation',
    }
)


def _env_truthy(name: str) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return False
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def no_color_enabled() -> bool:
    """Respect NO_COLOR and a Grinta-specific override."""
    return _env_truthy('NO_COLOR') or _env_truthy('GRINTA_NO_COLOR')


def set_theme_preset(name: str) -> None:
    """Override the active theme preset (must be called before imports)."""
    global _THEME_PRESET
    _THEME_PRESET = name


def get_theme_preset() -> str:
    """Return the active theme preset name.

    Check order: explicit set → ``GRINTA_THEME`` env var → ``deep-system-instrumentation``.
    """
    if _THEME_PRESET is not None:
        return _THEME_PRESET
    raw = (os.environ.get('GRINTA_THEME') or '').strip().lower()
    if raw in THEME_PRESETS:
        return raw
    return 'deep-system-instrumentation'


def use_ascii_cli_symbols() -> bool:
    """When true, use ASCII-friendly markers instead of Unicode (``GRINTA_ASCII=1``)."""
    if _env_truthy('GRINTA_ASCII'):
        return True
    enc = (os.environ.get('PYTHONIOENCODING') or '').strip().lower()
    return enc == 'ascii'


def splash_anim_disabled() -> bool:
    """Skip splash ``Live`` animation (``GRINTA_NO_SPLASH_ANIM=1``)."""
    return _env_truthy('GRINTA_NO_SPLASH_ANIM')


def accessible_mode_enabled() -> bool:
    """When true, enable high-contrast/simplified UI for accessibility.

    Controlled by the ``GRINTA_ACCESSIBLE`` env var.

    Accessible mode disables animations, disables color (via ``NO_COLOR``),
    forces ASCII symbols, and uses simplified layouts suitable for screen
    readers and low-vision users.
    """
    return _env_truthy('GRINTA_ACCESSIBLE')
