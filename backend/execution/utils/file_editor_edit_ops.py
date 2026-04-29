"""Shared edit-operation helpers for FileEditor."""

from __future__ import annotations

import difflib
import hashlib
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from backend.core import json_compat as json_compat

# Sentinel: multiple whitespace-normalized matches for the same old_str
_NORM_WS_SPAN_AMBIGUOUS = object()


def _file_editor_module():
    from backend.execution.utils import file_editor as fe

    return fe


def _tool_result(**kwargs):
    return _file_editor_module().ToolResult(**kwargs)


def normalize_whitespace_for_match(text: str) -> str:
    lines = text.splitlines()
    normalized_lines = []
    for line in lines:
        line = line.replace('\t', '    ')
        line = re.sub(r'[ \t]+', ' ', line).strip()
        normalized_lines.append(line)
    result = '\n'.join(normalized_lines)
    return re.sub(r'\n+', '\n', result).strip()


def _match_normalized_block_at(
    lines_norm: list[str],
    norm_old_lines: list[str],
    start: int,
) -> tuple[bool, int]:
    """Align ``norm_old_lines`` against ``lines_norm`` starting at ``start``."""
    current = start
    for target in norm_old_lines:
        while current < len(lines_norm) and not lines_norm[current] and target:
            current += 1
        if current >= len(lines_norm) or lines_norm[current] != target:
            return False, current
        current += 1
    return True, current


def _find_unique_normalized_ws_span(
    lines_norm: list[str],
    norm_old_lines: list[str],
) -> tuple[int, int] | None | object:
    """Return ``(start, end_exclusive)``, ``None``, or ``_NORM_WS_SPAN_AMBIGUOUS``."""
    first_line_matches = [
        i for i, nl in enumerate(lines_norm) if nl == norm_old_lines[0]
    ]
    valid_match: tuple[int, int] | None = None
    for start in first_line_matches:
        found, end = _match_normalized_block_at(lines_norm, norm_old_lines, start)
        if found:
            if valid_match is not None:
                return _NORM_WS_SPAN_AMBIGUOUS
            valid_match = (start, end)
    return valid_match


def ws_tolerant_replace(
    editor: Any,
    file_content: str,
    old_str: str,
    new_str: str,
) -> str | Any:
    norm_content = normalize_whitespace_for_match(file_content)
    norm_old = normalize_whitespace_for_match(old_str)

    count = norm_content.count(norm_old)
    if count == 0 or count > 1:
        return _tool_result(
            output='',
            error=build_no_match_error(editor, file_content, old_str, mode='normalize_ws'),
            new_content=file_content,
        )

    lines_orig = file_content.splitlines(keepends=True)
    lines_norm = [normalize_whitespace_for_match(line_text) for line_text in lines_orig]
    norm_old_lines = norm_old.splitlines()
    if not norm_old_lines:
        return _tool_result(
            output='',
            error='old_str contains only whitespace.',
            new_content=file_content,
        )

    span = _find_unique_normalized_ws_span(lines_norm, norm_old_lines)
    if span is _NORM_WS_SPAN_AMBIGUOUS:
        return _tool_result(
            output='',
            error=build_no_match_error(
                editor, file_content, old_str, mode='normalize_ws'
            ),
            new_content=file_content,
        )
    if span is None:
        return _tool_result(
            output='',
            error=build_no_match_error(editor, file_content, old_str, mode='normalize_ws'),
            new_content=file_content,
        )

    start, end = span
    return ''.join(lines_orig[:start]) + new_str + ''.join(lines_orig[end:])


def map_normalized_offset_to_original(original: str, norm_offset: int) -> int:
    return -1


def line_ending_for_content(content: str) -> str:
    if '\r\n' in content:
        return '\r\n'
    return '\n'


def closest_match_candidates(
    editor: Any,
    file_content: str,
    old_str: str,
    *,
    limit: int = 3,
) -> list[tuple[float, int, str]]:
    target = normalize_whitespace_for_match(old_str).strip()
    if not target:
        return []

    if '\n' in old_str or '\r' in old_str:
        target = normalize_whitespace_for_match(old_str.splitlines()[0]).strip()

    candidates: list[tuple[float, int, str]] = []
    for idx, line in enumerate(file_content.splitlines(), 1):
        normalized = normalize_whitespace_for_match(line).strip()
        if not normalized:
            continue
        ratio = difflib.SequenceMatcher(None, target, normalized).ratio()
        if ratio < 0.4:
            continue
        snippet = line.strip()
        if len(snippet) > 120:
            snippet = f'{snippet[:117]}...'
        candidates.append((ratio, idx, snippet))

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[:limit]


def build_no_match_error(editor: Any, file_content: str, old_str: str, mode: str) -> str:
    base = {
        'exact': 'No exact match found for old_str.',
        'normalize_ws': 'No match found even with whitespace normalization.',
        'fuzzy_safe': 'No match found for fuzzy_safe mode.',
    }.get(mode, 'No match found for old_str.')

    closest = closest_match_candidates(editor, file_content, old_str)
    if not closest:
        return base

    lines = [base, 'Closest candidates:']
    for ratio, line_no, snippet in closest:
        lines.append(f'- line {line_no} (score {ratio:.2f}): {snippet}')
    return '\n'.join(lines)


def _fuzzy_precheck_old_str(old_str: str, file_content: str) -> Any | None:
    """Return a ``ToolResult`` error if fuzzy_safe cannot run; otherwise ``None``."""
    if not old_str.strip():
        return _tool_result(
            output='',
            error='fuzzy_safe mode requires a non-empty old_str.',
            new_content=file_content,
        )
    if '\n' in old_str or '\r' in old_str:
        return _tool_result(
            output='',
            error='fuzzy_safe mode supports only single-line old_str. Use normalize_ws for multi-line edits.',
            new_content=file_content,
        )
    if len(old_str) > 120:
        return _tool_result(
            output='',
            error='fuzzy_safe mode only supports old_str up to 120 characters.',
            new_content=file_content,
        )
    return None


def _fuzzy_score_lines_over_threshold(
    file_content: str,
    old_str: str,
    *,
    min_ratio: float = 0.9,
) -> list[tuple[float, int, str]]:
    target = normalize_whitespace_for_match(old_str).strip()
    lines = file_content.splitlines(keepends=True)
    scored: list[tuple[float, int, str]] = []
    for idx, raw_line in enumerate(lines):
        normalized_line = normalize_whitespace_for_match(raw_line).strip()
        if not normalized_line:
            continue
        ratio = difflib.SequenceMatcher(None, target, normalized_line).ratio()
        if ratio >= min_ratio:
            scored.append((ratio, idx, raw_line))
    return scored


def _fuzzy_line_ending_for_raw_line(raw_line: str) -> str:
    if raw_line.endswith('\r\n'):
        return '\r\n'
    if raw_line.endswith('\n'):
        return '\n'
    return ''


def fuzzy_safe_replace(
    editor: Any,
    file_content: str,
    old_str: str,
    new_str: str,
) -> str | Any:
    pre = _fuzzy_precheck_old_str(old_str, file_content)
    if pre is not None:
        return pre

    scored = _fuzzy_score_lines_over_threshold(file_content, old_str)
    if not scored:
        return _tool_result(
            output='',
            error=build_no_match_error(editor, file_content, old_str, mode='fuzzy_safe'),
            new_content=file_content,
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    best_ratio, best_idx, best_line = scored[0]

    if len(scored) > 1 and abs(best_ratio - scored[1][0]) < 0.01:
        return _tool_result(
            output='',
            error='fuzzy_safe found ambiguous matches with similar confidence. Narrow old_str and retry.',
            new_content=file_content,
        )

    line_ending = _fuzzy_line_ending_for_raw_line(best_line)
    replacement = new_str
    if line_ending and not new_str.endswith(('\n', '\r')):
        replacement = f'{new_str}{line_ending}'

    updated = list(file_content.splitlines(keepends=True))
    updated[best_idx] = replacement
    return ''.join(updated)


def flex_quote_pattern(needle: str) -> str:
    parts: list[str] = []
    for ch in needle:
        if ch == '"':
            parts.append('(?:["\u201c\u201d])')
        elif ch == "'":
            parts.append("(?:['\u2018\u2019])")
        else:
            parts.append(re.escape(ch))
    return ''.join(parts)


def find_actual_substring_regex(editor: Any, haystack: str, needle: str) -> str | None:
    try:
        rx = re.compile(flex_quote_pattern(needle), re.DOTALL)
    except re.error:
        return None
    matches = list(rx.finditer(haystack))
    if len(matches) == 1:
        return matches[0].group(0)
    return None


def find_actual_substring_for_replace(editor: Any, haystack: str, needle: str) -> str | None:
    fe = _file_editor_module()
    if needle in haystack:
        return needle

    norm_needle = fe.normalize_quotes(needle)
    norm_hay = fe.normalize_quotes(haystack)
    if norm_needle and norm_needle in norm_hay:
        count = norm_hay.count(norm_needle)
        if count != 1:
            return None
        idx = norm_hay.index(norm_needle)
        if idx + len(needle) > len(haystack):
            return find_actual_substring_regex(editor, haystack, needle)
        actual = haystack[idx : idx + len(needle)]
        if fe.normalize_quotes(actual) != norm_needle:
            return find_actual_substring_regex(editor, haystack, needle)
        return actual

    return find_actual_substring_regex(editor, haystack, needle)


def preserve_quote_style_in_new_string(actual_old: str, new_str: str) -> str:
    doubles = [c for c in actual_old if c in '"\u201c\u201d']
    singles = [c for c in actual_old if c in "'\u2018\u2019"]
    di = 0
    si = 0
    out: list[str] = []
    for ch in new_str:
        if ch == '"':
            repl = doubles[di % len(doubles)] if doubles else '"'
            di += 1
            out.append(repl)
        elif ch == "'":
            repl = singles[si % len(singles)] if singles else "'"
            si += 1
            out.append(repl)
        else:
            out.append(ch)
    return ''.join(out)


def _apply_str_replace_when_not_exact(
    editor: Any,
    old_content: str,
    old_str: str,
    new_str: str,
    file_path: Path | None,
) -> str | Any:
    """Quote-normalize, ws-tolerant, then fuzzy_safe fallback (same precedence as before)."""
    actual = find_actual_substring_for_replace(editor, old_content, old_str)
    if actual is not None:
        if old_content.count(actual) != 1:
            return _tool_result(
                output='',
                error='ERROR: quote-normalized old_str is not unique.',
                new_content=old_content,
            )
        adjusted_new = preserve_quote_style_in_new_string(actual, new_str)
        return old_content.replace(actual, adjusted_new, 1)

    tolerant = ws_tolerant_replace(editor, old_content, old_str, new_str)
    fe = _file_editor_module()
    if isinstance(tolerant, fe.ToolResult):
        if '\n' not in old_str and '\r' not in old_str:
            fuzzy_result = fuzzy_safe_replace(editor, old_content, old_str, new_str)
            if not isinstance(fuzzy_result, fe.ToolResult):
                return fuzzy_result
            tolerant.error = ((tolerant.error or '') + '\n\n' + (fuzzy_result.error or ''))
        return tolerant
    return tolerant


def apply_str_replace(
    editor: Any,
    old_content: str,
    old_str: str,
    new_str: str,
    file_path: Path | None = None,
) -> str | Any:
    exact_count = old_content.count(old_str)

    if exact_count == 1:
        return old_content.replace(old_str, new_str, 1)
    if exact_count > 1:
        return _tool_result(
            output='',
            error=f'ERROR: old_str matches {exact_count} times. Must be unique.',
            new_content=old_content,
        )

    return _apply_str_replace_when_not_exact(editor, old_content, old_str, new_str, file_path)


def resolve_edit_content(file_text_val: str | None, new_str_val: str | None) -> str:
    return new_str_val or file_text_val or ''


def _apply_edit_implicit_legacy(
    editor: Any,
    old_content_str: str,
    file_text_val: str | None,
    old_str_val: str | None,
    new_str_val: str | None,
    insert_line: int | None,
    start_line: int | None,
    end_line: int | None,
    file_path: Path | None,
) -> str | Any:
    """Insert/replace/str_replace/full-file paths when ``edit_mode`` is unset."""
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
    if old_str_val and new_str_val:
        return apply_str_replace(
            editor,
            old_content_str,
            old_str_val,
            new_str_val,
            file_path=file_path,
        )
    if file_text_val:
        return file_text_val
    if new_str_val:
        return old_content_str + new_str_val
    return _tool_result(
        output='',
        error='No content provided for edit operation',
        new_content=old_content_str,
    )


def apply_edit_logic(
    editor: Any,
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

    def branch_replace() -> str | Any:
        if old_str_val and new_str_val:
            return apply_str_replace(
                editor, old_content_str, old_str_val, new_str_val, file_path=file_path
            )
        return _tool_result(
            output='',
            error='edit_mode=replace requires old_str and new_str.',
            new_content=old_content_str,
        )

    branches: dict[str, Callable[[], str | Any]] = {
        'format': branch_format,
        'section': branch_section,
        'range': branch_range,
        'patch': branch_patch,
        'replace': branch_replace,
    }
    if resolved_mode is not None:
        handler = branches.get(resolved_mode)
        if handler is not None:
            return handler()
    return _apply_edit_implicit_legacy(
        editor,
        old_content_str,
        file_text_val,
        old_str_val,
        new_str_val,
        insert_line,
        start_line,
        end_line,
        file_path,
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


def _apply_patch_hunks_to_content(content: str, hunks: list[tuple[str, str]]) -> str | Any:
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
