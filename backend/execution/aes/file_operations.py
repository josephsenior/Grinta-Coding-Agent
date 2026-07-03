"""File operation helpers for the runtime action execution server.

Extracted from action_execution_server.py to reduce its size and improve
maintainability. Contains: path resolution, file reading (text/binary/image/pdf/video),
file writing, file permissions, directory viewing, and the file editor execution wrapper.
"""

from __future__ import annotations

import base64
import mimetypes
import os
import re
from typing import TYPE_CHECKING, Any

from backend.core.enums import FileReadSource
from backend.core.logging.logger import app_logger as logger
from backend.core.os_capabilities import OS_CAPS
from backend.execution.utils.files.files import (
    read_lines,
)
from backend.execution.utils.test_output_summary import extract_test_summary
from backend.ledger.action import FileReadAction
from backend.ledger.observation import (
    ErrorObservation,
    FileReadObservation,
)

if TYPE_CHECKING:
    pass


def execute_file_editor(
    editor: Any,
    command: str,
    path: str,
    file_text: str | None = None,
    view_range: list[int] | None = None,
    new_str: str | None = None,
    old_string: str | None = None,
    replace_all: bool = False,
    insert_line: int | str | None = None,
    start_line: int | None = None,
    end_line: int | None = None,
    dry_run: bool = False,
    *,
    edit_mode: str | None = None,
    expected_hash: str | None = None,
) -> tuple[str, tuple[str | None, str | None], dict[str, Any]]:
    insert_line, error_msg = _parse_insert_line(insert_line)
    if error_msg:
        return _make_error_response(error_msg, 'INVALID_INSERT_LINE', False)

    result = _invoke_editor(
        editor,
        command,
        path,
        file_text,
        view_range,
        new_str,
        old_string,
        replace_all,
        insert_line,
        start_line,
        end_line,
        dry_run,
        edit_mode=edit_mode,
        expected_hash=expected_hash,
    )

    if result.error:
        return _make_editor_error_response(result, path, file_text, new_str, command)
    if not result.output:
        logger.warning('No output from file edit pipeline for %s', path)
        return _make_empty_response(result, command)
    return _make_success_response(result)


def _make_error_response(
    error_msg: str, error_code: str, retryable: bool
) -> tuple[str, tuple[None, None], dict[str, Any]]:
    return (
        error_msg,
        (None, None),
        {
            'tool': 'file_edit',
            'ok': False,
            'error_code': error_code,
            'retryable': retryable,
        },
    )


def _make_editor_error_response(
    result: Any, path: str, file_text: str | None, new_str: str | None, command: str
) -> tuple[str, tuple[None, None], dict[str, Any]]:
    from backend.core.errors.structured_edit_errors import (
        normalize_editor_error_response,
    )

    _ = (file_text, new_str)
    message, tool_result = normalize_editor_error_response(
        result,
        path=path,
        command=command,
    )
    return message, (None, None), tool_result


def _make_empty_response(
    result: Any, command: str
) -> tuple[str, tuple[None, None], dict[str, Any]]:
    return (
        '',
        (None, None),
        {
            'tool': 'file_edit',
            'ok': True,
            'error_code': None,
            'retryable': False,
            'operation': result.operation or command,
            'payload': result.metadata or {},
            'verification_passed': bool(
                (result.metadata or {}).get('verification_passed', False)
            ),
        },
    )


def _make_success_response(
    result: Any,
) -> tuple[str, tuple[str | None, str | None], dict[str, Any]]:
    return (
        result.output,
        (result.old_content, result.new_content),
        {
            'tool': 'file_edit',
            'ok': True,
            'error_code': None,
            'retryable': False,
            'operation': result.operation,
            'payload': result.metadata or {},
            'verification_passed': bool(
                (result.metadata or {}).get('verification_passed', False)
            ),
        },
    )


def _parse_insert_line(insert_line: int | str | None) -> tuple[int | None, str | None]:
    """Parse insert_line to integer and return (value, error_msg)."""
    if insert_line is not None and isinstance(insert_line, str):
        try:
            return int(insert_line), None
        except ValueError:
            return (
                None,
                f"Invalid insert_line value: '{insert_line}'. Expected an integer.",
            )
    return insert_line, None


def _invoke_editor(
    editor: Any,
    command: str,
    path: str,
    file_text: str | None,
    view_range: list[int] | None,
    new_str: str | None,
    old_string: str | None,
    replace_all: bool,
    insert_line: int | None,
    start_line: int | None,
    end_line: int | None,
    dry_run: bool,
    *,
    edit_mode: str | None = None,
    expected_hash: str | None = None,
) -> Any:
    """Safely invoke the editor with MISSING sentinels."""
    from backend.core.type_safety.sentinels import MISSING
    from backend.execution.utils.file_editor import ToolError, ToolResult

    try:
        return editor(
            command=command,
            path=path,
            file_text=file_text if file_text is not None else MISSING,
            view_range=view_range,
            new_str=new_str if new_str is not None else MISSING,
            old_string=old_string,
            replace_all=replace_all,
            insert_line=insert_line,
            start_line=start_line,
            end_line=end_line,
            dry_run=dry_run,
            edit_mode=edit_mode,
            expected_hash=expected_hash,
        )
    except ToolError as e:
        return ToolResult(output='', error=str(e))
    except TypeError as e:
        return ToolResult(output='', error=str(e))


def truncate_large_text(value: str, max_chars: int, *, label: str) -> str:
    """Truncate large text payloads to prevent oversized event observations."""
    if max_chars <= 0 or len(value) <= max_chars:
        return value
    half = max_chars // 2
    logger.warning(
        'Truncating oversized %s payload from %s chars to %s chars',
        label,
        len(value),
        max_chars,
    )
    return value[:half] + '\n[... Truncated by app due to size ...]\n' + value[-half:]


# ---------------------------------------------------------------------------
# Diff codec — priority-based lossy diff truncation
# ---------------------------------------------------------------------------
# Priority determines DROP ORDER (lowest priority dropped first when budget
# is tight). Output order is ALWAYS original diff order — lines are never
# reordered, only removed.
#
# Priority tiers:
#   100  diff metadata     diff --git, index, ---, +++      (always emitted)
#    90  hunk header       @@ -a,b +c,d @@                  (always emitted*)
#    80  change            + and - lines                     (dropped last)
#    40  adjacent context  ±2 context lines around +/-       (dropped second)
#     5  context           plain context lines               (dropped first)
#
# * Hunk headers always emitted in full and truncated modes. In skeleton
#   mode only file headers are emitted.

_DIFF_TRUNC_HARD_CAP = 20_000

_PRIORITY_DIFF_METADATA = 100
_PRIORITY_HUNK_HEADER = 90
_PRIORITY_CHANGE = 80
_PRIORITY_ADJ_CONTEXT = 40
_PRIORITY_CONTEXT = 5

_GENERATED_FILE_PATTERNS = (
    re.compile(r'(^|/)(package-lock\.json|yarn\.lock|pnpm-lock\.yaml)$'),
    re.compile(r'\.lock$'),
    re.compile(r'\.min\.js$'),
    re.compile(r'_pb2\.py$'),
    re.compile(r'\.generated\.'),
    re.compile(r'(^|/)(go\.sum|cargo\.lock|poetry\.lock)$'),
)

# Marker prefix emitted by the diff codec when output is lossy. Detected by
# the prompt layer (see observation_processors._handle_file_edit_observation)
# so the agent is told to re-read the file, even when the prompt layer itself
# does not truncate.
DIFF_CODEC_MARKER_PREFIX = '[DIFF_CODEC'

_DIFF_CODEC_VERSION = 1


def _is_generated_path(path: str) -> bool:
    if not path:
        return False
    return any(p.search(path) for p in _GENERATED_FILE_PATTERNS)


# --- Parsing ---


class _DiffLine:
    __slots__ = ('text', 'priority', 'category', 'file_idx', 'hunk_idx', 'kept')

    def __init__(self, text: str, priority: int, category: str, file_idx: int, hunk_idx: int):
        self.text = text
        self.priority = priority
        self.category = category
        self.file_idx = file_idx
        self.hunk_idx = hunk_idx
        self.kept = True


class _HunkInfo:
    __slots__ = ('idx', 'file_idx', 'additions', 'deletions', 'context_count', 'header_line')

    def __init__(self, idx: int, file_idx: int, header_line: _DiffLine):
        self.idx = idx
        self.file_idx = file_idx
        self.additions = 0
        self.deletions = 0
        self.context_count = 0
        self.header_line = header_line


class _FileInfo:
    __slots__ = ('idx', 'path', 'is_generated', 'metadata_lines', 'hunks')

    def __init__(self, idx: int, path: str):
        self.idx = idx
        self.path = path
        self.is_generated = _is_generated_path(path)
        self.metadata_lines: list[_DiffLine] = []
        self.hunks: list[_HunkInfo] = []


def _parse_diff(lines: list[str]) -> tuple[list[_DiffLine], list[_FileInfo], list[_HunkInfo]]:
    """Parse unified diff into classified lines.

    Returns (all_lines, files, hunks) where all_lines is in original order.
    Each line is classified with a priority and tagged with file/hunk indices.
    """
    all_lines: list[_DiffLine] = []
    files: list[_FileInfo] = []
    hunks: list[_HunkInfo] = []

    file_idx = -1
    hunk_idx = -1
    current_hunk_lines: list[_DiffLine] = []

    for raw in lines:
        if raw.startswith('diff --git'):
            path = _extract_path_from_diff_header(raw)
            file_idx += 1
            hunk_idx = -1
            current_hunk_lines = []
            fi = _FileInfo(file_idx, path)
            files.append(fi)
            dl = _DiffLine(raw, _PRIORITY_DIFF_METADATA, 'metadata', file_idx, -1)
            fi.metadata_lines.append(dl)
            all_lines.append(dl)
        elif raw.startswith('index ') or raw.startswith('--- ') or raw.startswith('+++ '):
            if file_idx >= 0:
                dl = _DiffLine(raw, _PRIORITY_DIFF_METADATA, 'metadata', file_idx, -1)
                files[file_idx].metadata_lines.append(dl)
                all_lines.append(dl)
            else:
                all_lines.append(_DiffLine(raw, _PRIORITY_CONTEXT, 'context', 0, -1))
        elif raw.startswith('@@'):
            hunk_idx += 1
            hdl = _DiffLine(raw, _PRIORITY_HUNK_HEADER, 'hunk_header', file_idx, hunk_idx)
            hi = _HunkInfo(hunk_idx, file_idx, hdl)
            if file_idx >= 0:
                files[file_idx].hunks.append(hi)
            hunks.append(hi)
            all_lines.append(hdl)
            current_hunk_lines = []
        elif raw.startswith('+'):
            dl = _DiffLine(raw, _PRIORITY_CHANGE, 'add', file_idx, hunk_idx)
            all_lines.append(dl)
            current_hunk_lines.append(dl)
            if hunk_idx >= 0:
                hunks[hunk_idx].additions += 1
        elif raw.startswith('-'):
            dl = _DiffLine(raw, _PRIORITY_CHANGE, 'remove', file_idx, hunk_idx)
            all_lines.append(dl)
            current_hunk_lines.append(dl)
            if hunk_idx >= 0:
                hunks[hunk_idx].deletions += 1
        else:
            dl = _DiffLine(raw, _PRIORITY_CONTEXT, 'context', file_idx, hunk_idx)
            all_lines.append(dl)
            current_hunk_lines.append(dl)
            if hunk_idx >= 0:
                hunks[hunk_idx].context_count += 1

    _mark_adjacent_context(current_hunk_lines)
    _mark_adjacent_context_for_all_hunks(all_lines, hunks)
    return all_lines, files, hunks


def _mark_adjacent_context_for_all_hunks(all_lines: list[_DiffLine], hunks: list[_HunkInfo]) -> None:
    """Mark context lines within ±2 lines of a change as adjacent context."""
    for hi in hunks:
        hunk_content = [
            dl for dl in all_lines
            if dl.hunk_idx == hi.idx and dl.category in ('context', 'add', 'remove')
        ]
        _mark_adjacent_context(hunk_content)


def _mark_adjacent_context(lines: list[_DiffLine]) -> None:
    """Mark context lines within ±2 positions of a +/- line as adjacent."""
    change_positions = [i for i, dl in enumerate(lines) if dl.category in ('add', 'remove')]
    if not change_positions:
        return
    adjacent = set()
    for pos in change_positions:
        for offset in (-2, -1, 0, 1, 2):
            adjacent.add(pos + offset)
    for i, dl in enumerate(lines):
        if dl.category == 'context' and i in adjacent:
            dl.priority = _PRIORITY_ADJ_CONTEXT
            dl.category = 'adj_context'


def _extract_path_from_diff_header(line: str) -> str:
    """Extract the file path from a 'diff --git a/path b/path' line."""
    parts = line.split()
    if len(parts) >= 4:
        return parts[-1].lstrip('b/')
    return ''


# --- Budget allocation ---


def _line_cost(dl: _DiffLine) -> int:
    return len(dl.text) + 1


def _structural_size(lines: list[_DiffLine]) -> int:
    """Size of metadata + hunk headers (always emitted, excluded from budget)."""
    return sum(_line_cost(dl) for dl in lines if dl.priority >= _PRIORITY_HUNK_HEADER)


def _content_size(lines: list[_DiffLine]) -> int:
    """Size of all non-structural lines."""
    return sum(_line_cost(dl) for dl in lines if dl.priority < _PRIORITY_HUNK_HEADER)


def _allocate_budget(
    lines: list[_DiffLine],
    hunks: list[_HunkInfo],
    files: list[_FileInfo],
    budget: int,
) -> tuple[str, dict[str, Any]]:
    """Allocate budget by dropping lowest-priority lines first.

    Returns (codec_mode, telemetry).
    """
    structural = _structural_size(lines)

    # --- Skeleton mode: structural metadata alone exceeds budget ---
    if structural > budget:
        return _emit_skeleton(files, budget)

    content_budget = budget - structural
    content_lines = [dl for dl in lines if dl.priority < _PRIORITY_HUNK_HEADER]
    total_content = sum(_line_cost(dl) for dl in content_lines)

    # --- Full mode: everything fits ---
    if total_content <= content_budget:
        return 'full', _build_telemetry(files, hunks, lines, dropped_any=False)

    # --- Truncated mode: drop by priority (lowest first) ---

    # Phase 1: drop plain context (priority 5)
    for dl in content_lines:
        if dl.priority == _PRIORITY_CONTEXT:
            dl.kept = False
    used = sum(_line_cost(dl) for dl in content_lines if dl.kept)
    if used <= content_budget:
        return 'truncated', _build_telemetry(files, hunks, lines, dropped_any=True)

    # Phase 2: drop adjacent context (priority 40)
    for dl in content_lines:
        if dl.priority == _PRIORITY_ADJ_CONTEXT:
            dl.kept = False
    used = sum(_line_cost(dl) for dl in content_lines if dl.kept)
    if used <= content_budget:
        return 'truncated', _build_telemetry(files, hunks, lines, dropped_any=True)

    # Phase 3: drop changes (priority 80) from lowest-change-count hunks first.
    # Keep all @@ headers regardless — the agent always knows WHERE a change
    # occurred even if it can't see WHAT changed.
    hunks_by_change_count = sorted(
        [h for h in hunks if h.additions + h.deletions > 0],
        key=lambda h: h.additions + h.deletions,
    )

    for hi in hunks_by_change_count:
        if used <= content_budget:
            break
        for dl in content_lines:
            if dl.hunk_idx == hi.idx and dl.category in ('add', 'remove') and dl.kept:
                dl.kept = False
                used -= _line_cost(dl)
        if used <= content_budget:
            break

    return 'truncated', _build_telemetry(files, hunks, lines, dropped_any=True)


# --- Emission ---


def _emit_skeleton(files: list[_FileInfo], budget: int) -> tuple[str, dict[str, Any]]:
    """Emit file headers only — no hunks, no content."""
    parts: list[str] = []
    total_omitted_hunks = 0
    total_omitted_add = 0
    total_omitted_del = 0
    files_omitted = 0

    for fi in files:
        for dl in fi.metadata_lines:
            parts.append(dl.text)
        om_hunks = len(fi.hunks)
        om_add = sum(h.additions for h in fi.hunks)
        om_del = sum(h.deletions for h in fi.hunks)
        total_omitted_hunks += om_hunks
        total_omitted_add += om_add
        total_omitted_del += om_del
        files_omitted += 1
        parts.append(
            f'[SKELETON: omitted_hunks={om_hunks}, '
            f'omitted_additions={om_add}, omitted_deletions={om_del}]'
        )

    summary = _format_fidelity_summary(
        mode='skeleton',
        coverage=0.0,
        files_full=0,
        files_partial=0,
        files_omitted=files_omitted,
        per_file=None,
        omitted_hunks=total_omitted_hunks,
        omitted_add=total_omitted_add,
        omitted_del=total_omitted_del,
    )
    parts.append(summary)
    return 'skeleton', {'_output': '\n'.join(parts), '_summary': summary}


def _emit_truncated(
    lines: list[_DiffLine],
    files: list[_FileInfo],
    hunks: list[_HunkInfo],
    path: str,
    telemetry: dict[str, Any],
) -> str:
    """Emit surviving lines in original order.

    Markers are emitted ONLY where changes (+/- lines) were dropped.
    Dropped context lines are silently omitted — the hunk header tells
    the agent where the hunk is, and the absence of context is normal
    for a truncated diff.
    """
    parts: list[str] = []
    dropped_add = 0
    dropped_del = 0
    marker_pending = False

    for dl in lines:
        if dl.kept:
            if marker_pending:
                parts.append(
                    f'{DIFF_CODEC_MARKER_PREFIX}: +{dropped_add}/-{dropped_del} lines dropped]'
                )
                marker_pending = False
                dropped_add = 0
                dropped_del = 0
            parts.append(dl.text)
        else:
            if dl.category in ('add', 'remove'):
                if dl.category == 'add':
                    dropped_add += 1
                else:
                    dropped_del += 1
                marker_pending = True

    if marker_pending:
        parts.append(
            f'{DIFF_CODEC_MARKER_PREFIX}: +{dropped_add}/-{dropped_del} lines dropped]'
        )

    return '\n'.join(parts)


# --- Fidelity summary ---


def _build_telemetry(
    files: list[_FileInfo],
    hunks: list[_HunkInfo],
    lines: list[_DiffLine],
    dropped_any: bool,
) -> dict[str, Any]:
    total_add = sum(h.additions for h in hunks)
    total_del = sum(h.deletions for h in hunks)
    kept_add = sum(1 for dl in lines if dl.category == 'add' and dl.kept)
    kept_del = sum(1 for dl in lines if dl.category == 'remove' and dl.kept)
    total_changes = total_add + total_del
    kept_changes = kept_add + kept_del
    coverage = (kept_changes / total_changes * 100) if total_changes else 100.0

    per_file: list[dict[str, Any]] = []
    files_full = 0
    files_partial = 0
    files_omitted = 0

    for fi in files:
        f_hunks = [h for h in fi.hunks if h.file_idx == fi.idx]
        f_om_add = sum(h.additions for h in f_hunks) - sum(
            1 for dl in lines if dl.file_idx == fi.idx and dl.category == 'add' and dl.kept
        )
        f_om_del = sum(h.deletions for h in f_hunks) - sum(
            1 for dl in lines if dl.file_idx == fi.idx and dl.category == 'remove' and dl.kept
        )
        f_om_hunks = sum(1 for h in f_hunks if not any(
            dl.kept for dl in lines if dl.hunk_idx == h.idx and dl.category in ('add', 'remove')
        ))
        if f_om_add == 0 and f_om_del == 0:
            files_full += 1
        elif f_om_add == sum(h.additions for h in f_hunks) and f_om_del == sum(h.deletions for h in f_hunks):
            files_omitted += 1
        else:
            files_partial += 1
        per_file.append({
            'path': fi.path,
            'omitted_hunks': f_om_hunks,
            'omitted_additions': f_om_add,
            'omitted_deletions': f_om_del,
        })

    return {
        'coverage': coverage,
        'files_full': files_full,
        'files_partial': files_partial,
        'files_omitted': files_omitted,
        'per_file': per_file,
        'omitted_hunks': sum(1 for h in hunks if not any(
            dl.kept for dl in lines if dl.hunk_idx == h.idx and dl.category in ('add', 'remove')
        )),
        'omitted_add': total_add - kept_add,
        'omitted_del': total_del - kept_del,
    }


def _format_fidelity_summary(
    mode: str,
    coverage: float,
    files_full: int,
    files_partial: int,
    files_omitted: int,
    per_file: list[dict[str, Any]] | None,
    omitted_hunks: int = 0,
    omitted_add: int = 0,
    omitted_del: int = 0,
) -> str:
    parts = [
        f'[DIFF_CODEC v{_DIFF_CODEC_VERSION} mode={mode}',
        f'change_line_coverage={coverage:.1f}%',
        f'files_fully_represented={files_full}',
        f'files_partially_represented={files_partial}',
        f'files_omitted={files_omitted}]',
    ]
    if per_file:
        for pf in per_file:
            if pf['omitted_additions'] > 0 or pf['omitted_deletions'] > 0 or pf['omitted_hunks'] > 0:
                parts.append(
                    f'  {pf["path"]}: omitted_hunks={pf["omitted_hunks"]}, '
                    f'omitted_additions={pf["omitted_additions"]}, '
                    f'omitted_deletions={pf["omitted_deletions"]}'
                )
    return '\n'.join(parts)


# --- Main entry point ---


def truncate_diff(value: str, *, path: str = '') -> str:
    """Truncate diff output using a priority-based lossy codec.

    Lines are classified by priority and dropped lowest-first when budget
    is tight. Output order is always original diff order. The codec operates
    in three modes:

    - **full**: everything fits, nothing dropped.
    - **truncated**: some lines dropped (context first, then adjacent context,
      then changes from lowest-density hunks). Hunk headers always kept.
    - **skeleton**: structural metadata alone exceeds budget — file headers
      only, no hunks, no content.

    A fidelity summary is always emitted when the codec is active (i.e. when
    the diff exceeds the budget). All lossy outputs carry the ``[DIFF_CODEC``
    marker prefix; the prompt layer (observation_processors) detects it and
    emits a re-read footer.
    """
    if len(value) <= _DIFF_TRUNC_HARD_CAP:
        return value

    lines_text = value.split('\n')
    all_lines, files, hunks = _parse_diff(lines_text)

    if not files:
        # Not a standard unified diff — fall back to head/tail truncation.
        return _fallback_head_tail(value, path)

    mode, telemetry = _allocate_budget(all_lines, hunks, files, _DIFF_TRUNC_HARD_CAP)

    if mode == 'skeleton':
        logger.warning(
            'Diff skeleton mode (structural metadata > %s chars), path=%s',
            _DIFF_TRUNC_HARD_CAP,
            path,
        )
        return telemetry['_output']

    if mode == 'full':
        return value

    # truncated
    logger.warning(
        'Diff truncated from %s chars (mode=%s, coverage=%.1f%%), path=%s',
        len(value),
        mode,
        telemetry['coverage'],
        path,
    )
    body = _emit_truncated(all_lines, files, hunks, path, telemetry)
    summary = _format_fidelity_summary(
        mode='truncated',
        coverage=telemetry['coverage'],
        files_full=telemetry['files_full'],
        files_partial=telemetry['files_partial'],
        files_omitted=telemetry['files_omitted'],
        per_file=telemetry['per_file'],
        omitted_hunks=telemetry['omitted_hunks'],
        omitted_add=telemetry['omitted_add'],
        omitted_del=telemetry['omitted_del'],
    )
    return body + '\n' + summary


def _fallback_head_tail(value: str, path: str) -> str:
    """Fallback for non-diff text that exceeds the cap."""
    head = value[:5000]
    tail = value[-2000:]
    if '\n' in head:
        head = head[: head.rfind('\n')]
    if '\n' in tail:
        tail = tail[tail.find('\n') + 1 :]
    path_part = f' path={path}' if path else ''
    marker = (
        f'{DIFF_CODEC_MARKER_PREFIX}{path_part}] non-diff content shortened '
        '(head/tail kept) — re-read the source to see the full text'
    )
    return f'{head}\n{marker}\n{tail}'


# Default max chars for bash command output (configurable via env var).
_DEFAULT_MAX_CMD_OUTPUT_CHARS = 40_000


def _get_max_cmd_output_chars(max_chars: int | None) -> int:
    """Resolve max_chars from arg or env."""
    if max_chars is not None:
        return max_chars
    raw = os.environ.get('APP_MAX_CMD_OUTPUT_CHARS', '')
    try:
        return int(raw) if raw else _DEFAULT_MAX_CMD_OUTPUT_CHARS
    except (ValueError, TypeError):
        return _DEFAULT_MAX_CMD_OUTPUT_CHARS


def _extract_truncation_lines(
    lines: list[str], head_budget: int, tail_budget: int
) -> tuple[list[str], list[str]]:
    """Extract head and tail lines within fixed budgets."""
    head_lines: list[str] = []
    head_chars = 0
    for line in lines:
        if head_chars + len(line) > head_budget:
            break
        head_lines.append(line)
        head_chars += len(line)

    tail_lines: list[str] = []
    tail_chars = 0
    for line in reversed(lines):
        if tail_chars + len(line) > tail_budget:
            break
        tail_lines.insert(0, line)
        tail_chars += len(line)

    return head_lines, tail_lines


# Regex for lines that likely contain error/failure context worth surfacing.
_ERROR_LINE_RE = re.compile(
    r'\b(?:Error|Exception|Traceback|FAILED|FAIL:'
    r'|AssertionError|panic|PANIC'
    r'|ModuleNotFoundError|ImportError|FileNotFoundError'
    r'|PermissionError|RuntimeError|TypeError|ValueError'
    r'|KeyError|AttributeError|SyntaxError|IndentationError)\b',
    re.IGNORECASE,
)


def _extract_error_context(
    lines: list[str],
    head_count: int,
    tail_count: int,
    budget: int,
) -> list[str]:
    """Extract error-context lines from the truncated middle of output."""
    if head_count + tail_count >= len(lines):
        return []

    middle = lines[head_count : len(lines) - tail_count]
    error_indices = _find_error_line_indices(middle)
    if not error_indices:
        return []

    selected = _expand_error_context(error_indices, len(middle))
    return _collect_lines_within_budget(middle, selected, budget)


def _find_error_line_indices(middle: list[str]) -> list[int]:
    return [i for i, line in enumerate(middle) if _ERROR_LINE_RE.search(line)]


def _expand_error_context(error_indices: list[int], middle_len: int) -> set[int]:
    selected: set[int] = set()
    for idx in error_indices:
        for offset in range(-2, 3):
            pos = idx + offset
            if 0 <= pos < middle_len:
                selected.add(pos)
    return selected


def _collect_lines_within_budget(
    middle: list[str], selected: set[int], budget: int
) -> list[str]:
    result: list[str] = []
    chars = 0
    prev_idx = -2
    for idx in sorted(selected):
        line = middle[idx]
        if chars + len(line) > budget:
            break
        if idx > prev_idx + 1 and result:
            gap_marker = '  ...\n'
            if chars + len(gap_marker) + len(line) > budget:
                break
            result.append(gap_marker)
            chars += len(gap_marker)
        result.append(line)
        chars += len(line)
        prev_idx = idx
    return result


def truncate_cmd_output(output: str, max_chars: int | None = None) -> str:
    """Truncate bash command output with error-aware head+tail strategy.

    - Preserves the first lines for command context (15% budget)
    - Surfaces error/traceback lines from the truncated middle (10% budget)
    - Always preserves the last lines for final status/results (75% budget)
    - Appends a [TEST_SUMMARY] block AFTER truncation so it never consumes
      the truncation budget

    Args:
        output: Raw command output string.
        max_chars: Maximum number of characters to keep. Reads
            ``APP_MAX_CMD_OUTPUT_CHARS`` env var if not set, defaulting to
            40 000 characters (~80-120 lines for typical terminal output).

    Returns:
        Possibly-truncated output string with a clear [TRUNCATED] notice.
    """
    max_chars = _get_max_cmd_output_chars(max_chars)

    # Extract test summary BEFORE truncation but append it AFTER, so
    # the summary block never inflates the char budget.
    test_summary = extract_test_summary(output)

    if max_chars <= 0 or len(output) <= max_chars:
        if test_summary:
            return test_summary + '\n\n' + output
        return output

    lines = output.splitlines(keepends=True)
    total_lines = len(lines)

    # Budget split: 15% head, 10% error context, 75% tail.
    head_budget = int(max_chars * 0.15)
    error_budget = int(max_chars * 0.10)
    tail_budget = max_chars - head_budget - error_budget

    head_lines, tail_lines = _extract_truncation_lines(lines, head_budget, tail_budget)

    # Extract error context from the truncated middle.
    error_context = _extract_error_context(
        lines, len(head_lines), len(tail_lines), error_budget
    )

    skipped = total_lines - len(head_lines) - len(tail_lines)
    notice = (
        f'\n[APP: Output truncated — {skipped} lines hidden. '
        f'Showing first {len(head_lines)} and last {len(tail_lines)} lines]'
    )
    notice += '\n'

    logger.debug(
        'Truncated bash output from %d lines (%d chars) → head=%d tail=%d error_ctx=%d',
        total_lines,
        len(output),
        len(head_lines),
        len(tail_lines),
        len(error_context),
    )

    parts = [''.join(head_lines), notice]
    if error_context:
        parts.append('[ERROR_CONTEXT from truncated middle]\n')
        parts.append(''.join(error_context))
        parts.append('\n')
    parts.append(''.join(tail_lines))

    result = ''.join(parts)

    # Append test summary AFTER truncation — outside the char budget.
    if test_summary:
        result = test_summary + '\n\n' + result

    return result


def get_max_edit_observation_chars() -> int:
    """Read and validate max edit observation payload size from environment."""
    raw_value = os.environ.get('APP_MAX_EDIT_OBS_CHARS', '500000')
    try:
        parsed = int(raw_value)
    except (TypeError, ValueError):
        logger.warning(
            'Invalid APP_MAX_EDIT_OBS_CHARS=%r; using default 500000',
            raw_value,
        )
        return 500000
    if parsed <= 0:
        logger.warning(
            'Non-positive APP_MAX_EDIT_OBS_CHARS=%s; using default 500000',
            parsed,
        )
        return 500000
    return parsed


def resolve_path(path: str, working_dir: str) -> str:
    """Resolve a relative or absolute path to an absolute path with security validation.

    Args:
        path: File path (relative or absolute)
        working_dir: Current working directory

    Returns:
        Absolute file path as string (validated and safe)

    """
    from backend.core.type_safety.path_validation import SafePath

    safe_path = SafePath.validate(
        path,
        workspace_root=working_dir,
        must_be_relative=True,
    )
    return str(safe_path.path)


def encode_binary_file(
    filepath: str,
    file_data: bytes,
    mime_type: str | None,
    default_mime: str,
) -> str:
    """Encode binary file data as base64 data URL."""
    encoded_data = base64.b64encode(file_data).decode('utf-8')
    effective_mime = mime_type or default_mime
    return f'data:{effective_mime};base64,{encoded_data}'


def read_image_file(filepath: str) -> FileReadObservation:
    """Read and encode an image file."""
    with open(filepath, 'rb') as file:
        image_data = file.read()
        mime_type, _ = mimetypes.guess_type(filepath)
        encoded_image = encode_binary_file(filepath, image_data, mime_type, 'image/png')
    return FileReadObservation(path=filepath, content=encoded_image)


def read_pdf_file(filepath: str) -> FileReadObservation:
    """Read and encode a PDF file."""
    with open(filepath, 'rb') as file:
        pdf_data = file.read()
        encoded_pdf = encode_binary_file(
            filepath, pdf_data, 'application/pdf', 'application/pdf'
        )
    return FileReadObservation(path=filepath, content=encoded_pdf)


def read_video_file(filepath: str) -> FileReadObservation:
    """Read and encode a video file."""
    with open(filepath, 'rb') as file:
        video_data = file.read()
        mime_type, _ = mimetypes.guess_type(filepath)
        encoded_video = encode_binary_file(filepath, video_data, mime_type, 'video/mp4')
    return FileReadObservation(path=filepath, content=encoded_video)


def _read_document_text(
    filepath: str,
    *,
    label: str,
    extractor,
) -> FileReadObservation | ErrorObservation:
    try:
        content = extractor(filepath)
    except RuntimeError as exc:
        return ErrorObservation(str(exc))
    except Exception as exc:
        return ErrorObservation(f'Failed to read {label}: {filepath}: {exc}')
    return FileReadObservation(path=filepath, content=content)


def read_pdf_text_file(filepath: str) -> FileReadObservation | ErrorObservation:
    """Extract text from a PDF file."""
    from backend.execution.document_readers import extract_pdf_text

    return _read_document_text(filepath, label='PDF', extractor=extract_pdf_text)


def read_docx_file(filepath: str) -> FileReadObservation | ErrorObservation:
    """Extract text from a DOCX file."""
    from backend.execution.document_readers import extract_docx_text

    return _read_document_text(filepath, label='DOCX', extractor=extract_docx_text)


def read_pptx_file(filepath: str) -> FileReadObservation | ErrorObservation:
    """Extract text from a PPTX file."""
    from backend.execution.document_readers import extract_pptx_text

    return _read_document_text(filepath, label='PPTX', extractor=extract_pptx_text)


def read_text_file(filepath: str, action: FileReadAction) -> FileReadObservation:
    """Read a text file with optional line range.

    Args:
        filepath: The path to the text file.
        action: The file read action with start/end line parameters.

    Returns:
        FileReadObservation: The observation with file content.

    Raises:
        IsADirectoryError: If filepath is a directory.

    """
    if os.path.isdir(filepath):
        raise IsADirectoryError(f'{filepath} is a directory, not a file')

    with open(filepath, encoding='utf-8') as f:
        all_lines = f.readlines()

    start = (action.start or 1) - 1
    end = action.end if action.end is not None else -1

    lines = read_lines(all_lines, start, end)

    return FileReadObservation(
        path=filepath,
        content=''.join(lines),
    )


def handle_file_read_errors(filepath: str, working_dir: str) -> ErrorObservation:
    """Handle file reading errors with appropriate error messages."""
    if not os.path.exists(filepath):
        candidates = os.listdir(working_dir) if os.path.isdir(working_dir) else []
        hint = ''
        if candidates:
            import difflib

            matches = difflib.get_close_matches(
                os.path.basename(filepath), candidates, n=3
            )
            if matches:
                hint = f' Did you mean: {", ".join(matches)}?'
        return ErrorObservation(f'File not found: {filepath}.{hint}')
    return ErrorObservation(
        f'Cannot read file: {filepath} (permission denied or other error)'
    )


def ensure_directory_exists(filepath: str) -> None:
    """Create parent directories for a file path if they don't exist."""
    parent = os.path.dirname(filepath)
    if parent:
        os.makedirs(parent, exist_ok=True)


def set_file_permissions(
    filepath: str,
    file_exists: bool,
    file_stat: os.stat_result | None,
) -> None:
    """Set file permissions and ownership with preservation for existing files."""
    if OS_CAPS.is_windows:
        return  # Windows doesn't support chmod/chown

    if file_exists and file_stat is not None:
        try:
            os.chmod(filepath, file_stat.st_mode)
            if hasattr(os, 'chown'):
                os.chown(filepath, file_stat.st_uid, file_stat.st_gid)
        except (OSError, PermissionError):
            logger.debug('Could not restore permissions for %s', filepath)
    else:
        try:
            os.chmod(filepath, 0o664)
        except (OSError, PermissionError):
            logger.debug('Could not set default permissions for %s', filepath)


def handle_directory_view(full_path: str, display_path: str) -> FileReadObservation:
    """Handle viewing a directory by listing files up to 2 levels deep."""
    # List files up to 2 levels deep
    file_list, hidden_count = _list_directory_recursive(full_path, max_depth=2)

    content = _format_directory_listing(display_path, file_list, hidden_count)

    return FileReadObservation(
        content=content,
        path=display_path,
        impl_source=FileReadSource.FILE_EDITOR,
    )


def _list_directory_recursive(
    dir_path: str,
    max_depth: int,
    current_depth: int = 0,
    base_path: str = '',
) -> tuple[list[str], int]:
    """Recursively list directory entries up to max_depth."""
    if current_depth >= max_depth:
        return [], 0

    entries = []
    hidden_count = 0

    try:
        for entry in os.listdir(dir_path):
            # Skip hidden files/directories (starting with .)
            if entry.startswith('.'):
                hidden_count += 1
                continue

            entry_path = os.path.join(dir_path, entry)
            relative_path = os.path.join(base_path, entry) if base_path else entry

            try:
                if os.path.isdir(entry_path):
                    entries.append(relative_path + '/')
                    # Recursively list subdirectories
                    sub_entries, sub_hidden = _list_directory_recursive(
                        entry_path, max_depth, current_depth + 1, relative_path
                    )
                    entries.extend(sub_entries)
                    hidden_count += sub_hidden
                else:
                    entries.append(relative_path)
            except (OSError, ValueError):
                # Skip entries that can't be accessed
                continue
    except (OSError, PermissionError, NotADirectoryError):
        # Cannot read directory
        pass

    return entries, hidden_count


def _format_directory_listing(
    display_path: str, file_list: list[str], hidden_count: int
) -> str:
    """Format directory listing for display."""
    # Sort: directories first (with /), then files
    directories = sorted(
        [f for f in file_list if f.endswith('/')], key=lambda s: s.lower()
    )
    files = sorted(
        [f for f in file_list if not f.endswith('/')], key=lambda s: s.lower()
    )
    sorted_entries = directories + files

    display_path_normalized = display_path.replace('\\', '/')
    lines = [
        f"Here's the files and directories up to 2 levels deep in {display_path_normalized}, excluding hidden items:"
    ]

    # Include the directory itself first (with trailing slash)
    if not display_path_normalized.endswith('/'):
        lines.append(f'{display_path_normalized}/')

    # Then list entries inside the directory
    for entry in sorted_entries:
        entry_normalized = entry.replace('\\', '/')
        sep = '' if display_path_normalized.endswith('/') else '/'
        lines.append(f'{display_path_normalized}{sep}{entry_normalized}')

    if hidden_count > 0:
        lines.append('')
        lines.append(
            f'{hidden_count} hidden files/directories in this directory are excluded. '
            f'{_hidden_items_command_hint(display_path_normalized)}'
        )

    return '\n'.join(lines)


def _hidden_items_command_hint(display_path_normalized: str) -> str:
    """Return a platform-aware hint for viewing hidden directory entries."""
    if OS_CAPS.is_windows:
        return f'Use `Get-ChildItem -Force {display_path_normalized}` to see them.'
    return f"You can use 'ls -la {display_path_normalized}' to see them."  # type: ignore
