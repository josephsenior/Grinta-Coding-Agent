"""One-off cleanup for legacy project-local storage layouts."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console

from backend.core.workspace_resolution import (
    workspace_agent_state_dir,
    workspace_grinta_root,
)
from backend.persistence.locations import get_project_local_data_root


@dataclass(frozen=True)
class _MigrationSpec:
    source: Path
    destination: Path
    ignored_names: frozenset[str] = frozenset()


@dataclass
class StorageCleanupReport:
    project_root: Path
    canonical_root: Path
    migrated_entries: int = 0
    removed_duplicates: int = 0
    archived_conflicts: int = 0
    removed_empty_dirs: int = 0
    touched_sources: list[Path] = field(default_factory=list)

    @property
    def conflict_root(self) -> Path:
        return self.canonical_root / '_cleanup_conflicts'

    @property
    def touched_source_count(self) -> int:
        return len(self.touched_sources)

    @property
    def had_changes(self) -> bool:
        return any(
            (
                self.migrated_entries,
                self.removed_duplicates,
                self.archived_conflicts,
                self.removed_empty_dirs,
            )
        )


def cleanup_project_storage(project_root: str | Path) -> StorageCleanupReport:
    """Consolidate legacy project data into workspace-keyed storage under ``~/.grinta/workspaces/<id>/storage``."""
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        msg = f'Project directory does not exist: {root}'
        raise ValueError(msg)

    canonical_root = Path(get_project_local_data_root(root))
    canonical_root.mkdir(parents=True, exist_ok=True)
    report = StorageCleanupReport(project_root=root, canonical_root=canonical_root)

    for spec in _migration_specs(root, canonical_root):
        if not spec.source.exists():
            continue
        report.touched_sources.append(spec.source)
        _merge_directory(
            spec.source,
            spec.destination,
            report,
            ignored_names=spec.ignored_names,
        )

    for candidate in _prunable_directories(root):
        _prune_empty_branch(candidate, root, report)

    return report


def run_storage_cleanup_command(
    project: str | None = None,
    *,
    console: Console | None = None,
) -> int:
    """Run storage cleanup and print a concise summary."""
    active_console = console or Console()
    resolved_project = (
        Path(project).expanduser().resolve() if project else Path.cwd().resolve()
    )
    try:
        report = cleanup_project_storage(resolved_project)
    except ValueError as exc:
        active_console.print(f'[red]{exc}[/red]')
        return 2

    if not report.touched_sources:
        active_console.print(
            f'[dim]No legacy project data found. Canonical storage root: {report.canonical_root}[/dim]'
        )
        return 0

    active_console.print('[bold green]Project storage cleanup complete.[/bold green]')
    active_console.print(f'Project: [cyan]{report.project_root}[/cyan]')
    active_console.print(f'Canonical root: [cyan]{report.canonical_root}[/cyan]')
    active_console.print(
        'Migrated entries: '
        f'[bold]{report.migrated_entries}[/bold]  '
        'Removed duplicates: '
        f'[bold]{report.removed_duplicates}[/bold]  '
        'Archived conflicts: '
        f'[bold]{report.archived_conflicts}[/bold]'
    )
    if report.archived_conflicts:
        active_console.print(
            f'[yellow]Conflicts were archived under {report.conflict_root}[/yellow]'
        )
    return 0


def _migration_specs(
    project_root: Path, canonical_root: Path
) -> tuple[_MigrationSpec, ...]:
    agent_root = workspace_agent_state_dir(project_root)
    bucket_root = workspace_grinta_root(project_root)
    return (
        _MigrationSpec(
            project_root / '.grinta' / 'conversations' / 'oss_user',
            canonical_root / 'users' / 'oss_user' / 'conversations',
        ),
        _MigrationSpec(
            project_root / 'storage' / '.grinta' / 'conversations' / 'oss_user',
            canonical_root / 'users' / 'oss_user' / 'conversations',
        ),
        _MigrationSpec(
            project_root / '.grinta' / 'conversations',
            canonical_root / 'sessions',
            ignored_names=frozenset({'oss_user'}),
        ),
        _MigrationSpec(
            project_root / '.grinta' / 'playbooks',
            bucket_root / 'playbooks',
        ),
        _MigrationSpec(
            project_root / '.grinta' / 'checkpoints',
            agent_root / 'rollback_checkpoints',
        ),
        _MigrationSpec(
            project_root / '.grinta' / 'context.md',
            bucket_root / 'project_context' / 'context.md',
        ),
        _MigrationSpec(
            project_root / '.grinta' / 'changelog.jsonl',
            bucket_root / 'project_context' / 'changelog.jsonl',
        ),
        _MigrationSpec(
            project_root / '.grinta' / '.gitignore',
            bucket_root / 'project_context' / '.gitignore',
        ),
        _MigrationSpec(
            project_root / '.grinta',
            agent_root,
            ignored_names=frozenset(
                {
                    'conversations',
                    'checkpoints',
                    'playbooks',
                    'context.md',
                    'changelog.jsonl',
                    '.gitignore',
                }
            ),
        ),
        _MigrationSpec(
            project_root / 'storage' / '.grinta' / 'conversations',
            canonical_root / 'sessions',
            ignored_names=frozenset({'oss_user'}),
        ),
        _MigrationSpec(
            project_root / 'storage' / '.grinta' / 'playbooks',
            bucket_root / 'playbooks',
        ),
        _MigrationSpec(
            project_root / 'storage' / '.grinta' / 'checkpoints',
            agent_root / 'rollback_checkpoints',
        ),
        _MigrationSpec(
            project_root / 'storage' / '.grinta',
            agent_root,
            ignored_names=frozenset({'conversations', 'checkpoints', 'playbooks'}),
        ),
        _MigrationSpec(
            project_root / 'storage' / '.jwt_secret',
            canonical_root / '.jwt_secret',
        ),
        _MigrationSpec(project_root / 'sessions', canonical_root / 'sessions'),
        _MigrationSpec(project_root / 'users', canonical_root / 'users'),
        _MigrationSpec(
            project_root / 'storage' / 'sessions', canonical_root / 'sessions'
        ),
        _MigrationSpec(project_root / 'storage' / 'users', canonical_root / 'users'),
    )


def _merge_directory(
    source: Path,
    destination: Path,
    report: StorageCleanupReport,
    *,
    ignored_names: frozenset[str] = frozenset(),
) -> None:
    if not source.exists():
        return

    if source.is_file():
        _merge_file(source, destination, report)
        return

    if destination.exists() and destination.is_file():
        _archive_conflict(source, report, reason='destination-file')
        return

    destination.mkdir(parents=True, exist_ok=True)
    for child in list(source.iterdir()):
        if child.name in ignored_names:
            continue
        _merge_directory(child, destination / child.name, report)
    _remove_dir_if_empty(source, report)


def _merge_file(source: Path, destination: Path, report: StorageCleanupReport) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists():
        shutil.move(str(source), str(destination))
        report.migrated_entries += 1
        return

    if destination.is_file() and _same_file_contents(source, destination):
        source.unlink()
        report.removed_duplicates += 1
        return

    _archive_conflict(source, report, reason='content-conflict')


def _archive_conflict(
    source: Path, report: StorageCleanupReport, *, reason: str
) -> None:
    archive_root = report.conflict_root / reason
    relative = source.relative_to(report.project_root)
    destination = _dedupe_path(archive_root / relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))
    report.archived_conflicts += 1


def _dedupe_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    counter = 1
    while True:
        candidate = parent / f'{stem}.{counter}{suffix}'
        if not candidate.exists():
            return candidate
        counter += 1


def _same_file_contents(left: Path, right: Path) -> bool:
    if left.stat().st_size != right.stat().st_size:
        return False
    return _sha256(left) == _sha256(right)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(65536), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_dir_if_empty(path: Path, report: StorageCleanupReport) -> None:
    if path.is_dir() and not any(path.iterdir()):
        path.rmdir()
        report.removed_empty_dirs += 1


def _prune_empty_branch(
    path: Path, stop_at: Path, report: StorageCleanupReport
) -> None:
    current = path
    while current != stop_at and current.exists() and current.is_dir():
        if any(current.iterdir()):
            return
        current.rmdir()
        report.removed_empty_dirs += 1
        current = current.parent


def _prunable_directories(project_root: Path) -> tuple[Path, ...]:
    return (
        project_root / 'sessions',
        project_root / 'users',
        project_root / 'storage' / 'sessions',
        project_root / 'storage' / 'users',
        project_root / 'storage' / '.grinta' / 'conversations' / 'oss_user',
        project_root / 'storage' / '.grinta' / 'conversations',
        project_root / 'storage' / '.grinta',
        project_root / 'storage',
        project_root / '.grinta' / 'conversations' / 'oss_user',
        project_root / '.grinta' / 'conversations',
        project_root / '.grinta',
    )
