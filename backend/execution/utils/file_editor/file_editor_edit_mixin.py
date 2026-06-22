"""Mixin containing extracted FileEditor edit-operation helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from backend.core.type_safety.sentinels import Sentinel, is_missing
from backend.execution.utils.file_editor.file_editor_edit_ops import (
    apply_edit_logic as _apply_edit_logic_impl,
)
from backend.execution.utils.file_editor.file_editor_edit_ops import (
    line_ending_for_content as _line_ending_for_content_impl,
)
from backend.execution.utils.file_editor.file_editor_edit_ops import (
    replace_range_guarded as _replace_range_guarded_impl,
)
from backend.execution.utils.file_editor.file_editor_edit_ops import (
    resolve_edit_content as _resolve_edit_content_impl,
)
from backend.execution.utils.file_editor.file_editor_edit_ops import (
    sha256_text as _sha256_text_impl,
)
from backend.execution.utils.file_editor.file_editor_edit_ops import (
    slice_text_by_line_range as _slice_text_by_line_range_impl,
)


class FileEditorEditOpsMixin:
    def _extract_edit_params(
        self,
        file_text: str | Sentinel | None,
        new_str: str | Sentinel | None,
    ) -> tuple[str | None, str | None]:
        file_text_val = (
            str(file_text)
            if not is_missing(file_text) and file_text is not None
            else None
        )
        new_str_val = (
            str(new_str) if not is_missing(new_str) and new_str is not None else None
        )
        return file_text_val, new_str_val

    @staticmethod
    def _line_ending_for_content(content: str) -> str:
        return _line_ending_for_content_impl(content)

    _STRICT_VALIDATION_LANGUAGES: frozenset[str] = frozenset(
        {'html', 'css', 'scss', 'json', 'yaml', 'xml', 'svg', 'toml'}
    )

    @staticmethod
    def _strict_write_validation_enabled() -> bool:
        raw = os.environ.get('GRINTA_STRICT_WRITE_VALIDATION', '').strip().lower()
        return raw in {'1', 'true', 'yes', 'on'}

    @staticmethod
    def _syntax_regression_guard_enabled() -> bool:
        raw = os.environ.get('GRINTA_SYNTAX_REGRESSION_GUARD', '').strip().lower()
        return raw not in {'0', 'false', 'no', 'off'}

    def _maybe_validate_syntax_for_file(
        self, file_path: Path, content: str
    ) -> tuple[bool, str]:
        preflight = self._preflight_content_guard(file_path, content)
        if preflight is not None:
            return False, preflight

        try:
            from backend.utils.treesitter.syntax_check import check_syntax
        except Exception as exc:
            return True, f'Syntax checker unavailable: {exc}'

        result = check_syntax(str(file_path), content)
        language = result.language
        if result.status == 'skipped':
            return True, result.detail or 'Syntax validation skipped'

        if result.status == 'passed':
            checker = f' via {result.checker}' if result.checker else ''
            return True, f'Syntax validation passed{checker}'

        enriched_msg = self._enrich_syntax_error_with_escape_hint(
            result.detail, content, file_path
        )
        enriched_msg = self._attach_content_context(enriched_msg, content)

        if (
            language in self._STRICT_VALIDATION_LANGUAGES
            and self._strict_write_validation_enabled()
        ):
            return False, enriched_msg

        return True, f'WARNING: {enriched_msg}'

    def _detect_introduced_syntax_error(
        self,
        file_path: Path,
        old_content: str | None,
        new_content: str,
    ) -> str | None:
        """Detect edits that turn a previously parse-valid file parse-invalid.

        Returns a diagnostic string when a regression is detected. Callers
        surface this as a post-write WARNING rather than blocking the edit.
        """
        if (
            old_content is None
            or old_content == new_content
            or not self._syntax_regression_guard_enabled()
        ):
            return None

        try:
            from backend.utils.treesitter.syntax_check import check_syntax
        except Exception:
            return None

        try:
            old_result = check_syntax(str(file_path), old_content)
            new_result = check_syntax(str(file_path), new_content)
        except Exception:
            return None

        if old_result.status != 'passed' or new_result.status != 'failed':
            return None

        enriched_msg = self._enrich_syntax_error_with_escape_hint(
            new_result.detail, new_content, file_path
        )
        enriched_msg = self._attach_content_context(enriched_msg, new_content)
        return f'File has syntax errors.\n{enriched_msg}'

    @staticmethod
    def _preflight_content_guard(file_path: Path, content: str) -> str | None:
        try:
            from backend.core.content_escape_repair import (
                looks_serialized_payload,
                serialized_payload_error,
            )

            if looks_serialized_payload(content):
                return serialized_payload_error('content')
        except Exception:
            pass

        placeholder_lines = {
            'your code here -- raw text, no json escaping needed',
            'full file contents here -- raw text, no json escaping',
            'raw file content here',
            '# raw file content here',
        }
        normalized_lines = {
            line.strip().lower() for line in content.splitlines() if line.strip()
        }
        if normalized_lines and normalized_lines.issubset(placeholder_lines):
            return 'Placeholder example content detected.'

        return None

    @staticmethod
    def _attach_content_context(msg: str, content: str, *, radius: int = 2) -> str:
        if not msg or not content:
            return msg
        lines = content.splitlines()
        if len(lines) < 3:
            return msg
        try:
            import re as _re

            nums = {
                int(match.group(1))
                for match in _re.finditer(r'(?i)\bline\s+(\d{1,6})\b', msg)
            }
        except Exception:
            return msg
        if not nums:
            return msg

        excerpts: list[str] = []
        for line_no in sorted(nums)[:5]:
            start = max(1, line_no - radius)
            end = min(len(lines), line_no + radius)
            width = len(str(end))
            block = [f'  [line {line_no} — excerpt]']
            for index in range(start, end + 1):
                marker = '>>' if index == line_no else '  '
                block.append(f'  {marker} {index:>{width}} | {lines[index - 1]}')
            excerpts.append('\n'.join(block))
        if not excerpts:
            return msg
        return msg + '\n\nContent context:\n' + '\n\n'.join(excerpts)

    @staticmethod
    def _enrich_syntax_error_with_escape_hint(
        msg: str, content: str, file_path: Path
    ) -> str:
        try:
            from backend.core.content_escape_repair import has_literal_escape_residue

            if has_literal_escape_residue(content, file_path):
                return (
                    msg
                    + '\n[HINT] Content contains literal \\n or \\" escape sequences.'
                )
        except Exception:
            pass
        return msg

    def _resolve_edit_content(
        self,
        file_text_val: str | None,
        new_str_val: str | None,
    ) -> str:
        return _resolve_edit_content_impl(file_text_val, new_str_val)

    def _apply_edit_logic(
        self,
        old_content_str: str,
        file_text_val: str | None,
        new_str_val: str | None,
        insert_line: int | None,
        start_line: int | None,
        end_line: int | None,
        *,
        edit_mode: str | None = None,
        expected_hash: str | None = None,
        file_path: Path | None = None,
    ) -> Any:
        return _apply_edit_logic_impl(
            self,
            old_content_str,
            file_text_val,
            new_str_val,
            insert_line,
            start_line,
            end_line,
            edit_mode=edit_mode,
            expected_hash=expected_hash,
            file_path=file_path,
        )

    @staticmethod
    def _slice_text_by_line_range(content: str, start_line: int, end_line: int) -> str:
        return _slice_text_by_line_range_impl(content, start_line, end_line)

    @staticmethod
    def _sha256_text(text: str) -> str:
        return _sha256_text_impl(text)

    def _replace_range_guarded(
        self,
        content: str,
        new_text: str,
        start_line: int,
        end_line: int,
        *,
        expected_hash: str | None = None,
    ) -> Any:
        return _replace_range_guarded_impl(
            self,
            content,
            new_text,
            start_line,
            end_line,
            expected_hash=expected_hash,
        )
