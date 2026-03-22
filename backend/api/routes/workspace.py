"""User-selected project folder (workspace) — open existing or create new."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api.app_state import get_app_state
from backend.core.workspace_resolution import (
    apply_workspace_to_config,
    get_effective_workspace_root,
    resolve_existing_directory,
    save_persisted_workspace_path,
)
from backend.runtime import runtime_orchestrator
from backend.storage.local import LocalFileStore

router = APIRouter(prefix="/api/v1/workspace", tags=["v1", "workspace"])


class WorkspacePathBody(BaseModel):
    path: str = Field(..., description="Absolute path to an existing folder")


class CreateWorkspaceBody(BaseModel):
    parent_path: str = Field(..., description="Absolute path to parent directory")
    name: str = Field(..., min_length=1, description="New folder name (single segment)")


async def _apply_and_persist(root: Path) -> str:
    state = get_app_state()
    try:
        s = apply_workspace_to_config(state.config, root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    save_persisted_workspace_path(s)
    new_store = LocalFileStore(s)
    state.file_store = new_store
    state._conversation_store = None  # noqa: SLF001
    runtime_orchestrator.drain_pooled_runtimes()
    cm = state.conversation_manager
    if cm is not None and hasattr(cm, "switch_workspace_root"):
        await cm.switch_workspace_root(new_store)
    return s


@router.get("")
async def get_workspace() -> dict:
    """Current project folder (``None`` until the user opens a workspace)."""
    path = get_effective_workspace_root()
    return {"path": str(path) if path is not None else None}


@router.post("")
async def set_workspace(body: WorkspacePathBody) -> dict:
    try:
        root = resolve_existing_directory(body.path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    s = await _apply_and_persist(root)
    return {"path": s, "ok": True}


@router.post("/create")
async def create_workspace(body: CreateWorkspaceBody) -> dict:
    parent = Path(body.parent_path).expanduser().resolve()
    if not parent.is_dir():
        raise HTTPException(
            status_code=400, detail="Parent path must be an existing directory"
        )
    name = body.name.strip().replace("\\", "/").split("/")[-1].strip()
    if not name or name in (".", ".."):
        raise HTTPException(status_code=400, detail="Invalid folder name")
    if any(sep in name for sep in ("/", "\\")):
        raise HTTPException(
            status_code=400, detail="Use a single folder name, not a path"
        )
    dest = parent / name
    if dest.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Already exists: {dest}",
        )
    try:
        dest.mkdir(parents=False)
    except OSError as e:
        raise HTTPException(
            status_code=400, detail=f"Could not create folder: {e}",
        ) from e
    s = await _apply_and_persist(dest)
    return {"path": s, "ok": True}
