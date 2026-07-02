"""Thin mixin: high-level edit, write, and read/write methods for FileEditor.

The actual method bodies live in sibling helper modules; this file
defines a one-line-forwarder class so monkey-patching of these
methods in tests (``patch.object(self.editor, '_read_file', ...)``)
keeps working.

Split from a single 1100-line file in 2026-06 to keep this module
under the 40 KB file-size cap. The flat re-export shim at the
bottom preserves back-compat with callers using
``from backend.execution.utils.file_editor import ...``.

Siblings:
  - backend.execution.utils.file_editor._file_editor_diff_helpers      (diff/context)
  - backend.execution.utils.file_editor._file_editor_io_helpers         (IO/encoding/message)
  - backend.execution.utils.file_editor._file_editor_read_write_helpers (read/write/insert/replace)
  - backend.execution.utils.file_editor._file_editor_edit_helpers       (edit/write/receipt/verify)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.execution.utils.file_editor._file_editor_edit_helpers import (
    build_dry_run_result_impl as _build_dry_run_result_impl,
)
from backend.execution.utils.file_editor._file_editor_edit_helpers import (
    build_receipt_impl as _build_receipt_impl,
)
from backend.execution.utils.file_editor._file_editor_edit_helpers import (
    detect_stale_disk_on_write_impl as _detect_stale_disk_on_write_impl,
)
from backend.execution.utils.file_editor._file_editor_edit_helpers import (
    finalize_edit_result_impl as _finalize_edit_result_impl,
)
from backend.execution.utils.file_editor._file_editor_edit_helpers import (
    handle_edit_impl as _handle_edit_impl,
)
from backend.execution.utils.file_editor._file_editor_edit_helpers import (
    handle_replace_string_impl as _handle_replace_string_impl,
)
from backend.execution.utils.file_editor._file_editor_edit_helpers import (
    handle_write_commit_impl as _handle_write_commit_impl,
)
from backend.execution.utils.file_editor._file_editor_edit_helpers import (
    handle_write_impl as _handle_write_impl,
)
from backend.execution.utils.file_editor._file_editor_edit_helpers import (
    handle_write_maybe_short_circuit_impl as _handle_write_maybe_short_circuit_impl,
)
from backend.execution.utils.file_editor._file_editor_edit_helpers import (
    write_edit_result_impl as _write_edit_result_impl,
)
from backend.execution.utils.file_editor._file_editor_io_helpers import _FileReadMeta
from backend.execution.utils.file_editor._file_editor_read_write_helpers import (
    insert_at_line_impl as _insert_at_line_impl,
)
from backend.execution.utils.file_editor._file_editor_read_write_helpers import (
    read_file_impl as _read_file_impl,
)
from backend.execution.utils.file_editor._file_editor_read_write_helpers import (
    read_file_with_meta_impl as _read_file_with_meta_impl,
)
from backend.execution.utils.file_editor._file_editor_read_write_helpers import (
    replace_range_impl as _replace_range_impl,
)
from backend.execution.utils.file_editor._file_editor_read_write_helpers import (
    write_file_impl as _write_file_impl,
)
from backend.execution.utils.file_editor._file_editor_types import ToolResult


class FileEditorOpsMixin:
    def _handle_edit(
        self,
        file_path: Path,
        file_text: str | object | None,
        new_str: str | object | None,
        insert_line: int | None,
        start_line: int | None,
        end_line: int | None,
        *,
        edit_mode: str | None = None,
        expected_hash: str | None = None,
        dry_run: bool = False,
    ) -> ToolResult:
        return _handle_edit_impl(
            self,
            file_path,
            file_text,
            new_str,
            insert_line,
            start_line,
            end_line,
            edit_mode=edit_mode,
            expected_hash=expected_hash,
            dry_run=dry_run,
        )

    def _handle_replace_string(
        self,
        file_path: Path,
        old_string: str | None,
        new_string: str,
        *,
        replace_all: bool,
        dry_run: bool,
    ) -> ToolResult:
        return _handle_replace_string_impl(
            self,
            file_path,
            old_string,
            new_string,
            replace_all=replace_all,
            dry_run=dry_run,
        )

    def _build_receipt(
        self,
        *,
        file_path: Path,
        old_content: str | None,
        new_content: str | None,
        operation: str,
        target_kind: str,
        verification_passed: bool,
        requested_start_line: int | None = None,
        requested_end_line: int | None = None,
        rollback_available: bool = True,
    ) -> dict[str, Any]:
        return _build_receipt_impl(
            self,
            file_path=file_path,
            old_content=old_content,
            new_content=new_content,
            operation=operation,
            target_kind=target_kind,
            verification_passed=verification_passed,
            requested_start_line=requested_start_line,
            requested_end_line=requested_end_line,
            rollback_available=rollback_available,
        )

    def _finalize_edit_result(
        self,
        file_path: Path,
        old_content: str | None,
        new_content: str,
        dry_run: bool,
        *,
        target_kind: str,
        requested_start_line: int | None = None,
        requested_end_line: int | None = None,
    ) -> ToolResult:
        return _finalize_edit_result_impl(
            self,
            file_path,
            old_content,
            new_content,
            dry_run,
            target_kind=target_kind,
            requested_start_line=requested_start_line,
            requested_end_line=requested_end_line,
        )

    def _build_dry_run_result(
        self,
        file_path: Path,
        old_content: str | None,
        new_content: str,
        *,
        operation: str,
        target_kind: str,
        requested_start_line: int | None = None,
        requested_end_line: int | None = None,
    ) -> ToolResult:
        return _build_dry_run_result_impl(
            self,
            file_path,
            old_content,
            new_content,
            operation=operation,
            target_kind=target_kind,
            requested_start_line=requested_start_line,
            requested_end_line=requested_end_line,
        )

    def _write_edit_result(
        self,
        file_path: Path,
        old_content: str | None,
        new_content: str,
        *,
        target_kind: str,
        requested_start_line: int | None = None,
        requested_end_line: int | None = None,
    ) -> ToolResult:
        return _write_edit_result_impl(
            self,
            file_path,
            old_content,
            new_content,
            target_kind=target_kind,
            requested_start_line=requested_start_line,
            requested_end_line=requested_end_line,
        )

    def _handle_write_maybe_short_circuit(
        self,
        *,
        file_path: Path,
        content: str,
        old_content: str | None,
        file_existed: bool,
        dry_run: bool,
        overwrite: bool,
    ) -> ToolResult | None:
        return _handle_write_maybe_short_circuit_impl(
            self,
            file_path=file_path,
            content=content,
            old_content=old_content,
            file_existed=file_existed,
            dry_run=dry_run,
            overwrite=overwrite,
        )

    def _handle_write_commit(
        self,
        *,
        file_path: Path,
        content: str,
        old_content: str | None,
        file_existed: bool,
    ) -> ToolResult:
        return _handle_write_commit_impl(
            self,
            file_path=file_path,
            content=content,
            old_content=old_content,
            file_existed=file_existed,
        )

    def _detect_stale_disk_on_write(
        self,
        *,
        file_path: Path,
        file_existed: bool,
        old_content: str | None,
        new_content: str,
    ) -> ToolResult | None:
        return _detect_stale_disk_on_write_impl(
            self,
            file_path=file_path,
            file_existed=file_existed,
            old_content=old_content,
            new_content=new_content,
        )

    def _handle_write(
        self,
        file_path: Path,
        content: str,
        *,
        dry_run: bool = False,
        overwrite: bool = False,
    ) -> ToolResult:
        return _handle_write_impl(
            self,
            file_path,
            content,
            dry_run=dry_run,
            overwrite=overwrite,
        )

    def _read_file_with_meta(self, file_path: Path) -> tuple[str, _FileReadMeta]:
        return _read_file_with_meta_impl(self, file_path)

    def _read_file(self, file_path: Path) -> str:
        return _read_file_impl(self, file_path)

    def _write_file(self, file_path: Path, content: str) -> str:
        return _write_file_impl(self, file_path, content)

    def _insert_at_line(self, content: str, new_text: str, line_num: int) -> str:
        return _insert_at_line_impl(self, content, new_text, line_num)

    def _replace_range(
        self,
        content: str,
        new_text: str,
        start_line: int,
        end_line: int,
        expected_hash: str | None = None,
    ) -> str | ToolResult:
        return _replace_range_impl(
            self, content, new_text, start_line, end_line, expected_hash
        )
