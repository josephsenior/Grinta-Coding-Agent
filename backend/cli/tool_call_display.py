"""User-facing summaries for LLM tool calls (CLI) — avoid raw JSON in the transcript."""

from __future__ import annotations

import json
import re
from typing import Any

# (icon, short verb phrase for the activity line)
_TOOL_HEADLINE: dict[str, tuple[str, str]] = {
    'execute_bash': ('', 'Shell'),
    'execute_powershell': ('', 'Shell'),
    'str_replace_editor': ('', 'Files'),
    'apply_patch': ('', 'Apply patch'),
    'edit_file': ('', 'Edit file'),
    'ast_code_editor': ('', 'AST edit'),
    'agent_think': ('', 'Think'),
    'think': ('', 'Think'),
    'finish': ('', 'Finish'),
    'summarize_context': ('', 'Summarize context'),
    'memory_manager': ('', 'Memory'),
    'task_tracker': ('', 'Tasks'),
    'search_code': ('', 'Search code'),
    'code_intelligence': ('', 'Code intelligence'),
    'explore_tree_structure': ('', 'Explore tree'),
    'read_symbol_definition': ('', 'Symbol'),
    'analyze_project_structure': ('', 'Analyze project'),
    'verify_file_lines': ('', 'Verify lines'),
    'verify_ui_change': ('', 'Verify UI'),
    'delegate_task': ('', 'Delegate'),
    'signal_progress': ('', 'Progress'),
    'shared_task_board': ('', 'Board'),
    'terminal_manager': ('', 'Terminal'),
    'communicate_with_user': ('', 'Message you'),
    'call_mcp_tool': ('�', 'MCP'),
    'checkpoint': ('', 'Checkpoint'),
    'revert_to_checkpoint': ('', 'Revert'),
    'session_diff': ('', 'Session diff'),
}


def tool_headline(
    tool_name: str, *, use_icons: bool = True
) -> tuple[str, str]:
    """Return (icon, category label) for *tool_name*.

    When *use_icons* is False, the icon string is empty and the label is plain text
    (professional / ASCII-friendly terminals).
    """
    if not tool_name:
        return '', 'Tool'
    info = _TOOL_HEADLINE.get(tool_name.strip())
    if info:
        _em, headline = info
        return '', headline
    pretty = tool_name.replace('_', ' ').strip() or 'tool'
    return '', pretty.title()


def friendly_verb_for_tool(
    tool_name: str, args: dict[str, Any] | None = None
) -> str:
    """Short English verb for the activity row (no emoji)."""
    tn = (tool_name or '').strip()
    a = args or {}
    if tn == 'str_replace_editor':
        cmd = str(a.get('command', '') or '')
        if cmd == 'view_file':
            return 'Viewed'
        if cmd == 'create_file':
            return 'Created'
        if cmd == 'insert_text':
            return 'Inserted'
        if cmd == 'undo_last_edit':
            return 'Reverted'
        return 'Edited'
    if tn in {'execute_bash', 'execute_powershell'}:
        return 'Ran'
    mapping = {
        'apply_patch': 'Patched',
        'edit_file': 'Edited',
        'ast_code_editor': 'Refactored',
        'agent_think': 'Thinking',
        'think': 'Thinking',
        'finish': 'Finished',
        'summarize_context': 'Compressed',
        'memory_manager': 'Managed',
        'task_tracker': 'Tracked',
        'search_code': 'Searched',
        'code_intelligence': 'Analyzed',
        'explore_tree_structure': 'Explored',
        'read_symbol_definition': 'Analyzed',
        'analyze_project_structure': 'Explored',
        'verify_file_lines': 'Verified',
        'verify_ui_change': 'Checked UI',
        'delegate_task': 'Delegated',
        'signal_progress': 'Noted',
        'shared_task_board': 'Checked',
        'terminal_manager': 'Opened',
        'communicate_with_user': 'Messaged',
        'call_mcp_tool': 'Invoked',
        'checkpoint': 'Saved',
        'revert_to_checkpoint': 'Reverted',
        'session_diff': 'Compared',
    }
    if tn in mapping:
        return mapping[tn]
    return tn.replace('_', ' ').title() if tn else 'Tool'


def tool_activity_stats_hint(tool_name: str, args: dict[str, Any]) -> str | None:
    """Optional dim second line (scope, depth, counts)."""
    tn = (tool_name or '').strip()
    if tn == 'search_code':
        sc_root = args.get('path') or args.get('root') or args.get('directory')
        if isinstance(sc_root, str) and sc_root.strip():
            return f'scope: {sc_root}'
    if tn == 'analyze_project_structure':
        d = args.get('depth')
        if isinstance(d, int) and d > 0:
            return f'tree depth {d}'
        p = args.get('path') or args.get('root')
        if isinstance(p, str) and p.strip():
            return f'path: {p}'
    if tn == 'explore_tree_structure':
        d = args.get('max_depth') or args.get('depth')
        if isinstance(d, int) and d > 0:
            return f'max depth {d}'
    if tn == 'str_replace_editor':
        c = str(args.get('command', '') or '')
        sr_path_hint = str(args.get('path', '') or '')
        if c == 'view_file' and sr_path_hint:
            start = args.get('view_range_start')
            end = args.get('view_range_end')
            if start is not None and end is not None:
                return f'lines {start}–{end}'
        if c == 'replace_text' and sr_path_hint:
            return sr_path_hint
    if tn == 'task_tracker':
        tl = args.get('task_list')
        if isinstance(tl, list) and tl:
            return f'{len(tl)} tasks'
    if tn == 'read_symbol_definition':
        sym = args.get('symbol') or args.get('name')
        if isinstance(sym, str) and sym.strip():
            return f'symbol: {sym}'
    if tn in {'code_intelligence', 'lsp_query'}:
        lsp_q = args.get('command') or args.get('query_type')
        if isinstance(lsp_q, str) and lsp_q.strip():
            return lsp_q
    return None


_VAGUE_SUMMARIES = frozenset(
    {
        '…',
        'command…',
        'file…',
        'search…',
        'LSP…',
        'directory tree',
        'scan workspace',
        'memory…',
        'tasks…',
        'AST edit…',
        'edit…',
        'terminal…',
        'board…',
        'MCP tool…',
        'revert…',
    }
)


def format_tool_activity_rows(
    tool_name: str, args: dict[str, Any] | None
) -> tuple[str, str, str | None]:
    """(verb, primary detail, optional stats) for transcript activity rows."""
    args = args or {}
    verb = friendly_verb_for_tool(tool_name, args)
    detail = summarize_tool_arguments(tool_name, args).strip()
    if detail in _VAGUE_SUMMARIES or not detail:
        detail = (tool_name or 'tool').replace('_', ' ')
    stats = tool_activity_stats_hint(tool_name, args)
    return verb, detail, stats


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


def _trunc(s: str, max_len: int = 100) -> str:
    s = ' '.join(s.split())
    if len(s) <= max_len:
        return s
    return s[: max_len - 1] + '…'


def summarize_tool_arguments(tool_name: str, args: dict[str, Any]) -> str:
    """One or two short lines describing *args* for *tool_name* (no JSON)."""
    tn = (tool_name or '').strip()

    if tn in {'execute_bash', 'execute_powershell'}:
        shell_cmd = args.get('command')
        if isinstance(shell_cmd, str) and shell_cmd.strip():
            return f'$ {_trunc(shell_cmd, 120)}'
        return 'command…'

    if tn == 'str_replace_editor':
        sr_cmd = str(args.get('command', '') or '')
        sr_path = str(args.get('path', '') or '')
        if sr_cmd == 'create_file' and sr_path:
            return f'{sr_path} · new file'
        parts: list[str] = []
        if sr_path:
            parts.append(sr_path)
        if sr_cmd:
            parts.append(sr_cmd)
        return ' · '.join(parts) if parts else 'file…'

    if tn == 'apply_patch':
        patch = args.get('patch') or args.get('diff') or ''
        if isinstance(patch, str) and patch.strip():
            return 'apply patch'
        return 'apply patch'

    if tn in {'think', 'agent_think'}:
        t = args.get('thought') or args.get('content')
        if isinstance(t, str) and t.strip():
            return _trunc(t, 160)
        return '…'

    if tn == 'finish':
        m = args.get('message')
        if isinstance(m, str) and m.strip():
            return _trunc(m, 120)
        return 'done'

    if tn == 'memory_manager':
        mm_op = args.get('operation') or args.get('action')
        mm_q = args.get('query') or args.get('key')
        bits = [str(x) for x in (mm_op, mm_q) if x]
        return _trunc(' · '.join(bits), 120) if bits else 'memory…'

    if tn == 'task_tracker':
        tt_op = args.get('operation') or args.get('command')
        tt_title = args.get('title') or args.get('task')
        task_list = args.get('task_list')
        task_count = len(task_list) if isinstance(task_list, list) else 0
        parts = [str(x) for x in (tt_op, tt_title) if x]
        if task_count:
            parts.append(f'{task_count} task{"s" if task_count != 1 else ""}')
        return _trunc(' · '.join(parts), 160) if parts else 'tasks…'

    if tn == 'search_code':
        sc_q = args.get('query') or args.get('pattern')
        sc_path = args.get('path') or args.get('root') or args.get('directory')
        bits_sc: list[str] = []
        if isinstance(sc_q, str) and sc_q.strip():
            bits_sc.append(_trunc(sc_q, 80))
        if isinstance(sc_path, str) and sc_path.strip():
            bits_sc.append(sc_path)
        return ' in '.join(bits_sc) if bits_sc else 'search…'

    if tn == 'code_intelligence':
        lsp_cmd = args.get('command') or args.get('query_type')
        lsp_path = args.get('file') or args.get('path')
        lsp_sym = args.get('symbol') or args.get('name')
        bits = [str(x) for x in (lsp_cmd, lsp_sym or lsp_path) if x]
        return _trunc(' · '.join(bits), 120) if bits else 'LSP…'

    if tn == 'explore_tree_structure':
        p = args.get('path') or args.get('root')
        if isinstance(p, str) and p.strip():
            return p
        return 'directory tree'

    if tn == 'read_symbol_definition':
        rs_sym = args.get('symbol') or args.get('name')
        rs_path = args.get('file') or args.get('path')
        bits_rs = [str(x) for x in (rs_sym, rs_path) if x]
        return _trunc(' · '.join(bits_rs), 120) if bits_rs else 'symbol…'

    if tn == 'analyze_project_structure':
        return 'scan workspace'

    if tn == 'verify_file_lines':
        vf_path = args.get('path') or args.get('file')
        if isinstance(vf_path, str):
            return vf_path or 'file'
        return 'verify'

    if tn == 'delegate_task':
        d = args.get('task_description') or args.get('description')
        if isinstance(d, str) and d.strip():
            return _trunc(d, 120)
        return 'sub-task…'

    if tn == 'signal_progress':
        prog_text = args.get('progress_note') or args.get('note') or args.get('message')
        if isinstance(prog_text, str) and prog_text.strip():
            return _trunc(prog_text, 120)
        return '…'

    if tn == 'communicate_with_user':
        for key in ('message', 'content', 'text'):
            v = args.get(key)
            if isinstance(v, str) and v.strip():
                return _trunc(v, 120)
        return '…'

    if tn == 'call_mcp_tool':
        inner = args.get('tool_name') or args.get('name')
        if isinstance(inner, str) and inner.strip():
            return f'→ {_trunc(inner, 80)}'
        return 'MCP tool…'

    if tn == 'checkpoint':
        lbl = args.get('label') or args.get('message')
        if isinstance(lbl, str) and lbl.strip():
            return _trunc(lbl, 80)
        return 'save state'

    if tn == 'revert_to_checkpoint':
        cid = args.get('checkpoint_id') or args.get('id')
        return str(cid) if cid is not None else 'revert…'

    if tn == 'session_diff':
        return 'changes since checkpoint'

    if tn == 'summarize_context':
        return 'compress conversation'

    if tn == 'edit_file':
        ef_path = args.get('path')
        if isinstance(ef_path, str) and ef_path.strip():
            return ef_path
        return 'edit…'

    if tn == 'ast_code_editor':
        ast_path = args.get('path')
        ast_cmd = args.get('command')
        bits_ast = [str(x) for x in (ast_cmd, ast_path) if x]
        return _trunc(' · '.join(bits_ast), 120) if bits_ast else 'AST edit…'

    if tn == 'terminal_manager':
        tm_cmd = args.get('command') or args.get('action')
        if tm_cmd:
            return str(tm_cmd)
        return 'terminal…'

    if tn == 'shared_task_board':
        op = args.get('operation') or args.get('command')
        return str(op) if op else 'board…'

    # Generic: pick a few readable string fields
    preferred_keys = (
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
    for key in preferred_keys:
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return _trunc(val, 120)
    return '…'


def format_tool_invocation_line(
    tool_name: str,
    args: dict[str, Any] | None,
    *,
    use_icons: bool = True,
) -> tuple[str, str]:
    """Return (icon, single-line label) for transcript / tool row."""
    icon, headline = tool_headline(tool_name, use_icons=use_icons)
    if not args:
        return icon, f'{headline}…'
    detail = summarize_tool_arguments(tool_name, args)
    if detail in {'…', 'command…', 'file…'}:
        return icon, f'{headline}…'
    return icon, f'{headline}: {detail}'


def streaming_args_hint(tool_name: str, partial_json: str) -> str:
    """Human-readable fragment from partially streamed arguments (no JSON braces)."""
    if not partial_json or not partial_json.strip():
        return ''

    # Fast path: full parse
    parsed = parse_tool_arguments_json(partial_json)
    if parsed is not None:
        return summarize_tool_arguments(tool_name, parsed)

    hints: list[str] = []
    # Order matters: prefer most user-meaningful keys first
    patterns: list[tuple[str, str]] = [
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
    ]
    for pat, _kind in patterns:
        m = re.search(pat, partial_json, re.DOTALL)
        if not m:
            continue
        raw = m.group(1).replace('\\n', '\n').replace('\\"', '"')
        piece = _trunc(raw, 90)
        if piece and piece not in hints:
            hints.append(piece)

    if not hints:
        # Unquoted partial values (streaming mid-token) — very rough
        m = re.search(r'"command"\s*:\s*"([^"]*)$', partial_json)
        if m and m.group(1).strip():
            hints.append(_trunc(m.group(1), 90))

    return ' · '.join(hints[:3]) if hints else ''


_TOOL_CALL_PREFIX = '[Tool call]'
_TOOL_RESULT_PREFIX = '[Tool result from '
_PROTOCOL_ECHO_PREFIXES = (
    _TOOL_RESULT_PREFIX,
    '[CMD_OUTPUT',
    '[Below is the output of the previous command.]',
    '[Observed result of command executed by user:',
    '[The command completed with exit code',
)


def strip_tool_call_marker_lines(text: str) -> str:
    """Drop whole lines that are only a friendly ``[Tool call] …`` summary.

    Cross-family history uses ``flatten_tool_call_for_history`` (``[Tool call] ✏️ …``)
    without the ``name({`` JSON shape; ``redact_streamed_tool_call_markers`` would
    otherwise leave those lines in assistant markdown.

    Lines matching ``[Tool call] identifier({...})`` are left intact so the JSON
    redaction pass below can remove them.
    """
    if _TOOL_CALL_PREFIX not in text:
        return text
    lines = text.splitlines(keepends=True)
    kept: list[str] = []
    for line in lines:
        rest = line.lstrip()
        if not rest.startswith(_TOOL_CALL_PREFIX):
            kept.append(line)
            continue
        after = rest[len(_TOOL_CALL_PREFIX) :].lstrip()
        if re.match(r'^[A-Za-z0-9_]+\s*\(', after):
            kept.append(line)
            continue
    return ''.join(kept)


def strip_protocol_echo_blocks(text: str) -> str:
    """Drop echoed tool-result / command-observation protocol blocks.

    Cross-family proxy history can occasionally be copied back into assistant text
    as paragraphs that start with ``[Tool result from ...]`` or ``[CMD_OUTPUT ...]``.
    Those blocks are internal protocol noise, so hide them from the visible transcript.
    """
    if not text or '[' not in text:
        return text

    parts = re.split(r'(\n\s*\n)', text)
    kept_parts: list[str] = []
    for part in parts:
        stripped = part.strip()
        if not stripped:
            kept_parts.append(part)
            continue
        if any(stripped.startswith(prefix) for prefix in _PROTOCOL_ECHO_PREFIXES):
            continue
        kept_parts.append(part)

    text = ''.join(kept_parts)
    lines = text.splitlines(keepends=True)
    kept_lines: list[str] = []
    for line in lines:
        stripped = line.lstrip()
        if any(stripped.startswith(prefix) for prefix in _PROTOCOL_ECHO_PREFIXES):
            continue
        kept_lines.append(line)
    return ''.join(kept_lines)


def _balanced_json_object_end(s: str, open_curly: int) -> int | None:
    """Return index after the ``}`` that closes the object starting at *open_curly*."""
    depth = 0
    in_str = False
    esc = False
    for pos in range(open_curly, len(s)):
        ch = s[pos]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return pos + 1
    return None


def redact_streamed_tool_call_markers(text: str) -> str:
    """Remove ``[Tool call] name({...})`` spans from assistant-visible text.

    OpenAI-compatible Gemini proxies and our cross-family history flattening can
    put this pattern in ``message.content``; the executor then streams it into
    the CLI.  Tool rows are already shown via structured actions — drop the raw
    JSON duplicate here.
    """
    text = strip_protocol_echo_blocks(strip_tool_call_marker_lines(text))
    if _TOOL_CALL_PREFIX not in text:
        return text
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        j = text.find(_TOOL_CALL_PREFIX, i)
        if j < 0:
            out.append(text[i:])
            break
        out.append(text[i:j])
        rest_start = j + len(_TOOL_CALL_PREFIX)
        rest = text[rest_start:]
        lstripped = rest.lstrip()
        ws = len(rest) - len(lstripped)
        m = re.match(r'^([A-Za-z0-9_]+)\(', lstripped)
        if not m:
            out.append(text[j:rest_start])
            i = rest_start
            continue
        open_paren_in_rest = lstripped.find('(')
        args_begin = rest_start + ws + open_paren_in_rest + 1
        tail = text[args_begin:].lstrip()
        json_shift = len(text[args_begin:]) - len(tail)
        json_start = args_begin + json_shift
        if json_start >= n or text[json_start] != '{':
            out.append(text[j])
            i = j + 1
            continue
        end_json = _balanced_json_object_end(text, json_start)
        if end_json is None:
            return ''.join(out).rstrip()
        k = end_json
        while k < n and text[k] in ' \t\r':
            k += 1
        if k >= n or text[k] != ')':
            return ''.join(out).rstrip()
        i = k + 1
        if i < n and text[i] == '\n':
            i += 1
    return ''.join(out)


# Matches JSON objects that look like task-list items the model echoes back in text.
# Pattern: {"description": ..., "id": ..., "status": ...} (any key order, no nesting)
_TASK_JSON_OBJ_RE = re.compile(
    r'\{[^{}]*"description"\s*:[^{}]*"(?:status|id)"\s*:[^{}]*\}',
    re.DOTALL,
)

# Internal protocol markers that the LLM sometimes echoes into its text response.
# These are agent-internal metadata — they should never be shown to the user.
_INTERNAL_RESULT_MARKER_RE = re.compile(
    r'\[(?:CHECKPOINT_RESULT|REVERT_RESULT|ROLLBACK|TASK_TRACKER)\]'
    r'(?:\s*\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}|\s+[^\n]*)',
)


def redact_internal_result_markers(text: str) -> str:
    """Strip internal ``[TAG] {json}`` or ``[TAG] text`` markers from user-visible text.

    Models sometimes echo ``[CHECKPOINT_RESULT] {…}``, ``[REVERT_RESULT] {…}``,
    ``[ROLLBACK] Success: …``, or ``[TASK_TRACKER] …`` from their conversation
    history back into streaming or final assistant text.  These are internal protocol
    markers — the CLI already displays friendly activity rows for these tools.
    """
    if '[' in text:
        text = _INTERNAL_RESULT_MARKER_RE.sub('', text)
    
    # Also strip out validation markers added by tool result validator to avoid UI clutter
    text = re.sub(r'\n?<APP_RESULT_VALIDATION>.*?(?:</APP_RESULT_VALIDATION>|$)', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'\[TOOL_FALLBACK\].*?(?:\n|$)', '', text)

    # Collapse blank lines left behind.
    cleaned = re.sub(r'\n{3,}', '\n\n', text)
    return cleaned.strip()


def redact_task_list_json_blobs(text: str) -> str:
    """Strip task-object JSON blobs from streaming text.

    Gemini Flash sometimes echoes ``{"description": ..., "status": ...}`` objects
    from the active plan back into its text response.  These are already shown via
    the structured :class:`TaskTrackingAction` display — remove the raw duplicates.
    """
    cleaned = _TASK_JSON_OBJ_RE.sub('', text)
    # Collapse runs of whitespace / bare punctuation left behind (e.g. ", , ]")
    cleaned = re.sub(r'[\s,]+\]', ']', cleaned)
    cleaned = re.sub(r'\[\s*\]', '', cleaned)
    return cleaned.strip()


def flatten_tool_call_for_history(name: str, arguments: str) -> str:
    """Single line for cross-family assistant history (no raw JSON)."""
    parsed = parse_tool_arguments_json(arguments)
    if parsed is not None:
        icon, label = format_tool_invocation_line(name, parsed)
        return f'{_TOOL_CALL_PREFIX} {icon} {label}'
    return f'{_TOOL_CALL_PREFIX} {name}'


def looks_like_streaming_tool_arguments(text: str) -> bool:
    """True when *text* looks like JSON tool arguments but chunk is not flagged."""
    s = text.lstrip()
    if not s.startswith('{'):
        return False
    # Avoid matching casual prose that starts with {
    markers = (
        '"command"',
        '"path"',
        '"tool_name"',
        '"arguments"',
        '"str_replace_editor"',
        '"function"',
    )
    return any(m in text for m in markers)


def mcp_result_user_preview(content: str, *, max_len: int = 400) -> str:
    """Turn MCP JSON/text tool output into a short user-facing string."""
    s = (content or '').strip()
    if not s:
        return ''
    if not s.startswith('{') and not s.startswith('['):
        return _trunc(s, max_len)

    try:
        data = json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return _trunc(s, max_len)

    if isinstance(data, dict):
        # Search / navigation result fields (search_code, lsp, etc.)
        for count_key in ('total_count', 'count', 'matches', 'total'):
            v = data.get(count_key)
            if isinstance(v, int):
                label = data.get('query') or data.get('pattern') or ''
                return (f'{v} matches' + (f' for "{_trunc(label, 40)}"' if label else ''))
        for key in ('text', 'message', 'content', 'summary', 'result', 'output'):
            v = data.get(key)
            if isinstance(v, str) and v.strip():
                return _trunc(v, max_len)
            if isinstance(v, (list, dict)) and v:
                try:
                    nested = json.dumps(v, ensure_ascii=False)
                except (TypeError, ValueError):
                    nested = str(v)
                return _trunc(nested, max_len)
        err = data.get('error') or data.get('detail')
        if isinstance(err, str) and err.strip():
            return _trunc(err, max_len)
        if isinstance(err, dict):
            msg = err.get('message') or err.get('msg')
            if isinstance(msg, str):
                return _trunc(msg, max_len)
    elif isinstance(data, list) and data:
        # List of file matches (e.g. from search_code)
        n = len(data)
        first = data[0]
        if isinstance(first, dict):
            path = first.get('path') or first.get('file') or first.get('filename') or ''
            return f'{n} result{"s" if n != 1 else ""}' + (f' (first: {path})' if path else '')
        try:
            return _trunc(json.dumps(data, ensure_ascii=False), max_len)
        except (TypeError, ValueError):
            return _trunc(str(data), max_len)

    try:
        return _trunc(json.dumps(data, ensure_ascii=False), max_len)
    except (TypeError, ValueError):
        return _trunc(s, max_len)


def try_format_message_as_tool_json(
    content: str, *, use_icons: bool = True
) -> tuple[str, str] | None:
    """If *content* is assistant tool JSON, return (icon, friendly multiline text)."""
    s = content.strip()
    if not s.startswith('{') and not s.startswith('['):
        return None
    try:
        data = json.loads(s)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None

    lines: list[str] = []
    first_tool_name = ''

    def one_call(name: str, arguments: Any) -> None:
        nonlocal first_tool_name
        if not first_tool_name:
            first_tool_name = name
        args_dict: dict[str, Any] = {}
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments)
                if isinstance(parsed, dict):
                    args_dict = parsed
            except (json.JSONDecodeError, TypeError, ValueError):
                args_dict = {'raw': arguments[:200]}
        elif isinstance(arguments, dict):
            args_dict = arguments
        icon, label = format_tool_invocation_line(
            name, args_dict or None, use_icons=use_icons
        )
        if icon:
            lines.append(f'{icon} {label}')
        else:
            lines.append(label)

    if isinstance(data, dict):
        if 'tool_calls' in data and isinstance(data['tool_calls'], list):
            for tc in data['tool_calls']:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get('function')
                if isinstance(fn, dict):
                    one_call(
                        str(fn.get('name', 'tool')),
                        fn.get('arguments', {}),
                    )
        elif 'name' in data and 'arguments' in data:
            one_call(str(data.get('name', 'tool')), data.get('arguments'))
        elif 'function' in data and isinstance(data['function'], dict):
            fn = data['function']
            one_call(str(fn.get('name', 'tool')), fn.get('arguments', {}))
        else:
            return None
    elif isinstance(data, list):
        for item in data:
            if not isinstance(item, dict):
                continue
            fn = item.get('function')
            if isinstance(fn, dict):
                one_call(
                    str(fn.get('name', 'tool')),
                    fn.get('arguments', {}),
                )
    else:
        return None

    if not lines:
        return None
    icon0, _ = tool_headline(first_tool_name, use_icons=use_icons)
    return icon0, '\n'.join(lines)
