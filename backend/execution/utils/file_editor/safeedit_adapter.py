"""Grinta's adapter to the standalone SafeEdit transaction package."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Mapping

from safeedit import SafeEdit, WriteFile

_MAX_SAFEEDIT_FILE_BYTES = 100_000_000


def _workspace_key(root: Path) -> str:
    normalized = os.path.normcase(str(root.resolve()))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


class SafeEditAdapter:
    """Route UTF-8 editor writes through SafeEdit and keep journals out of workspaces."""

    def __init__(self, workspace_root: str | Path) -> None:
        self.workspace_root = Path(workspace_root).resolve(strict=True)
        journal_dir = (
            Path.home()
            / ".grinta"
            / "safeedit"
            / _workspace_key(self.workspace_root)
        )
        self.engine = SafeEdit(
            self.workspace_root,
            max_file_bytes=_MAX_SAFEEDIT_FILE_BYTES,
            journal_dir=journal_dir,
        )

    def _relative_path(self, path: Path) -> str:
        resolved = path.resolve(strict=False)
        try:
            return resolved.relative_to(self.workspace_root).as_posix()
        except ValueError as exc:
            raise ValueError(f"File path is outside the SafeEdit workspace: {path}") from exc

    def write_utf8(self, path: Path, content: str, payload: bytes) -> bool:
        """Write a UTF-8 payload through SafeEdit, or return False for other encodings."""

        if payload != content.encode("utf-8") or len(payload) > _MAX_SAFEEDIT_FILE_BYTES:
            return False
        # FileEditor has legacy callers that pass absolute paths outside its
        # workspace. Its existing path validation remains authoritative there;
        # SafeEdit only handles writes within the workspace it was configured for.
        try:
            relative_path = self._relative_path(path)
        except ValueError:
            return False
        before = path.read_bytes() if path.exists() else None
        if before is not None:
            if len(before) > _MAX_SAFEEDIT_FILE_BYTES:
                return False
            try:
                before.decode("utf-8")
            except UnicodeDecodeError:
                return False
            if before == payload:
                return True
        relative = self._relative_path(path)
        operation = WriteFile(
            path=relative_path,
            content=content,
            expected_sha256=hashlib.sha256(before).hexdigest() if before is not None else None,
            create_only=before is None,
        )
        self.engine.commit(self.engine.plan([operation]))
        return True

    def write_utf8_batch(
        self,
        contents: Mapping[str, str],
        expected_hashes: Mapping[str, str | None],
    ) -> None:
        """Commit final UTF-8 contents for several workspace-relative paths."""

        operations = [
            WriteFile(
                path=self._relative_path(Path(path)),
                content=content,
                expected_sha256=expected_hashes[path],
                create_only=expected_hashes[path] is None,
            )
            for path, content in contents.items()
        ]
        self.engine.commit(self.engine.plan(operations))
