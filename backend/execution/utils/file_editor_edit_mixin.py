"""Mixin containing extracted FileEditor edit-operation helpers."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from backend.core.type_safety.sentinels import Sentinel, is_missing
from backend.execution.utils.file_editor_edit_ops import (
    apply_edit_logic as _apply_edit_logic_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    line_ending_for_content as _line_ending_for_content_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    replace_range_guarded as _replace_range_guarded_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    resolve_edit_content as _resolve_edit_content_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    sha256_text as _sha256_text_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
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

    def _maybe_validate_syntax_for_file(
        self, file_path: Path, content: str
    ) -> tuple[bool, str]:
        preflight = self._preflight_content_guard(file_path, content)
        if preflight is not None:
            return False, preflight

        try:
            from backend.utils.treesitter_editor import TreeSitterEditor
        except Exception as exc:
            return True, f'Tree-sitter unavailable: {exc}'

        try:
            editor = TreeSitterEditor()
        except Exception as exc:
            return True, f'Tree-sitter initialization failed: {exc}'

        language = editor.detect_language(str(file_path))
        if not language:
            return True, 'No parser mapping for file extension; skipping validation'

        is_valid, msg = editor.validate_syntax(content, str(file_path), language)
        if is_valid:
            return True, msg

        enriched_msg = self._enrich_syntax_error_with_escape_hint(
            msg, content, file_path
        )
        enriched_msg = self._attach_content_context(enriched_msg, content)

        if (
            language in self._STRICT_VALIDATION_LANGUAGES
            and self._strict_write_validation_enabled()
        ):
            return False, enriched_msg

        return True, f'WARNING: {enriched_msg}'

    @staticmethod
    def _preflight_content_guard(file_path: Path, content: str) -> str | None:
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
            return (
                'Placeholder example content detected. The file_editor XML examples '
                'must be replaced with the real file contents before writing.'
            )

        suffix = file_path.suffix.lower()
        if suffix == '.py':
            for idx, line in enumerate(content.splitlines(), start=1):
                if re.match(r'^\s*//', line):
                    return (
                        f'Line {idx}: invalid Python comment prefix `//` detected. '
                        'Python comments use `#`. Repair the affected lines with a '
                        'targeted range edit instead of retrying the same full write.'
                    )
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
                    msg + '\n\n[HINT] The content contains literal backslash-escape '
                    'sequences (e.g. \\n, \\") that appear to be double-escaped. '
                    'In your next tool call, use a single backslash for newlines '
                    '(a real newline character, not the characters "\\" + "n") '
                    'and unescaped double quotes inside strings.'
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
