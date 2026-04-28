"""Per-tool argument summarisers and streaming hints.

The original :func:`summarize_tool_arguments` was a 100+ line if/elif chain
(cyclomatic complexity 105 according to ``radon``).  Each branch is now a small
function looked up via the :data:`_TOOL_SUMMARIZERS` dispatch table, which
keeps individual handlers at single-digit complexity.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable


def _trunc(s: str, max_len: int = 100) -> str:
    s = ' '.join(s.split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + '…'


def _pluralize_result_label(label: str, count: int) -> str:
    singular = label[:-1] if label.endswith('s') and len(label) > 1 else label
    return singular if count == 1 else (label if label.endswith('s') else f'{label}s')


def _preview_result_item(item: Any, *, max_len: int) -> str:
    if isinstance(item, str) and item.strip():
        return _trunc(item, max_len)
    if isinstance(item, dict):
        for key in ('title', 'name', 'path', 'file', 'url', 'id'):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return _trunc(value, max_len)
    return ''


def _summarize_result_collection(
    items: list[Any], *, label: str = 'results', max_len: int
) -> str:
    count = len(items)
    noun = _pluralize_result_label(label, count)
    summary = f'{count} {noun}'
    preview = (
        _preview_result_item(items[0], max_len=max(20, max_len // 2)) if items else ''
    )
    if preview:
        return _trunc(f'{summary} · {preview}', max_len)
    return summary


def _summarize_raw_mcp_text(text: str, *, max_len: int) -> str:
    from backend.cli._tool_display.constants import _LOW_SIGNAL_MCP_LINES, _RAW_URL_RE

    lines = [raw.strip(' \t-*•') for raw in (text or '').splitlines() if raw.strip()]
    if not lines:
        return ''

    preview = next(
        (
            line
            for line in lines
            if line.lower() not in _LOW_SIGNAL_MCP_LINES
            and not _RAW_URL_RE.fullmatch(line)
        ),
        lines[0],
    )
    suffix = _raw_mcp_suffix(text, lines, _RAW_URL_RE)
    if not suffix:
        return _trunc(preview, max_len)
    budget = max(20, max_len - len(suffix))
    return f'{_trunc(preview, budget)}{suffix}'


def _raw_mcp_suffix(text: str, lines: list[str], url_re: Any) -> str:
    suffix_parts: list[str] = []
    if len(lines) > 1:
        suffix_parts.append(f'{len(lines)} lines')
    url_count = len(url_re.findall(text))
    if url_count > 1:
        suffix_parts.append(f'{url_count} links')
    if not suffix_parts:
        return ''
    return ' · ' + ' · '.join(suffix_parts)


# ---------------------------------------------------------------------------
# Terminal-manager helpers (open / input / read)
# ---------------------------------------------------------------------------


def _term_open_summary(args: dict[str, Any]) -> str:
    cmd = args.get('command')
    cwd = args.get('cwd')
    if isinstance(cmd, str) and cmd.strip():
        line = f'open · {_trunc(cmd, 100)}'
        if isinstance(cwd, str) and cwd.strip():
            line = f'{line} · cwd {_trunc(cwd, 48)}'
        return line
    return 'open (no command yet)'


def _term_input_summary(args: dict[str, Any]) -> str:
    sid = str(args.get('session_id') or '')
    inv = str(args.get('input') or '')
    ctrl = args.get('control')
    if isinstance(ctrl, str) and ctrl.strip():
        bits = ['input', f'ctrl {ctrl}']
        if sid.strip():
            bits.insert(1, _trunc(sid, 24))
        return ' · '.join(bits)
    if inv.strip():
        if sid.strip():
            return f'input · {_trunc(sid, 20)} · {_trunc(inv, 70)}'
        return f'input · {_trunc(inv, 90)}'
    if sid.strip():
        return f'input · {_trunc(sid, 40)}'
    return 'input…'


def _term_read_summary(args: dict[str, Any]) -> str:
    sid = str(args.get('session_id') or '')
    if sid.strip():
        return f'read · {_trunc(sid, 44)}'
    return 'read (no session)'


_TERM_SUMMARIZERS: dict[str, Callable[[dict[str, Any]], str]] = {
    'open': _term_open_summary,
    'input': _term_input_summary,
    'read': _term_read_summary,
}


def _summarize_terminal_manager_args(args: dict[str, Any]) -> str:
    """Human-readable line for ``terminal_manager`` (open / input / read)."""
    op = str(args.get('action') or '').strip().lower()
    handler = _TERM_SUMMARIZERS.get(op)
    return handler(args) if handler else 'terminal…'


def _streaming_hint_terminal_manager(partial_json: str) -> str:
    """Best-effort label while ``terminal_manager`` JSON is still streaming."""
    m_act = re.search(r'"action"\s*:\s*"(open|input|read)"', partial_json)
    if not m_act:
        return ''
    op = m_act.group(1)
    if op == 'open':
        m_cmd = re.search(
            r'"command"\s*:\s*"((?:\\.|[^"\\])*)"', partial_json, re.DOTALL
        )
        if m_cmd:
            raw_c = m_cmd.group(1).replace('\\n', '\n').replace('\\"', '"')
            return f'open · {_trunc(raw_c, 90)}'
        return 'open'
    if op == 'input':
        return _stream_hint_input(partial_json)
    if op == 'read':
        m_sid = re.search(r'"session_id"\s*:\s*"((?:\\.|[^"\\])*)"', partial_json)
        if m_sid:
            return f'read · {_trunc(m_sid.group(1), 40)}'
        return 'read'
    return ''


def _stream_hint_input(partial_json: str) -> str:
    m_sid = re.search(r'"session_id"\s*:\s*"((?:\\.|[^"\\])*)"', partial_json)
    sid = m_sid.group(1) if m_sid else ''
    m_ctrl = re.search(r'"control"\s*:\s*"((?:\\.|[^"\\])*)"', partial_json)
    m_inp = re.search(r'"input"\s*:\s*"((?:\\.|[^"\\])*)"', partial_json, re.DOTALL)
    parts: list[str] = ['input']
    if sid:
        parts.append(_trunc(sid, 22))
    if m_ctrl:
        parts.append(f'ctrl {m_ctrl.group(1)[:24]}')
    elif m_inp:
        raw = m_inp.group(1).replace('\\n', '\n').replace('\\"', '"')
        parts.append(_trunc(raw, 55))
    return ' · '.join(parts)


# ---------------------------------------------------------------------------
# Per-tool summarizers
# ---------------------------------------------------------------------------


def _arg_str(args: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = args.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _summary_shell(args: dict[str, Any]) -> str:
    cmd = _arg_str(args, 'command')
    return f'$ {_trunc(cmd, 120)}' if cmd else 'command…'


def _summary_text_editor(args: dict[str, Any]) -> str:
    cmd = str(args.get('command', '') or '')
    path = str(args.get('path', '') or '')
    if cmd == 'create_file' and path:
        return f'{path} · new file'
    parts = [p for p in (path, cmd) if p]
    return ' · '.join(parts) if parts else 'file…'


def _summary_think(args: dict[str, Any]) -> str:
    text = _arg_str(args, 'thought', 'content')
    return _trunc(text, 160) if text else '…'


def _summary_finish(args: dict[str, Any]) -> str:
    msg = _arg_str(args, 'message')
    return _trunc(msg, 120) if msg else 'done'


def _summary_memory(args: dict[str, Any]) -> str:
    op = args.get('operation') or args.get('action')
    q = args.get('query') or args.get('key')
    bits = [str(x) for x in (op, q) if x]
    return _trunc(' · '.join(bits), 120) if bits else 'memory…'


def _summary_task_tracker(args: dict[str, Any]) -> str:
    op = args.get('operation') or args.get('command')
    title = args.get('title') or args.get('task')
    task_list = args.get('task_list')
    count = len(task_list) if isinstance(task_list, list) else 0
    parts = [str(x) for x in (op, title) if x]
    if count:
        parts.append(f'{count} task{"s" if count != 1 else ""}')
    return _trunc(' · '.join(parts), 160) if parts else 'tasks…'


def _summary_search_code(args: dict[str, Any]) -> str:
    q = _arg_str(args, 'query', 'pattern')
    path = _arg_str(args, 'path', 'root', 'directory')
    bits: list[str] = []
    if q:
        bits.append(_trunc(q, 80))
    if path:
        bits.append(path)
    return ' in '.join(bits) if bits else 'search…'


def _summary_code_intelligence(args: dict[str, Any]) -> str:
    cmd = args.get('command') or args.get('query_type')
    path = args.get('file') or args.get('path')
    sym = args.get('symbol') or args.get('name')
    bits = [str(x) for x in (cmd, sym or path) if x]
    return _trunc(' · '.join(bits), 120) if bits else 'LSP…'


def _summary_explore_tree(args: dict[str, Any]) -> str:
    p = _arg_str(args, 'path', 'root')
    return p if p else 'directory tree'


def _summary_read_symbol(args: dict[str, Any]) -> str:
    sym = args.get('symbol') or args.get('name')
    path = args.get('file') or args.get('path')
    bits = [str(x) for x in (sym, path) if x]
    return _trunc(' · '.join(bits), 120) if bits else 'symbol…'


def _summary_analyze_project(_args: dict[str, Any]) -> str:
    return 'scan workspace'


def _summary_apply_patch(_args: dict[str, Any]) -> str:
    # The ``patch`` argument is a multi-KB unified-diff blob; never display it.
    return 'apply patch'


def _summary_verify_file(args: dict[str, Any]) -> str:
    path = args.get('path') or args.get('file')
    if isinstance(path, str):
        return path or 'file'
    return 'verify'


def _summary_delegate_task(args: dict[str, Any]) -> str:
    desc = _arg_str(args, 'task_description', 'description')
    return _trunc(desc, 120) if desc else 'sub-task…'


def _summary_communicate(args: dict[str, Any]) -> str:
    msg = _arg_str(args, 'message', 'content', 'text')
    return _trunc(msg, 120) if msg else '…'


def _summary_call_mcp(args: dict[str, Any]) -> str:
    inner = _arg_str(args, 'tool_name', 'name')
    return f'→ {_trunc(inner, 80)}' if inner else 'MCP tool…'


def _summary_checkpoint(args: dict[str, Any]) -> str:
    label = _arg_str(args, 'label', 'message')
    return _trunc(label, 80) if label else 'save state'


def _summary_summarize_context(_args: dict[str, Any]) -> str:
    return 'compress conversation'


def _summary_symbol_editor(args: dict[str, Any]) -> str:
    path = args.get('path')
    cmd = args.get('command')
    if cmd == 'edit_symbols':
        return _summary_symbol_editor_edit(path, args)
    bits = [str(x) for x in (cmd, path) if x]
    return _trunc(' · '.join(bits), 120) if bits else 'Code edit…'


def _summary_symbol_editor_edit(path: Any, args: dict[str, Any]) -> str:
    edits = args.get('edits') or args.get('symbol_edits') or []
    n = len(edits) if isinstance(edits, list) else 0
    bits = [
        'edit_symbols',
        str(path) if path else '',
        f'{n} symbols' if n else '',
    ]
    joined = ' · '.join(b for b in bits if b)
    return _trunc(joined, 120) if joined else 'Code batch…'


def _summary_shared_board(args: dict[str, Any]) -> str:
    op = args.get('operation') or args.get('command')
    return str(op) if op else 'board…'


_TOOL_SUMMARIZERS: dict[str, Callable[[dict[str, Any]], str]] = {
    'execute_bash': _summary_shell,
    'execute_powershell': _summary_shell,
    'text_editor': _summary_text_editor,
    'think': _summary_think,
    'agent_think': _summary_think,
    'finish': _summary_finish,
    'memory_manager': _summary_memory,
    'task_tracker': _summary_task_tracker,
    'search_code': _summary_search_code,
    'code_intelligence': _summary_code_intelligence,
    'explore_tree_structure': _summary_explore_tree,
    'read_symbol_definition': _summary_read_symbol,
    'analyze_project_structure': _summary_analyze_project,
    'apply_patch': _summary_apply_patch,
    'verify_file_lines': _summary_verify_file,
    'delegate_task': _summary_delegate_task,
    'communicate_with_user': _summary_communicate,
    'call_mcp_tool': _summary_call_mcp,
    'checkpoint': _summary_checkpoint,
    'summarize_context': _summary_summarize_context,
    'symbol_editor': _summary_symbol_editor,
    'terminal_manager': _summarize_terminal_manager_args,
    'shared_task_board': _summary_shared_board,
}


_GENERIC_SUMMARY_KEYS = (
    'path',
    'file',
    'target_file',
    'file_path',
    'command',
    'query',
    'q',
    'pattern',
    'url',
    'message',
    'thought',
    'description',
    'title',
)


def _summary_generic(args: dict[str, Any]) -> str:
    val = _arg_str(args, *_GENERIC_SUMMARY_KEYS)
    return _trunc(val, 120) if val else '…'


def summarize_tool_arguments(tool_name: str, args: dict[str, Any]) -> str:
    """One or two short lines describing *args* for *tool_name* (no JSON)."""
    handler = _TOOL_SUMMARIZERS.get((tool_name or '').strip())
    if handler is not None:
        return handler(args)
    return _summary_generic(args)


# ---------------------------------------------------------------------------
# Activity row + invocation line + streaming hint helpers
# ---------------------------------------------------------------------------


def parse_tool_arguments_json(raw: str) -> dict[str, Any] | None:
    """Parse tool ``arguments`` JSON if it is complete enough."""
    raw = raw.strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def format_tool_activity_rows(
    tool_name: str, args: dict[str, Any] | None
) -> tuple[str, str, str | None]:
    """(verb, primary detail, optional stats) for transcript activity rows."""
    from backend.cli._tool_display.constants import _VAGUE_SUMMARIES
    from backend.cli._tool_display.headline import (
        friendly_verb_for_tool,
        tool_activity_stats_hint,
    )

    args = args or {}
    verb = friendly_verb_for_tool(tool_name, args)
    detail = summarize_tool_arguments(tool_name, args).strip()
    if detail in _VAGUE_SUMMARIES or not detail:
        detail = (tool_name or 'tool').replace('_', ' ')
    stats = tool_activity_stats_hint(tool_name, args)
    return verb, detail, stats


def format_tool_invocation_line(
    tool_name: str,
    args: dict[str, Any] | None,
    *,
    use_icons: bool = True,
) -> tuple[str, str]:
    """Return (icon, single-line label) for transcript / tool row."""
    from backend.cli._tool_display.headline import tool_headline

    icon, headline = tool_headline(tool_name, use_icons=use_icons)
    if not args:
        return icon, f'{headline}…'
    detail = summarize_tool_arguments(tool_name, args)
    if detail in {'…', 'command…', 'file…'}:
        return icon, f'{headline}…'
    return icon, f'{headline}: {detail}'


_STREAMING_HINT_PATTERNS: tuple[tuple[str, str], ...] = (
    (r'"command"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', 'cmd'),
    (r'"path"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', 'path'),
    (r'"file"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', 'file'),
    (r'"target_file"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', 'file'),
    (r'"file_path"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', 'file'),
    (r'"query"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', 'query'),
    (r'"pattern"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', 'pattern'),
    (r'"thought"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', 'thought'),
    (r'"message"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', 'message'),
    (r'"task_description"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', 'task'),
    (r'"tool_name"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', 'mcp'),
    (r'"symbol"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', 'symbol'),
    (r'"operation"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)"', 'op'),
)


def _extract_streaming_hints(partial_json: str) -> list[str]:
    hints: list[str] = []
    for pat, _kind in _STREAMING_HINT_PATTERNS:
        m = re.search(pat, partial_json, re.DOTALL)
        if not m:
            continue
        raw = m.group(1).replace('\\n', '\n').replace('\\"', '"')
        piece = _trunc(raw, 90)
        if piece and piece not in hints:
            hints.append(piece)
    if not hints:
        # Unquoted partial values (streaming mid-token) — very rough.
        m = re.search(r'"command"\s*:\s*"([^"]*)$', partial_json)
        if m and m.group(1).strip():
            hints.append(_trunc(m.group(1), 90))
    return hints


def streaming_args_hint(tool_name: str, partial_json: str) -> str:
    """Human-readable fragment from partially streamed arguments (no JSON braces)."""
    if not partial_json or not partial_json.strip():
        return ''

    tn = (tool_name or '').strip()
    if tn == 'terminal_manager':
        frag = _streaming_hint_terminal_manager(partial_json)
        if frag:
            return frag

    parsed = parse_tool_arguments_json(partial_json)
    if parsed is not None:
        return summarize_tool_arguments(tool_name, parsed)

    hints = _extract_streaming_hints(partial_json)
    return ' · '.join(hints[:3]) if hints else ''
