from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import Request
    from backend.runtime.action_execution_server import ActionExecutor


async def _resolve_list_path(request: Request, client: ActionExecutor) -> str:
    """Resolve file listing path from request payload or fallback to runtime cwd."""
    path = ""
    try:
        data = await request.json()
        if isinstance(data, dict):
            path = str(data.get("path") or "")
    except Exception:
        path = ""

    if not path:
        return client.initial_cwd
    if os.path.isabs(path):
        return os.path.normpath(path)
    return os.path.normpath(os.path.join(client.initial_cwd, path))


def _get_sorted_directory_entries(full_path: str) -> list[str]:
    """Return sorted directory entries with directories first."""
    entries = os.listdir(full_path)
    return sorted(
        entries,
        key=lambda name: (
            not os.path.isdir(os.path.join(full_path, name)),
            name.lower(),
        ),
    )
