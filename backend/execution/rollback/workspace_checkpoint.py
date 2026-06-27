"""Manifest-based workspace checkpoint save/restore helpers."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from backend.core.logging.logger import app_logger as logger

_MANIFEST_VERSION = 1
_MANIFEST_FILENAME = 'manifest.json'
_FILES_DIRNAME = 'files'
_RESERVED_ROOTS = frozenset({'.git', '.grinta'})


@dataclass
class WorkspaceCheckpointFile:
    """File entry stored in a workspace checkpoint manifest."""

    path: str
    size: int
    mtime_ns: int


@dataclass
class WorkspaceCheckpointManifest:
    """Manifest describing a checkpointed workspace snapshot."""

    version: int = _MANIFEST_VERSION
    created_at: float = 0.0
    label: str = ''
    metadata: dict[str, Any] = field(default_factory=dict)
    files: list[WorkspaceCheckpointFile] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'version': self.version,
            'created_at': self.created_at,
            'label': self.label,
            'metadata': self.metadata,
            'files': [asdict(entry) for entry in self.files],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkspaceCheckpointManifest:
        raw_files = data.get('files') or []
        files = [
            WorkspaceCheckpointFile(
                path=str(item.get('path', '')),
                size=int(item.get('size', 0)),
                mtime_ns=int(item.get('mtime_ns', 0)),
            )
            for item in raw_files
            if isinstance(item, dict) and item.get('path')
        ]
        metadata = data.get('metadata')
        return cls(
            version=int(data.get('version', _MANIFEST_VERSION)),
            created_at=float(data.get('created_at', 0.0)),
            label=str(data.get('label', '')),
            metadata=metadata if isinstance(metadata, dict) else {},
            files=files,
        )


def save_checkpoint(
    workspace_path: str | Path,
    checkpoint_dir: str | Path,
    *,
    label: str = '',
    metadata: dict[str, Any] | None = None,
) -> WorkspaceCheckpointManifest:
    """Persist a manifest-first workspace checkpoint."""
    workspace_root = Path(workspace_path).resolve()
    checkpoint_root = Path(checkpoint_dir)
    files_root = checkpoint_root / _FILES_DIRNAME
    files_root.mkdir(parents=True, exist_ok=True)

    manifest = WorkspaceCheckpointManifest(
        created_at=time.time(),
        label=label,
        metadata=metadata or {},
    )

    for file_path in _iter_workspace_files(workspace_root):
        rel_path = file_path.relative_to(workspace_root)
        dest_path = files_root / rel_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(file_path, dest_path)
        stat = file_path.stat()
        manifest.files.append(
            WorkspaceCheckpointFile(
                path=rel_path.as_posix(),
                size=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            )
        )

    _atomic_write_json(checkpoint_root / _MANIFEST_FILENAME, manifest.to_dict())
    return manifest


def restore_checkpoint(
    workspace_path: str | Path,
    checkpoint_dir: str | Path,
    *,
    quarantine_dir: str | Path | None = None,
) -> Path | None:
    """Restore a manifest-based workspace checkpoint.

    Extra files not present in the checkpoint are moved into a quarantine
    directory instead of being deleted.
    """
    workspace_root = Path(workspace_path).resolve()
    checkpoint_root = Path(checkpoint_dir)
    manifest = load_checkpoint_manifest(checkpoint_root)
    source_root = checkpoint_root / _FILES_DIRNAME
    snapshot_files: set[Path]

    if manifest is not None and source_root.exists():
        snapshot_files = {
            _safe_relative_path(Path(entry.path), workspace_root)
            for entry in manifest.files
        }
    else:
        # Backward compatibility for legacy flat snapshots.
        source_root = checkpoint_root
        snapshot_files = _legacy_snapshot_files(source_root, workspace_root)

    created_quarantine_dir = _quarantine_workspace_extras(
        workspace_root,
        checkpoint_root,
        snapshot_files,
        (
            Path(quarantine_dir)
            if quarantine_dir is not None
            else checkpoint_root.parent
            / f'{checkpoint_root.name}_restore_quarantine_{int(time.time())}'
        ),
    )

    for rel_path in sorted(snapshot_files):
        source_path = source_root / rel_path
        if not source_path.exists() or not source_path.is_file():
            logger.warning(
                'Skipping missing checkpoint file during restore: %s', source_path
            )
            continue
        dest_path = workspace_root / rel_path
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_copy_file(source_path, dest_path)

    return created_quarantine_dir


def load_checkpoint_manifest(
    checkpoint_dir: str | Path,
) -> WorkspaceCheckpointManifest | None:
    """Load a checkpoint manifest if present and valid."""
    manifest_path = Path(checkpoint_dir) / _MANIFEST_FILENAME
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning(
            'Failed to load workspace checkpoint manifest %s: %s', manifest_path, exc
        )
        return None
    if not isinstance(data, dict):
        return None
    return WorkspaceCheckpointManifest.from_dict(data)


def _iter_workspace_files(workspace_root: Path):
    from backend.engine.tools.ignore_filter import (
        get_ignore_spec,
        is_ignored_file,
        prune_ignored_dirs,
    )

    root = str(workspace_root)
    spec = get_ignore_spec(root)
    for dirpath, dirnames, filenames in os.walk(root):
        prune_ignored_dirs(root, dirpath, dirnames, spec)
        for name in filenames:
            if is_ignored_file(root, dirpath, name, spec):
                continue
            file_path = Path(dirpath) / name
            if file_path.is_symlink():
                continue
            rel_path = file_path.relative_to(workspace_root)
            if _is_reserved_relative_path(rel_path):
                continue
            yield file_path


def _legacy_snapshot_files(snapshot_root: Path, workspace_root: Path) -> set[Path]:
    rel_paths: set[Path] = set()
    for file_path in snapshot_root.rglob('*'):
        if not file_path.is_file():
            continue
        rel_path = file_path.relative_to(snapshot_root)
        if rel_path.name == _MANIFEST_FILENAME:
            continue
        try:
            rel_paths.add(_safe_relative_path(rel_path, workspace_root))
        except ValueError:
            logger.warning('Skipping unsafe legacy checkpoint path: %s', rel_path)
    return rel_paths


def _quarantine_workspace_extras(
    workspace_root: Path,
    checkpoint_root: Path,
    snapshot_files: set[Path],
    quarantine_dir: Path | None,
) -> Path | None:
    created_quarantine_dir = quarantine_dir

    for item in sorted(
        workspace_root.rglob('*'), key=lambda p: len(p.parts), reverse=True
    ):
        if not item.exists() or _is_reserved_workspace_path(
            item, workspace_root, checkpoint_root
        ):
            continue
        rel_path = item.relative_to(workspace_root)

        if item.is_dir():
            if rel_path in snapshot_files:
                created_quarantine_dir = _move_to_quarantine(
                    item,
                    rel_path,
                    created_quarantine_dir,
                )
                continue
            if any(rel_path in saved.parents for saved in snapshot_files):
                continue
            created_quarantine_dir = _move_to_quarantine(
                item,
                rel_path,
                created_quarantine_dir,
            )
            continue

        if rel_path not in snapshot_files:
            created_quarantine_dir = _move_to_quarantine(
                item,
                rel_path,
                created_quarantine_dir,
            )

    return created_quarantine_dir


def _move_to_quarantine(
    source_path: Path,
    rel_path: Path,
    quarantine_dir: Path | None,
) -> Path:
    if quarantine_dir is None:
        quarantine_dir = source_path.parent / f'.restore_quarantine_{int(time.time())}'
        quarantine_dir.mkdir(parents=True, exist_ok=True)
    else:
        quarantine_dir.mkdir(parents=True, exist_ok=True)
    target = quarantine_dir / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target = target.with_name(f'{target.name}.{int(time.time() * 1000)}')
    shutil.move(str(source_path), str(target))
    return quarantine_dir


def _is_reserved_workspace_path(
    path: Path, workspace_root: Path, checkpoint_root: Path
) -> bool:
    try:
        rel_path = path.resolve().relative_to(workspace_root)
    except ValueError:
        return True
    if _is_reserved_relative_path(rel_path):
        return True

    resolved = path.resolve()
    checkpoint_root = checkpoint_root.resolve()
    try:
        resolved.relative_to(checkpoint_root)
        return True
    except ValueError:
        pass
    try:
        checkpoint_root.relative_to(resolved)
        return True
    except ValueError:
        return False


def _is_reserved_relative_path(rel_path: Path) -> bool:
    return bool(rel_path.parts) and rel_path.parts[0] in _RESERVED_ROOTS


def _safe_relative_path(rel_path: Path, workspace_root: Path) -> Path:
    resolved = (workspace_root / rel_path).resolve()
    try:
        resolved.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError(f'unsafe checkpoint path: {rel_path}') from exc
    return rel_path


def _atomic_copy_file(source_path: Path, dest_path: Path) -> None:
    fd, temp_name = tempfile.mkstemp(
        prefix=f'.{dest_path.name}.',
        suffix='.tmp',
        dir=str(dest_path.parent),
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        shutil.copy2(source_path, temp_path)
        os.replace(temp_path, dest_path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(
        prefix=f'.{path.name}.',
        suffix='.tmp',
        dir=str(path.parent),
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True),
            encoding='utf-8',
        )
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


__all__ = [
    'WorkspaceCheckpointFile',
    'WorkspaceCheckpointManifest',
    'load_checkpoint_manifest',
    'restore_checkpoint',
    'save_checkpoint',
]
