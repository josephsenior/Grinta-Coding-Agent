"""Shared edit-operation helpers for FileEditor."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.core import json_compat as json_compat


def _file_editor_module():
    from backend.execution.utils import file_editor as fe

    return fe


def _tool_result(**kwargs):
    return _file_editor_module().ToolResult(**kwargs)


def resolve_edit_content(file_text_val: str | None, new_str_val: str | None) -> str:
    return new_str_val or file_text_val or ''


def line_ending_for_content(content: str) -> str:
    if '\r\n' in content:
        return '\r\n'
    return '\n'


def _apply_edit_implicit(
    editor: Any,
    old_content_str: str,
    file_text_val: str | None,
    new_str_val: str | None,
    insert_line: int | None,
    start_line: int | None,
    end_line: int | None,
) -> str | Any:
    """Insert/range/full-file paths when ``edit_mode`` is unset."""
    if start_line is not None and end_line is not None:
        return editor._replace_range(
            old_content_str,
            resolve_edit_content(file_text_val, new_str_val),
            start_line,
            end_line,
        )
    if insert_line is not None:
        return editor._insert_at_line(
            old_content_str,
            resolve_edit_content(file_text_val, new_str_val),
            insert_line,
        )
    if file_text_val:
        return file_text_val
    return _tool_result(
        output='',
        error=(
            'Deterministic edit failed: when edit_mode is not provided, '
            'you must provide start_line/end_line (range) or insert_line (insert).'
        ),
        new_content=old_content_str,
    )


def apply_edit_logic(
    editor: Any,
    old_content_str: str,
    file_text_val: str | None,
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
) -> str | Any:
    resolved_mode = (edit_mode or '').strip().lower() or None

    def branch_format() -> str | Any:
        return apply_format_edit(
            editor,
            old_content_str,
            file_path=file_path,
            format_kind=format_kind,
            format_op=format_op,
            format_path=format_path,
            format_value=format_value,
        )

    def branch_section() -> str | Any:
        return apply_section_edit(
            editor,
            old_content_str,
            anchor_type=anchor_type,
            anchor_value=anchor_value,
            anchor_occurrence=anchor_occurrence,
            section_action=section_action,
            section_content=section_content,
        )

    def branch_range() -> str | Any:
        if start_line is None or end_line is None:
            return _tool_result(
                output='',
                error='edit_mode=range requires start_line and end_line.',
                new_content=old_content_str,
            )
        return replace_range_guarded(
            editor,
            old_content_str,
            resolve_edit_content(file_text_val, new_str_val),
            start_line,
            end_line,
            expected_hash=expected_hash,
        )

    def branch_patch() -> str | Any:
        return apply_unified_patch(editor, old_content_str, patch_text)

    branches: dict[str, Callable[[], str | Any]] = {
        'format': branch_format,
        'section': branch_section,
        'range': branch_range,
        'patch': branch_patch,
    }
    if resolved_mode is not None:
        handler = branches.get(resolved_mode)
        if handler is not None:
            return handler()
    return _apply_edit_implicit(
        editor,
        old_content_str,
        file_text_val,
        new_str_val,
        insert_line,
        start_line,
        end_line,
    )


def slice_text_by_line_range(content: str, start_line: int, end_line: int) -> str:
    lines = content.splitlines(keepends=True)
    if not lines or start_line < 1:
        return ''
    start_idx = start_line - 1
    end_idx = min(len(lines), end_line)
    if start_idx >= len(lines):
        return ''
    return ''.join(lines[start_idx:end_idx])


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def replace_range_guarded(
    editor: Any,
    content: str,
    new_text: str,
    start_line: int,
    end_line: int,
    *,
    expected_hash: str | None = None,
) -> str | Any:
    if expected_hash:
        current_slice = slice_text_by_line_range(content, start_line, end_line)
        if sha256_text(current_slice) != expected_hash:
            return _tool_result(
                output='',
                error='Range guard failed: expected_hash does not match target slice.',
                new_content=content,
            )
    return editor._replace_range(content, new_text, start_line, end_line)


def apply_format_edit(
    editor: Any,
    content: str,
    *,
    file_path: Path | None,
    format_kind: str | None,
    format_op: str | None,
    format_path: str | None,
    format_value: Any,
) -> str | Any:
    kind = (format_kind or (file_path.suffix.lstrip('.') if file_path else '')).lower()
    kind = {'yml': 'yaml'}.get(kind, kind)
    op = (format_op or 'set').lower()
    if kind not in {'json', 'yaml', 'toml'}:
        return _tool_result(
            output='',
            error=f'Unsupported format kind for parser-based edit: {kind!r}',
            new_content=content,
        )
    if not format_path:
        return _tool_result(
            output='',
            error='edit_mode=format requires format_path.',
            new_content=content,
        )
    try:
        data = parse_structured_content(content, kind)
        updated = mutate_structured_data(data, op, format_path, format_value)
        return serialize_structured_content(updated, kind)
    except Exception as exc:
        return _tool_result(
            output='',
            error=f'Format edit failed: {exc}',
            new_content=content,
        )


def parse_structured_content(content: str, kind: str) -> Any:
    if kind == 'json':
        return json_compat.loads(content or '{}')
    if kind == 'yaml':
        import yaml

        return yaml.safe_load(content) or {}
    try:
        import tomllib

        return tomllib.loads(content or '')
    except Exception:
        import toml

        return toml.loads(content or '')


def serialize_structured_content(data: Any, kind: str) -> str:
    if kind == 'json':
        return f'{json_compat.dumps(data, indent=2, ensure_ascii=True)}\n'
    if kind == 'yaml':
        import yaml

        return yaml.safe_dump(data, sort_keys=False)
    try:
        import toml

        return toml.dumps(data)
    except Exception as exc:
        raise ValueError(f'TOML serialization unavailable: {exc}') from exc


def structured_path_tokens(path_expr: str) -> list[str]:
    cleaned = path_expr.strip()
    if cleaned.startswith('$.'):
        cleaned = cleaned[2:]
    elif cleaned.startswith('$'):
        cleaned = cleaned[1:]
    return [part for part in cleaned.split('.') if part]


def _walk_structured_to_leaf_parent(
    data: dict[str, Any],
    tokens: list[str],
    op: str,
) -> tuple[dict[str, Any], str]:
    """Walk to the parent dict of the final key in ``tokens``."""
    node: dict[str, Any] = data
    for token in tokens[:-1]:
        if token not in node or not isinstance(node[token], dict):
            if op == 'set':
                node[token] = {}
            else:
                raise ValueError(f'Path segment {token!r} not found')
        node = node[token]
    return node, tokens[-1]


def _mutate_structured_leaf(
    parent: dict[str, Any],
    leaf: str,
    op: str,
    value: Any,
) -> None:
    if op == 'set':
        parent[leaf] = value
    elif op == 'delete':
        parent.pop(leaf, None)
    elif op == 'append':
        target = parent.get(leaf)
        if target is None:
            parent[leaf] = [value]
        elif isinstance(target, list):
            target.append(value)
        else:
            raise ValueError('append target is not a list')
    else:
        raise ValueError(f'Unsupported format_op: {op!r}')


def mutate_structured_data(data: Any, op: str, path_expr: str, value: Any) -> Any:
    if not isinstance(data, dict):
        raise ValueError('Structured root must be an object/map')
    tokens = structured_path_tokens(path_expr)
    if not tokens:
        raise ValueError('format_path must point to a key')
    parent, leaf = _walk_structured_to_leaf_parent(data, tokens, op)
    _mutate_structured_leaf(parent, leaf, op, value)
    return data


def _find_markdown_section_range(
    lines: list[str], anchor_value: str, occurrence: int
) -> tuple[int, int] | None:
    heading_re = re.compile(r'^(#{1,6})\s+(.*)$')
    heading_matches: list[tuple[int, int]] = []
    for idx, line in enumerate(lines):
        match = heading_re.match(line.strip('\r\n'))
        if match and match.group(2).strip() == anchor_value.strip():
            heading_matches.append((idx, len(match.group(1))))

    if len(heading_matches) < occurrence or occurrence < 1:
        return None

    start_idx, level = heading_matches[occurrence - 1]
    end_idx = len(lines)
    for pos in range(start_idx + 1, len(lines)):
        match = heading_re.match(lines[pos].strip('\r\n'))
        if match and len(match.group(1)) <= level:
            end_idx = pos
            break
    return start_idx, end_idx


def _find_pattern_section_range(
    content: str,
    lines: list[str],
    *,
    kind: str,
    anchor_value: str,
    occurrence: int,
) -> tuple[int, int] | None:
    pattern = anchor_value if kind == 'regex' else re.escape(anchor_value)
    pattern_matches = list(re.finditer(pattern, content, re.MULTILINE))
    if len(pattern_matches) < occurrence or occurrence < 1:
        return None

    target = pattern_matches[occurrence - 1]
    start_idx = content[: target.start()].count('\n')
    return start_idx, len(lines)


def _resolve_section_range(
    content: str,
    lines: list[str],
    *,
    kind: str,
    anchor_value: str,
    occurrence: int,
) -> tuple[int, int] | None:
    if kind == 'markdown_heading':
        return _find_markdown_section_range(lines, anchor_value, occurrence)
    return _find_pattern_section_range(
        content,
        lines,
        kind=kind,
        anchor_value=anchor_value,
        occurrence=occurrence,
    )


def _apply_section_action(
    lines: list[str],
    repl_lines: list[str],
    *,
    start_idx: int,
    end_idx: int,
    action: str,
) -> list[str] | None:
    if action == 'replace':
        return lines[:start_idx] + repl_lines + lines[end_idx:]
    if action == 'insert_before':
        return lines[:start_idx] + repl_lines + lines[start_idx:]
    if action == 'insert_after':
        return lines[:end_idx] + repl_lines + lines[end_idx:]
    if action == 'delete':
        return lines[:start_idx] + lines[end_idx:]
    return None


def apply_section_edit(
    editor: Any,
    content: str,
    *,
    anchor_type: str | None,
    anchor_value: str | None,
    anchor_occurrence: int | None,
    section_action: str | None,
    section_content: str | None,
) -> str | Any:
    if not anchor_value:
        return _tool_result(
            output='',
            error='edit_mode=section requires anchor_value.',
            new_content=content,
        )
    kind = (anchor_type or 'markdown_heading').lower()
    occurrence = anchor_occurrence or 1
    action = (section_action or 'replace').lower()
    lines = content.splitlines(keepends=True)
    section_range = _resolve_section_range(
        content,
        lines,
        kind=kind,
        anchor_value=anchor_value,
        occurrence=occurrence,
    )
    if section_range is None:
        return _tool_result(
            output='', error='Section anchor not found.', new_content=content
        )
    start_idx, end_idx = section_range

    replacement = section_content or ''
    repl_lines = replacement.splitlines(keepends=True)
    result_lines = _apply_section_action(
        lines,
        repl_lines,
        start_idx=start_idx,
        end_idx=end_idx,
        action=action,
    )
    if result_lines is None:
        return _tool_result(
            output='',
            error=f'Unsupported section_action: {action!r}',
            new_content=content,
        )
    return ''.join(result_lines)


def _collect_unified_patch_hunks(patch_text: str) -> list[tuple[str, str]]:
    hunks: list[tuple[str, str]] = []
    old_lines: list[str] = []
    new_lines: list[str] = []
    in_hunk = False
    for raw_line in patch_text.splitlines():
        if raw_line.startswith('@@'):
            if in_hunk:
                hunks.append((''.join(old_lines), ''.join(new_lines)))
            old_lines, new_lines = [], []
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if raw_line.startswith(' '):
            text = raw_line[1:] + '\n'
            old_lines.append(text)
            new_lines.append(text)
        elif raw_line.startswith('-'):
            old_lines.append(raw_line[1:] + '\n')
        elif raw_line.startswith('+'):
            new_lines.append(raw_line[1:] + '\n')
    if in_hunk:
        hunks.append((''.join(old_lines), ''.join(new_lines)))
    return hunks


def _apply_patch_hunks_to_content(
    content: str, hunks: list[tuple[str, str]]
) -> str | Any:
    updated = content
    for old_chunk, new_chunk in hunks:
        if not old_chunk:
            updated = f'{updated}{new_chunk}'
            continue
        count = updated.count(old_chunk)
        if count != 1:
            return _tool_result(
                output='',
                error='Patch hunk context did not match uniquely.',
                new_content=content,
            )
        updated = updated.replace(old_chunk, new_chunk, 1)
    return updated


def apply_unified_patch(editor: Any, content: str, patch_text: str | None) -> str | Any:
    if not patch_text:
        return _tool_result(
            output='',
            error='edit_mode=patch requires patch_text.',
            new_content=content,
        )
    hunks = _collect_unified_patch_hunks(patch_text)
    return _apply_patch_hunks_to_content(content, hunks)
