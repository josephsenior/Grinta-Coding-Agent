"""Opt-in Agentless-ML edit contract at completed-action boundaries.

This checks persistent source state. It does not monitor intermediate writes
inside one shell command, and it is not a process sandbox.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path, PurePosixPath


class ComparisonContractError(RuntimeError):
    """The comparison attempt must stop before returning normal tool feedback."""


class ComparisonEditGuard:
    """Check all accepted source changes against the immutable starting tree."""

    def __init__(self, workspace: str | Path, base_commit: str | None = None):
        self.workspace = Path(workspace).resolve(strict=True)
        self.failed: str | None = None
        self.base = self._git('rev-parse', base_commit or 'HEAD').decode().strip()
        self.original = self._tree(
            self._git('ls-tree', '-rz', '--full-tree', self.base)
        )

    def _git(self, *args: str, index: Path | None = None) -> bytes:
        env = {k: v for k, v in os.environ.items() if not k.upper().startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull)
        if index is not None:
            env['GIT_INDEX_FILE'] = str(index)
        return subprocess.run(
            [
                'git',
                '-c',
                'core.hooksPath=' + os.devnull,
                '-c',
                'core.fsmonitor=false',
                '-c',
                'core.autocrlf=false',
                '-c',
                'core.attributesFile=' + os.devnull,
                '-c',
                'core.filemode=' + ('false' if os.name == 'nt' else 'true'),
                *args,
            ],
            cwd=self.workspace,
            env=env,
            check=True,
            capture_output=True,
            timeout=60,
        ).stdout

    @staticmethod
    def _tree(listing: bytes) -> dict[str, tuple[str, str]]:
        result = {}
        for entry in listing.split(b'\0'):
            if entry:
                metadata, name = entry.split(b'\t', 1)
                mode, _, object_id = metadata.split()
                result[name.decode('utf-8')] = (mode.decode(), object_id.decode())
        return result

    def _current_tree(self) -> dict[str, tuple[str, str]]:
        with tempfile.TemporaryDirectory(
            prefix='grinta-comparison-index-'
        ) as temporary:
            index = Path(temporary) / 'index'
            self._git('read-tree', self.base, index=index)
            self._git('add', '-A', '--', '.', index=index)
            tree = self._git('write-tree', index=index).decode().strip()
            return self._tree(self._git('ls-tree', '-rz', '--full-tree', tree))

    @staticmethod
    def _path(path: str) -> None:
        pure = PurePosixPath(path)
        if pure.is_absolute() or any(
            part in ('', '.', '..') for part in path.split('/')
        ):
            raise ComparisonContractError(f'unsupported source path: {path}')
        for part in pure.parts:
            stem = part.split('.', 1)[0].upper()
            if (
                part.casefold() in {'.git', 'git~1'}
                or part.endswith((' ', '.'))
                or any(ord(c) < 32 or c in '\\:*?"<>|' for c in part)
                or stem in {'CON', 'PRN', 'AUX', 'NUL'}
                or stem
                in {f'{prefix}{n}' for prefix in ('COM', 'LPT') for n in range(1, 10)}
            ):
                raise ComparisonContractError(f'unsupported source path: {path}')

    def check(self) -> None:
        if self.failed:
            raise ComparisonContractError(self.failed)
        try:
            current = self._current_tree()
            folded = {}
            for path in current:
                folded.setdefault(path.casefold(), []).append(path)
            # Each newly located executable needs one executable path removed
            # from the base. This checks the resulting mode budget, without
            # pretending Git's similarity guesses prove a rename.
            removed_executables = sum(
                mode == '100755' and path not in current
                for path, (mode, _) in self.original.items()
            )
            new_executables = sum(
                mode == '100755' and path not in self.original
                for path, (mode, _) in current.items()
            )
            if new_executables > removed_executables:
                raise ComparisonContractError('new files must use mode 100644')
            for path in self.original.keys() | current.keys():
                before, after = self.original.get(path), current.get(path)
                if before == after:
                    continue
                self._path(path)
                if len(folded.get(path.casefold(), [])) > 1:
                    raise ComparisonContractError(f'case-colliding source path: {path}')
                if before is None and any(
                    old.casefold() == path.casefold()
                    or path.casefold().startswith(old.casefold() + '/')
                    or old.casefold().startswith(path.casefold() + '/')
                    for old in self.original
                ):
                    raise ComparisonContractError(
                        f'new source path collides with the starting tree: {path}'
                    )
                if before and before[0] not in {'100644', '100755'}:
                    raise ComparisonContractError(
                        f'cannot change a symlink or submodule: {path}'
                    )
                if after and after[0] not in {'100644', '100755'}:
                    raise ComparisonContractError(
                        f'cannot create a symlink or submodule: {path}'
                    )
                if before and after and before[0] != after[0]:
                    raise ComparisonContractError(
                        f'permission changes are unsupported: {path}'
                    )
                for entry in (before, after):
                    if entry:
                        data = self._git('cat-file', 'blob', entry[1])
                        if b'\0' in data:
                            raise ComparisonContractError(
                                f'binary source change: {path}'
                            )
                        try:
                            data.decode('utf-8')
                        except UnicodeDecodeError as exc:
                            raise ComparisonContractError(
                                f'non-UTF-8 source change: {path}'
                            ) from exc
        except Exception as exc:
            self.failed = f'Agentless-ML comparison edit contract violated: {exc}'
            raise ComparisonContractError(self.failed) from exc
