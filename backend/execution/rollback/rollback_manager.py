"""Rollback and checkpoint system for agent actions.

Allows creating snapshots before risky operations and rolling back
if something goes wrong.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.core.logging.logger import app_logger as logger
from backend.core.workspace_resolution import workspace_agent_state_dir
from backend.execution.rollback.shadow_repo import ShadowRepo, ShadowRepoError



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
    # Tier distinguishes user-visible checkpoints (tier=2, 'manual') from
    # system-generated transaction snapshots (tier=1, 'before_risky' etc.).
    tier: int = 2

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Checkpoint:
        """Create from dictionary, tolerating old manifests without 'tier'."""
        known = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


class RollbackManager:
    """Manages checkpoints and rollback operations for agent actions.

    Features:
    - Automatic checkpoints before risky operations
    - Manual checkpoint creation
    - pygit2-backed shadow-repo snapshots (always available, no system git needed)
    - Rollback to any checkpoint
    - Cleanup of old checkpoints

    The checkpoint backend is a private bare git object-store (``ShadowRepo``)
    maintained entirely via pygit2 inside ``.grinta/shadow_repo/``.  It is
    completely independent of any ``.git`` the workspace may have, requires no
    system ``git`` binary, and works identically on Windows, macOS and Linux.

    Example::

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

    """

    def __init__(
        self,
        workspace_path: str,
        checkpoints_dir: str | None = None,
        max_checkpoints: int = 20,
        auto_cleanup: bool = True,
        allow_destructive_git_rollback: bool | None = None,
    ) -> None:
        """Initialize rollback manager.

        Args:
            workspace_path: Path to the workspace.
            checkpoints_dir: Directory to store the checkpoint manifest
                (default: ``<workspace>/.grinta/rollback_checkpoints``).
            max_checkpoints: Maximum number of checkpoints to keep.
            auto_cleanup: Whether to automatically clean up old checkpoints.
            allow_destructive_git_rollback: Unused; kept for API compatibility
                with existing call-sites.  Has no effect -- the shadow-repo
                approach is inherently non-destructive.

        """
        self.workspace_path = Path(workspace_path)
        self.checkpoints_dir = (
            Path(checkpoints_dir)
            if checkpoints_dir
            else workspace_agent_state_dir(self.workspace_path) / 'rollback_checkpoints'
        )
        self.max_checkpoints = max_checkpoints
        self.auto_cleanup = auto_cleanup
        # Retained for API compat -- has no effect with the shadow-repo backend.
        self.allow_destructive_git_rollback = bool(allow_destructive_git_rollback or False)

        # Create checkpoints directory
        self.checkpoints_dir.mkdir(parents=True, exist_ok=True)

        # Load existing checkpoints
        self.checkpoints: list[Checkpoint] = self._load_checkpoints()

        # Track the latest checkpoint timestamp to avoid ties on platforms where
        # time.time() resolution is coarse.
        self._last_checkpoint_ts: float = max(
            (cp.timestamp for cp in self.checkpoints),
            default=0.0,
        )

        # Initialise the shadow repo (pygit2, no subprocess).
        # pygit2 is a hard dependency -- if it is missing or the shadow repo
        # cannot be initialised the exception propagates to the caller.
        self._shadow_repo = ShadowRepo(workspace_root=self.workspace_path)

        # vcs_available kept for API compatibility with existing call-sites.
        self.vcs_available: bool = True

    def _load_checkpoints(self) -> list[Checkpoint]:
        """Load existing checkpoints from disk."""
        checkpoints = []
        manifest_file = self.checkpoints_dir / 'manifest.json'

        if manifest_file.exists():
            try:
                with open(manifest_file, encoding='utf-8') as f:
                    data = json.load(f)
                    checkpoints = [
                        Checkpoint.from_dict(cp) for cp in data.get('checkpoints', [])
                    ]
            except Exception as e:
                logger.warning('Failed to load checkpoints manifest: %s', e)

        return checkpoints

    def _save_checkpoints(self) -> None:
        """Save checkpoints manifest to disk."""
        manifest_file = self.checkpoints_dir / 'manifest.json'

        try:
            data = {
                'checkpoints': [cp.to_dict() for cp in self.checkpoints],
                'last_updated': time.time(),
            }
            fd, temp_name = tempfile.mkstemp(
                prefix=f'.{manifest_file.name}.',
                suffix='.tmp',
                dir=str(manifest_file.parent),
            )
            os.close(fd)
            temp_path = Path(temp_name)
            try:
                with open(temp_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, indent=2)
                os.replace(temp_path, manifest_file)
            finally:
                if temp_path.exists():
                    temp_path.unlink(missing_ok=True)
        except Exception as e:
            logger.error('Failed to save checkpoints manifest: %s', e)

    def _generate_checkpoint_id(self) -> str:
        """Generate a unique checkpoint ID."""
        return f'cp_{int(time.time() * 1000)}_{os.urandom(4).hex()}'

    def _create_shadow_snapshot(self, label: str) -> str:
        """Create a shadow-repo snapshot via pygit2 and return the commit SHA.

        Uses the ``ShadowRepo`` engine: an in-process bare git object-store
        located in ``.grinta/shadow_repo/``.  No subprocess is spawned.  The
        stat-cache skips re-hashing files that have not changed since the last
        snapshot, making incremental checkpoints very fast.

        Returns:
            Commit SHA string (40 hex chars).

        Raises:
            ShadowRepoError: If the pygit2 snapshot fails.

        """
        return self._shadow_repo.snapshot(label=label)

    def create_checkpoint(
        self,
        description: str,
        checkpoint_type: str = 'manual',
        metadata: dict[str, Any] | None = None,
        use_git: bool = True,  # noqa: ARG002 -- kept for API compat; shadow repo always used
        tier: int = 2,
    ) -> str:
        """Create a new checkpoint.

        The checkpoint is backed by the ``ShadowRepo`` engine (pygit2, in-process,
        zero subprocess).  The ``use_git`` parameter is accepted for API
        compatibility with existing call-sites but has no effect.

        Args:
            description: Human-readable description.
            checkpoint_type: Type of checkpoint ('auto', 'manual', 'before_risky',
                'phase_boundary', etc.).
            metadata: Additional metadata to store.
            use_git: Accepted for API compatibility; has no effect.
            tier: Visibility tier.  2 = user-visible manual snapshot (default).
                  1 = system transaction (hidden from /checkpoint list by default).

        Returns:
            Checkpoint ID string.

        Raises:
            ShadowRepoError: If the shadow-repo snapshot fails.

        """
        checkpoint_id = self._generate_checkpoint_id()
        # Use a monotonic-increasing wall-clock timestamp to make ordering stable.
        checkpoint_ts = time.time()
        if checkpoint_ts <= self._last_checkpoint_ts:
            checkpoint_ts = self._last_checkpoint_ts + 1e-6
        self._last_checkpoint_ts = checkpoint_ts

        logger.info('Creating checkpoint: %s (ID: %s)', description, checkpoint_id)

        # Phase-boundary checkpoints skip the snapshot -- they record a lifecycle
        # transition marker only, not workspace content.
        if checkpoint_type == 'phase_boundary':
            shadow_sha: str | None = None
        else:
            shadow_sha = self._create_shadow_snapshot(label=description)

        # Create checkpoint object.  The shadow commit SHA is stored in the
        # existing ``git_commit_sha`` field so old manifests stay compatible.
        checkpoint = Checkpoint(
            id=checkpoint_id,
            timestamp=checkpoint_ts,
            description=description,
            checkpoint_type=checkpoint_type,
            workspace_path=str(self.workspace_path),
            metadata=metadata or {},
            git_commit_sha=shadow_sha,
            file_snapshots={},
            tier=tier,
        )

        # Add to list
        self.checkpoints.append(checkpoint)

        # Save manifest
        self._save_checkpoints()

        # Auto-cleanup if enabled
        if self.auto_cleanup:
            self._cleanup_old_checkpoints()

        logger.info('Checkpoint created successfully: %s', checkpoint_id)

        return checkpoint_id

    def rollback_to(self, checkpoint_id: str) -> bool:
        """Rollback workspace to a specific checkpoint.

        Args:
            checkpoint_id: ID of the checkpoint to rollback to.

        Returns:
            ``True`` if rollback was successful, ``False`` otherwise.

        """
        checkpoint = self._find_checkpoint(checkpoint_id)
        if not checkpoint:
            return False

        logger.info(
            'Rolling back to checkpoint: %s (%s)', checkpoint.description, checkpoint_id
        )

        try:
            return self._try_shadow_rollback(checkpoint)
        except Exception as e:
            logger.error('Rollback failed: %s', e)
            return False

    def _find_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        """Find a checkpoint by ID.

        Args:
            checkpoint_id: Checkpoint ID to find.

        Returns:
            Checkpoint object or None if not found.

        """
        checkpoint = next(
            (cp for cp in self.checkpoints if cp.id == checkpoint_id), None
        )
        if not checkpoint:
            logger.error('Checkpoint not found: %s', checkpoint_id)
        return checkpoint

    def _try_shadow_rollback(self, checkpoint: Checkpoint) -> bool:
        """Restore workspace from the shadow-repo commit recorded in *checkpoint*.

        Args:
            checkpoint: Checkpoint whose ``git_commit_sha`` holds a shadow SHA.

        Returns:
            ``True`` if the shadow restore succeeded, ``False`` if the checkpoint
            has no SHA (e.g. a phase-boundary marker).

        Raises:
            ShadowRepoError: If the shadow restore encounters a pygit2 error.

        """
        if not checkpoint.git_commit_sha:
            logger.warning(
                'Checkpoint %s has no snapshot SHA (phase-boundary marker); nothing to restore.',
                checkpoint.id,
            )
            return False

        quarantine_dir = (
            self.checkpoints_dir
            / f'{checkpoint.id}_restore_quarantine_{int(time.time())}'
        )
        self._shadow_repo.restore(
            checkpoint.git_commit_sha,
            quarantine_dir=quarantine_dir,
        )
        logger.info(
            'Shadow-repo restore successful from commit %s',
            checkpoint.git_commit_sha,
        )
        return True

    def _snapshot_relative_files(self, snapshot_dir: Path) -> set[Path]:
        """Return validated relative file paths present in a snapshot."""
        rel_paths: set[Path] = set()
        workspace_root = self.workspace_path.resolve()
        for file_path in snapshot_dir.rglob('*'):
            if not file_path.is_file():
                continue
            rel_path = file_path.relative_to(snapshot_dir)
            try:
                (workspace_root / rel_path).resolve().relative_to(workspace_root)
            except ValueError:
                logger.warning(
                    'Skipping unsafe snapshot path during rollback: %s', rel_path
                )
                continue
            rel_paths.add(rel_path)
        return rel_paths

    def _is_reserved_workspace_path(self, path: Path) -> bool:
        """Return True for workspace metadata paths that rollback must not move."""
        workspace_root = self.workspace_path.resolve()
        try:
            rel_path = path.resolve().relative_to(workspace_root)
        except ValueError:
            return True
        if not rel_path.parts:
            return True
        if rel_path.parts[0] in {'.grinta', '.git'}:
            return True

        try:
            checkpoints_root = self.checkpoints_dir.resolve()
        except OSError:
            checkpoints_root = self.checkpoints_dir
        resolved = path.resolve()
        try:
            resolved.relative_to(checkpoints_root)
            return True
        except ValueError:
            pass
        try:
            checkpoints_root.relative_to(resolved)
            return True
        except ValueError:
            return False

    def _quarantine_workspace_extras(
        self,
        checkpoint_id: str,
        snapshot_files: set[Path],
    ) -> Path | None:
        """Move files not present in the snapshot aside instead of deleting them."""
        quarantine_dir: Path | None = None

        for item in sorted(
            self.workspace_path.rglob('*'),
            key=lambda p: len(p.parts),
            reverse=True,
        ):
            if not item.exists() or self._is_reserved_workspace_path(item):
                continue
            rel_path = item.relative_to(self.workspace_path)

            if item.is_dir():
                if rel_path in snapshot_files:
                    quarantine_dir = self._move_to_restore_quarantine(
                        item,
                        rel_path,
                        checkpoint_id,
                        quarantine_dir,
                    )
                    continue
                has_snapshot_child = any(
                    rel_path in saved.parents for saved in snapshot_files
                )
                if has_snapshot_child:
                    continue
                quarantine_dir = self._move_to_restore_quarantine(
                    item,
                    rel_path,
                    checkpoint_id,
                    quarantine_dir,
                )
                continue

            if rel_path not in snapshot_files:
                quarantine_dir = self._move_to_restore_quarantine(
                    item,
                    rel_path,
                    checkpoint_id,
                    quarantine_dir,
                )

        return quarantine_dir

    def _move_to_restore_quarantine(
        self,
        path: Path,
        rel_path: Path,
        checkpoint_id: str,
        quarantine_dir: Path | None,
    ) -> Path:
        """Move a rollback extra/conflict into a checkpoint-local quarantine."""
        if quarantine_dir is None:
            quarantine_dir = (
                self.checkpoints_dir
                / f'{checkpoint_id}_restore_quarantine_{int(time.time())}'
            )
            quarantine_dir.mkdir(parents=True, exist_ok=True)
        target = quarantine_dir / rel_path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target = target.with_name(f'{target.name}.{int(time.time() * 1000)}')
        shutil.move(str(path), str(target))
        return quarantine_dir

    def _clear_workspace(self) -> None:
        """Clear workspace directory (except .grinta and .git)."""
        for item in self.workspace_path.iterdir():
            if item.name not in ['.grinta', '.git']:
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

    def _restore_snapshot(self, snapshot_dir: Path) -> None:
        """Restore files from snapshot directory.

        Args:
            snapshot_dir: Directory containing snapshot files

        """
        for file_path in snapshot_dir.rglob('*'):
            if file_path.is_file():
                rel_path = file_path.relative_to(snapshot_dir)
                dest_path = self.workspace_path / rel_path
                dest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file_path, dest_path)

    def list_checkpoints(
        self,
        *,
        tier: int | None = None,
    ) -> list[dict[str, Any]]:
        """List available checkpoints, optionally filtered by tier.

        Args:
            tier: If provided, only return checkpoints at this tier level.
                  Tier 1 = system transactions (before_risky etc.).
                  Tier 2 = user-visible manual snapshots (default shown in CLI).
                  ``None`` returns all tiers.

        Returns:
            List of checkpoint information dictionaries

        """
        checkpoints = self.checkpoints
        if tier is not None:
            checkpoints = [cp for cp in checkpoints if cp.tier == tier]
        return [
            {
                'id': cp.id,
                'description': cp.description,
                'timestamp': cp.timestamp,
                'datetime': datetime.fromtimestamp(cp.timestamp).isoformat(),
                'type': cp.checkpoint_type,
                'tier': cp.tier,
                'has_git_snapshot': cp.git_commit_sha is not None,
                'git_commit_sha': cp.git_commit_sha,
                'file_count': len(cp.file_snapshots),
            }
            for cp in sorted(checkpoints, key=lambda x: x.timestamp, reverse=True)
        ]

    def get_checkpoint(self, checkpoint_id: str) -> Checkpoint | None:
        """Get a specific checkpoint by ID.

        Args:
            checkpoint_id: Checkpoint ID

        Returns:
            Checkpoint object or None if not found

        """
        return next((cp for cp in self.checkpoints if cp.id == checkpoint_id), None)

    def get_checkpoint_files(self, checkpoint_id: str) -> list[str]:
        """Get list of files tracked by a checkpoint.

        Args:
            checkpoint_id: Checkpoint ID

        Returns:
            List of file paths in the checkpoint snapshot
        """
        checkpoint = self.get_checkpoint(checkpoint_id)
        if checkpoint is None:
            return []
        return list(checkpoint.file_snapshots.keys())

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

        logger.info('Checkpoint deleted: %s', checkpoint_id)

        return True

    # Checkpoint types that should never be auto-evicted to free space.
    # ``before_destructive`` records a known-dangerous shell command; losing
    # it would defeat the purpose of recording it in the first place.
    # ``phase_boundary`` records a lifecycle transition snapshot.
    PROTECTED_CHECKPOINT_TYPES = frozenset({'before_destructive', 'phase_boundary'})

    def _cleanup_old_checkpoints(self) -> None:
        """Remove old checkpoints to stay within max_checkpoints limit.

        ``PROTECTED_CHECKPOINT_TYPES`` (e.g. ``before_destructive``,
        ``phase_boundary``) are always kept regardless of age.
        """
        if len(self.checkpoints) <= self.max_checkpoints:
            return

        evictable = [
            cp
            for cp in self.checkpoints
            if cp.checkpoint_type not in self.PROTECTED_CHECKPOINT_TYPES
        ]
        protected_count = len(self.checkpoints) - len(evictable)
        # Allow at most max_checkpoints rows total; protected ones eat into
        # the budget but are never themselves evicted.
        keep_evictable = max(0, self.max_checkpoints - protected_count)
        if len(evictable) <= keep_evictable:
            return

        sorted_evictable = sorted(evictable, key=lambda x: x.timestamp)
        to_delete = sorted_evictable[: len(sorted_evictable) - keep_evictable]

        for checkpoint in to_delete:
            self.delete_checkpoint(checkpoint.id)

        logger.info(
            'Cleaned up %s old checkpoints (kept %s protected)',
            len(to_delete),
            protected_count,
        )

    def get_latest_checkpoint(self) -> Checkpoint | None:
        """Get the most recent checkpoint.

        Returns:
            Most recent checkpoint or None if no checkpoints exist

        """
        if not self.checkpoints:
            return None

        return max(self.checkpoints, key=lambda x: x.timestamp)
