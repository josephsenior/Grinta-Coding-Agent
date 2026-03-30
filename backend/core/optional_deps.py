"""Helpers for optional dependencies.

Core modules should not import optional dependencies at import time.
Instead, optional subsystems should import their dependencies lazily when used.
"""

from __future__ import annotations

import importlib


class OptionalDependencyError(ImportError):
    pass


def require_optional(module: str, *, extra: str) -> object:
    """Import an optional module or raise a crisp error.

    Args:
        module: Top-level module name to import.
        extra: uv/Python extra name users should install.

    Returns:
        Imported module.
    """
    try:
        return importlib.import_module(module)
    except ModuleNotFoundError as exc:
        raise OptionalDependencyError(
            f"Optional dependency '{module}' is required for this feature. "
            f"Install with: pip install 'app-ai[{extra}]'"
        ) from exc
