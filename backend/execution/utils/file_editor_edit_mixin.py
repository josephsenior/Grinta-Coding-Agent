"""Mixin containing extracted FileEditor edit-operation helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from backend.core.type_safety.sentinels import Sentinel, is_missing
from backend.execution.utils.file_editor_edit_ops import (
    apply_edit_logic as _apply_edit_logic_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    apply_format_edit as _apply_format_edit_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    apply_section_edit as _apply_section_edit_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    apply_str_replace as _apply_str_replace_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    apply_unified_patch as _apply_unified_patch_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    build_no_match_error as _build_no_match_error_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    closest_match_candidates as _closest_match_candidates_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    find_actual_substring_for_replace as _find_actual_substring_for_replace_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    find_actual_substring_regex as _find_actual_substring_regex_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    flex_quote_pattern as _flex_quote_pattern_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    fuzzy_safe_replace as _fuzzy_safe_replace_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    line_ending_for_content as _line_ending_for_content_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    map_normalized_offset_to_original as _map_normalized_offset_to_original_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    mutate_structured_data as _mutate_structured_data_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    normalize_whitespace_for_match as _normalize_whitespace_for_match_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    parse_structured_content as _parse_structured_content_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    preserve_quote_style_in_new_string as _preserve_quote_style_in_new_string_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    replace_range_guarded as _replace_range_guarded_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    resolve_edit_content as _resolve_edit_content_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    serialize_structured_content as _serialize_structured_content_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    sha256_text as _sha256_text_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    slice_text_by_line_range as _slice_text_by_line_range_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    structured_path_tokens as _structured_path_tokens_impl,
)
from backend.execution.utils.file_editor_edit_ops import (
    ws_tolerant_replace as _ws_tolerant_replace_impl,
)


class FileEditorEditOpsMixin:
    def _extract_edit_params(
        self,
        file_text: str | Sentinel | None,
        old_str: str | Sentinel | None,
        new_str: str | Sentinel | None,
    ) -> tuple[str | None, str | None, str | None]:
        file_text_val = (
            str(file_text)
            if not is_missing(file_text) and file_text is not None
            else None
        )
        old_str_val = (
            str(old_str) if not is_missing(old_str) and old_str is not None else None
        )
        new_str_val = (
            str(new_str) if not is_missing(new_str) and new_str is not None else None
        )
        return file_text_val, old_str_val, new_str_val

    @staticmethod
    def _normalize_whitespace_for_match(text: str) -> str:
        return _normalize_whitespace_for_match_impl(text)

    def _ws_tolerant_replace(
        self,
        file_content: str,
        old_str: str,
        new_str: str,
    ) -> Any:
        return _ws_tolerant_replace_impl(self, file_content, old_str, new_str)

    @staticmethod
    def _map_normalized_offset_to_original(original: str, norm_offset: int) -> int:
        return _map_normalized_offset_to_original_impl(original, norm_offset)

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

    def _closest_match_candidates(
        self,
        file_content: str,
        old_str: str,
        *,
        limit: int = 3,
    ) -> list[tuple[float, int, str]]:
        return _closest_match_candidates_impl(
            self, file_content, old_str, limit=limit
        )

    def _build_no_match_error(self, file_content: str, old_str: str, mode: str) -> str:
        return _build_no_match_error_impl(self, file_content, old_str, mode)

    def _fuzzy_safe_replace(
        self,
        file_content: str,
        old_str: str,
        new_str: str,
    ) -> Any:
        return _fuzzy_safe_replace_impl(self, file_content, old_str, new_str)

    @staticmethod
    def _flex_quote_pattern(needle: str) -> str:
        return _flex_quote_pattern_impl(needle)

    def _find_actual_substring_regex(self, haystack: str, needle: str) -> str | None:
        return _find_actual_substring_regex_impl(self, haystack, needle)

    def _find_actual_substring_for_replace(
        self, haystack: str, needle: str
    ) -> str | None:
        return _find_actual_substring_for_replace_impl(self, haystack, needle)

    @staticmethod
    def _preserve_quote_style_in_new_string(actual_old: str, new_str: str) -> str:
        return _preserve_quote_style_in_new_string_impl(actual_old, new_str)

    def _apply_str_replace(
        self,
        old_content: str,
        old_str: str,
        new_str: str,
        file_path: Path | None = None,
    ) -> Any:
        return _apply_str_replace_impl(self, old_content, old_str, new_str, file_path)

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
        old_str_val: str | None,
        new_str_val: str | None,
        insert_line: int | None,
        start_line: int | None,
        end_line: int | None,
        *,
        edit_mode: str | None = None,
        format_kind: str | None = None,
        format_op: str | None = None,
        format_path: str | None = None,
        format_value: Any = None,
        anchor_type: str | None = None,
        anchor_value: str | None = None,
        anchor_occurrence: int | None = None,
        section_action: str | None = None,
        section_content: str | None = None,
        patch_text: str | None = None,
        expected_hash: str | None = None,
        file_path: Path | None = None,
    ) -> Any:
        return _apply_edit_logic_impl(
            self,
            old_content_str,
            file_text_val,
            old_str_val,
            new_str_val,
            insert_line,
            start_line,
            end_line,
            edit_mode=edit_mode,
            format_kind=format_kind,
            format_op=format_op,
            format_path=format_path,
            format_value=format_value,
            anchor_type=anchor_type,
            anchor_value=anchor_value,
            anchor_occurrence=anchor_occurrence,
            section_action=section_action,
            section_content=section_content,
            patch_text=patch_text,
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

    def _apply_format_edit(
        self,
        content: str,
        *,
        file_path: Path | None,
        format_kind: str | None,
        format_op: str | None,
        format_path: str | None,
        format_value: Any,
    ) -> Any:
        return _apply_format_edit_impl(
            self,
            content,
            file_path=file_path,
            format_kind=format_kind,
            format_op=format_op,
            format_path=format_path,
            format_value=format_value,
        )

    def _parse_structured_content(self, content: str, kind: str) -> Any:
        return _parse_structured_content_impl(content, kind)

    def _serialize_structured_content(self, data: Any, kind: str) -> str:
        return _serialize_structured_content_impl(data, kind)

    @staticmethod
    def _structured_path_tokens(path_expr: str) -> list[str]:
        return _structured_path_tokens_impl(path_expr)

    def _mutate_structured_data(
        self, data: Any, op: str, path_expr: str, value: Any
    ) -> Any:
        return _mutate_structured_data_impl(data, op, path_expr, value)

    def _apply_section_edit(
        self,
        content: str,
        *,
        anchor_type: str | None,
        anchor_value: str | None,
        anchor_occurrence: int | None,
        section_action: str | None,
        section_content: str | None,
    ) -> Any:
        return _apply_section_edit_impl(
            self,
            content,
            anchor_type=anchor_type,
            anchor_value=anchor_value,
            anchor_occurrence=anchor_occurrence,
            section_action=section_action,
            section_content=section_content,
        )

    def _apply_unified_patch(self, content: str, patch_text: str | None) -> Any:
        return _apply_unified_patch_impl(self, content, patch_text)
