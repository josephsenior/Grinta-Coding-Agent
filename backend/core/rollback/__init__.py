"""Rollback and checkpoint system for safe agent operations."""

from backend.core.rollback.rollback_manager import Checkpoint, RollbackManager

Snapshot = Checkpoint

__all__ = ["Checkpoint", "Snapshot", "RollbackManager"]
