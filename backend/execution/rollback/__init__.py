"""Rollback and checkpoint system for safe agent operations."""

from backend.execution.rollback.rollback_manager import Checkpoint, RollbackManager
from backend.execution.rollback.workspace_checkpoint import (
    WorkspaceCheckpointManifest,
    load_checkpoint_manifest,
    restore_checkpoint,
    save_checkpoint,
)

__all__ = [
    'Checkpoint',
    'RollbackManager',
    'WorkspaceCheckpointManifest',
    'load_checkpoint_manifest',
    'restore_checkpoint',
    'save_checkpoint',
]
