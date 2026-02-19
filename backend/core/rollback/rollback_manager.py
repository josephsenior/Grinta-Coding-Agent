"""Rollback and checkpoint system for agent actions.

Allows creating snapshots before risky operations and rolling back
if something goes wrong.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.core.logger import forge_logger as logger


@dataclass
class Checkpoint:
    """Represents a saved state checkpoint."""

    id: str
    timestamp: float
    description: str
    checkpoint_type: str  # 'auto', 'manual', 'before_risky'
    workspace_path: str
    metadata: dict[str, Any] = field(default_factory=dict)
    git_commit_sha: str | None = None
    file_snapshots: dict[str, str] = field(default_factory=dict)  # path -> content hash

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        """Create from dictionary."""
        return cls(**data)


class RollbackManager:
    """Manages checkpoints and rollback operations for agent actions.

    Features:
    - Automatic checkpoints before risky operations
    - Manual checkpoint creation
    - Git-based snapshots (if available)
    - File-level snapshots
    - Rollback to any checkpoint
    - Cleanup of old checkpoints

    Example:
        ```python
        rollback = RollbackManager(workspace_path="/workspace")

        # Create checkpoint before risky operation
        checkpoint_id = rollback.create_checkpoint(
            "before_delete",
            checkpoint_type="before_risky"
        )

        # ... perform risky operation ...

        # Rollback if something went wrong
        if error:
            rollback.rollback_to(checkpoint_id)
        ```

    """

    def __init__(
        self,
        workspace_path: str,
        checkpoints_dir: str | None = None,
        max_checkpoints: int = 20,
        auto_cleanup: bool = True,
    ) -> None:
        """Initialize rollback manager.

        Args:
            workspace_path: Path to the workspace
            checkpoints_dir: Directory to store checkpoints (default: workspace_path/.Forge/checkpoints)
            max_checkpoints: Maximum number of checkpoints to keep
            auto_cleanup: Whether to automatically clean up old checkpoints

        """
        self.workspace_path = Path(workspace_path)
        self.checkpoints_dir = (
            Path(checkpoints_dir)
            if checkpoints_dir
            else self.workspace_path / ".Forge" / "checkpoints"
        )
        self.max_checkpoints = max_checkpoints
        self.auto_cleanup = auto_cleanup

        # Create checkpoints directory
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

        # Load existing checkpoints
        self.checkpoints: list[Checkpoint] = self._load_checkpoints()

        # Check if git is available
        self.vcs_available = self._check_git_available()

    def _check_git_available(self) -> bool:
        """Check if git is available and workspace is a git repo."""
        try:
            result = subprocess.run(
                ["git", "rev-parse", "--git-dir"],
                check=False,
                cwd=self.workspace_path,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _load_checkpoints(self) -> list[Checkpoint]:
        """Load existing checkpoints from disk."""
        checkpoints = []
        manifest_file = self.checkpoints_dir / "manifest.json"

        if manifest_file.exists():
            try:
                with open(manifest_file, encoding="utf-8") as f:
                    data = json.load(f)
                    checkpoints = [
                        Checkpoint.from_dict(cp) for cp in data.get("checkpoints", [])
                    ]
            except Exception as e:
                logger.warning("Failed to load checkpoints manifest: %s", e)

        return checkpoints

    def _save_checkpoints(self) -> None:
        """Save checkpoints manifest to disk."""
        manifest_file = self.checkpoints_dir / "manifest.json"

        try:
            data = {
                "checkpoints": [cp.to_dict() for cp in self.checkpoints],
                "last_updated": time.time(),
            }
            with open(manifest_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error("Failed to save checkpoints manifest: %s", e)

    def _generate_checkpoint_id(self) -> str:
        """Generate a unique checkpoint ID."""
        return f"cp_{int(time.time() * 1000)}_{os.urandom(4).hex()}"

    def _create_git_snapshot(self) -> str | None:
        """Create a git commit snapshot and return the SHA.

        Returns:
            Git commit SHA if successful, None otherwise

        """
        if not self.vcs_available:
            return None

        try:
            # Create a temporary commit
            subprocess.run(
                ["git", "add", "-A"],
                check=False,
                cwd=self.workspace_path,
                capture_output=True,
                timeout=30,
            )

            result = subprocess.run(
                [
                    "git",
                    "commit",
                    "-m",
                    "[Forge Checkpoint] Auto-snapshot",
                    "--allow-empty",
                ],
                check=False,
                cwd=self.workspace_path,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                # Get the commit SHA
                sha_result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    check=False,
                    cwd=self.workspace_path,
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                return sha_result.stdout.strip() if sha_result.returncode == 0 else None
        except Exception as e:
            logger.warning("Failed to create git snapshot: %s", e)

        return None

    def _create_file_snapshot(self, checkpoint_id: str) -> dict[str, str]:
        """Create file-level snapshots for the checkpoint.

        Args:
            checkpoint_id: ID of the checkpoint

        Returns:
            Dictionary mapping file paths to content hashes

        """
        snapshot_dir = self.checkpoints_dir / checkpoint_id
        snapshot_dir.mkdir(exist_ok=True)

        file_snapshots = {}

        try:
            # Copy workspace files to checkpoint directory
            for file_path in self.workspace_path.rglob("*"):
                if file_path.is_file():
                    # Skip .Forge directory and .git
                    if ".Forge" in file_path.parts or ".git" in file_path.parts:
                        continue

                    rel_path = file_path.relative_to(self.workspace_path)
                    dest_path = snapshot_dir / rel_path
                    dest_path.parent.mkdir(parents=True, exist_ok=True)

                    shutil.copy2(file_path, dest_path)
                    file_snapshots[str(rel_path)] = "saved"
        except Exception as e:
            logger.error("Failed to create file snapshot: %s", e)

        return file_snapshots

    def create_checkpoint(
        self,
        description: str,
        checkpoint_type: str = "manual",
        metadata: dict[str, Any] | None = None,
        use_git: bool = True,
    ) -> str:
        """Create a new checkpoint.

        Args:
            description: Human-readable description
            checkpoint_type: Type of checkpoint ('auto', 'manual', 'before_risky')
            metadata: Additional metadata to store
            use_git: Whether to use git for snapshot (if available)

        Returns:
            Checkpoint ID

        """
        checkpoint_id = self._generate_checkpoint_id()

        logger.info("Creating checkpoint: %s (ID: %s)", description, checkpoint_id)

        # Create git snapshot if available
        git_commit_sha = None
        if use_git and self.vcs_available:
            git_commit_sha = self._create_git_snapshot()

        # Create file snapshot as fallback or if git is not available
        file_snapshots = self._create_file_snapshot(checkpoint_id)

        # Create checkpoint object
        checkpoint = Checkpoint(
            id=checkpoint_id,
            timestamp=time.time(),
            description=description,
            checkpoint_type=checkpoint_type,
            workspace_path=str(self.workspace_path),
            metadata=metadata or {},
            git_commit_sha=git_commit_sha,
            file_snapshots=file_snapshots,
        )

        # Add to list
        self.checkpoints.append(checkpoint)

        # Save manifest
        self._save_checkpoints()

        # Auto-cleanup if enabled
        if self.auto_cleanup:
            self._cleanup_old_checkpoints()

        logger.info("Checkpoint created successfully: %s", checkpoint_id)

        return checkpoint_id

    def rollback_to(self, checkpoint_id: str) -> bool:
        """Rollback workspace to a specific checkpoint.

        Args:
            checkpoint_id: ID of the checkpoint to rollback to

        Returns:
            True if rollback was successful, False otherwise

        """
        checkpoint = self._find_checkpoint(checkpoint_id)
        if not checkpoint:
            return False

        logger.info(
            "Rolling back to checkpoint: %s (%s)", checkpoint.description, checkpoint_id
        )

        try:
            # Try git-based rollback first
            if self._try_git_rollback(checkpoint):
                return True

            # Fallback to file-based rollback
            return self._try_file_based_rollback(checkpoint_id)

        except Exception as e:
            logger.error("Rollback failed: %s", e)
            return False

    def _find_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        """Find a checkpoint by ID.

        Args:
            checkpoint_id: Checkpoint ID to find

        Returns:
            Checkpoint object or None if not found

        """
        checkpoint = next(
            (cp for cp in self.checkpoints if cp.id == checkpoint_id), None
        )
        if not checkpoint:
            logger.error("Checkpoint not found: %s", checkpoint_id)
        return checkpoint

    def _try_git_rollback(self, checkpoint: Checkpoint) -> bool:
        """Attempt to rollback using git reset.

        Args:
            checkpoint: Checkpoint containing git commit SHA

        Returns:
            True if git rollback succeeded, False otherwise

        """
        if not (checkpoint.git_commit_sha and self.vcs_available):
            return False

        result = subprocess.run(
            ["git", "reset", "--hard", checkpoint.git_commit_sha],
            check=False,
            cwd=self.workspace_path,
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            logger.info("Git rollback successful to %s", checkpoint.git_commit_sha)
            return True
        logger.warning("Git rollback failed: %s", result.stderr)
        return False

    def _try_file_based_rollback(self, checkpoint_id: str) -> bool:
        """Attempt to rollback using file snapshots.

        Args:
            checkpoint_id: Checkpoint ID to restore from

        Returns:
            True if file-based rollback succeeded, False otherwise

        """
        snapshot_dir = self.checkpoints_dir / checkpoint_id

        if not snapshot_dir.exists():
            logger.error("Checkpoint snapshot directory not found: %s", snapshot_dir)
            return False

        self._clear_workspace()
        self._restore_snapshot(snapshot_dir)

        logger.info("File-based rollback successful")
        return True

    def _clear_workspace(self) -> None:
        """Clear workspace directory (except .Forge and .git)."""
        for item in self.workspace_path.iterdir():
            if item.name not in [".Forge", ".git"]:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

    def _restore_snapshot(self, snapshot_dir: Path) -> None:
        """Restore files from snapshot directory.

        Args:
            snapshot_dir: Directory containing snapshot files

        """
        for file_path in snapshot_dir.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(snapshot_dir)
                dest_path = self.workspace_path / rel_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, dest_path)

    def list_checkpoints(self) -> list[dict[str, Any]]:
        """List all available checkpoints.

        Returns:
            List of checkpoint information dictionaries

        """
        return [
            {
                "id": cp.id,
                "description": cp.description,
                "timestamp": cp.timestamp,
                "datetime": datetime.fromtimestamp(cp.timestamp).isoformat(),
                "type": cp.checkpoint_type,
                "has_git_snapshot": cp.git_commit_sha is not None,
                "file_count": len(cp.file_snapshots),
            }
            for cp in sorted(self.checkpoints, key=lambda x: x.timestamp, reverse=True)
        ]

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        """Get a specific checkpoint by ID.

        Args:
            checkpoint_id: Checkpoint ID

        Returns:
            Checkpoint object or None if not found

        """
        return next((cp for cp in self.checkpoints if cp.id == checkpoint_id), None)

    def delete_checkpoint(self, checkpoint_id: str) -> bool:
        """Delete a specific checkpoint.

        Args:
            checkpoint_id: Checkpoint ID

        Returns:
            True if deleted, False if not found

        """
        checkpoint = self.get_checkpoint(checkpoint_id)

        if not checkpoint:
            return False

        # Remove from list
        self.checkpoints = [cp for cp in self.checkpoints if cp.id != checkpoint_id]

        # Delete snapshot directory
        snapshot_dir = self.checkpoints_dir / checkpoint_id
        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir)

        # Save manifest
        self._save_checkpoints()

        logger.info("Checkpoint deleted: %s", checkpoint_id)

        return True

    def _cleanup_old_checkpoints(self) -> None:
        """Remove old checkpoints to stay within max_checkpoints limit."""
        if len(self.checkpoints) <= self.max_checkpoints:
            return

        # Sort by timestamp (oldest first)
        sorted_checkpoints = sorted(self.checkpoints, key=lambda x: x.timestamp)

        # Keep only the most recent max_checkpoints
        to_delete = sorted_checkpoints[: len(sorted_checkpoints) - self.max_checkpoints]

        for checkpoint in to_delete:
            self.delete_checkpoint(checkpoint.id)

        logger.info("Cleaned up %s old checkpoints", len(to_delete))

    def get_latest_checkpoint(self) -> Checkpoint | None:
        """Get the most recent checkpoint.

        Returns:
            Most recent checkpoint or None if no checkpoints exist

        """
        if not self.checkpoints:
            return None

        return max(self.checkpoints, key=lambda x: x.timestamp)
