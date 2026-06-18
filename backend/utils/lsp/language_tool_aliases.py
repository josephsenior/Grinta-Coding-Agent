"""Shared IDE / toolchain labels → Grinta canonical language adapter keys.

VS Code ``launch.json`` and debugger ``type`` fields use labels like ``pwa-node``
that do not match our internal recipe keys (e.g. ``javascript``). LSP queries
are mostly extension-driven; debugger actions often carry those IDE strings.

Keep alias tables small and explicit — normalize once here, reuse from DAP and
runtime detection helpers.
"""

from __future__ import annotations

# Maps lowercase debugger adapter / ``language`` hints to keys in
# ``backend.execution.debugger._DAP_ADAPTER_RECIPES``.
DEBUG_ADAPTER_SYNONYMS: dict[str, str] = {
    'pwa-node': 'javascript',
}


def normalize_debug_adapter_name(name: str) -> str:
    """Strip, lowercase, and apply :data:`DEBUG_ADAPTER_SYNONYMS`."""
    lowered = name.strip().lower()
    return DEBUG_ADAPTER_SYNONYMS.get(lowered, lowered)


__all__ = ['DEBUG_ADAPTER_SYNONYMS', 'normalize_debug_adapter_name']
