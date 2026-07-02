"""File-level import edge extraction for the symbol index."""

from __future__ import annotations

from backend.engine.tools._aps_dependencies import _downstream_imports


def downstream_import_paths(file_path: str, workspace_root: str) -> list[str]:
    """Return workspace-relative paths imported by ``file_path``."""
    return _downstream_imports(file_path, workspace_root)
