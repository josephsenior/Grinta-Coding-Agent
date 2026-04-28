"""Verb / headline / activity-stat mappings for tool calls."""

from __future__ import annotations

from typing import Any, Callable

from backend.cli._tool_display.constants import _TOOL_HEADLINE


def tool_headline(tool_name: str, *, use_icons: bool = True) -> tuple[str, str]:
    """Return (icon, category label) for *tool_name*.

    *use_icons* is currently informational only — every entry in
    :data:`_TOOL_HEADLINE` ships an empty icon so terminals without emoji
    rendering remain professional and ASCII-friendly.
    """
    if not tool_name:
        return '', 'Tool'
    info = _TOOL_HEADLINE.get(tool_name.strip())
    if info:
        _icon, headline = info
        return '', headline
    pretty = tool_name.replace('_', ' ').strip() or 'tool'
    return '', pretty.title()


# ---------------------------------------------------------------------------
# Verb mapping
# ---------------------------------------------------------------------------

_TEXT_EDITOR_VERBS = {
    'read_file': 'Viewed',
    'create_file': 'Created',
    'insert_text': 'Inserted',
    'undo_last_edit': 'Reverted',
}

_TERMINAL_MANAGER_VERBS = {
    'open': 'Started',
    'input': 'Sent',
    'read': 'Read',
}

_SIMPLE_VERB_MAP = {
    'symbol_editor': 'Refactored',
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
    'browser': 'Browser',
    'delegate_task': 'Delegated',
    'shared_task_board': 'Checked',
    'communicate_with_user': 'Messaged',
    'call_mcp_tool': 'Invoked',
    'checkpoint': 'Saved',
}


def _verb_text_editor(args: dict[str, Any]) -> str:
    return _TEXT_EDITOR_VERBS.get(str(args.get('command', '') or ''), 'Edited')


def _verb_terminal_manager(args: dict[str, Any]) -> str:
    op = str(args.get('action') or '').strip().lower()
    return _TERMINAL_MANAGER_VERBS.get(op, 'Tool')


def friendly_verb_for_tool(tool_name: str, args: dict[str, Any] | None = None) -> str:
    """Short English verb for the activity row (no emoji)."""
    tn = (tool_name or '').strip()
    a = args or {}
    if tn == 'text_editor':
        return _verb_text_editor(a)
    if tn in {'execute_bash', 'execute_powershell'}:
        return 'Ran'
    if tn == 'terminal_manager':
        verb = _verb_terminal_manager(a)
        if verb != 'Tool':
            return verb
    if tn in _SIMPLE_VERB_MAP:
        return _SIMPLE_VERB_MAP[tn]
    return tn.replace('_', ' ').title() if tn else 'Tool'


# ---------------------------------------------------------------------------
# Activity stats hint (one short dim line per tool)
# ---------------------------------------------------------------------------


def _stats_search_code(args: dict[str, Any]) -> str | None:
    root = args.get('path') or args.get('root') or args.get('directory')
    if isinstance(root, str) and root.strip():
        return f'scope: {root}'
    return None


def _stats_analyze_project(args: dict[str, Any]) -> str | None:
    depth = args.get('depth')
    if isinstance(depth, int) and depth > 0:
        return f'tree depth {depth}'
    p = args.get('path') or args.get('root')
    if isinstance(p, str) and p.strip():
        return f'path: {p}'
    return None


def _stats_explore_tree(args: dict[str, Any]) -> str | None:
    depth = args.get('max_depth') or args.get('depth')
    if isinstance(depth, int) and depth > 0:
        return f'max depth {depth}'
    return None


def _stats_text_editor(args: dict[str, Any]) -> str | None:
    cmd = str(args.get('command', '') or '')
    path_hint = str(args.get('path', '') or '')
    if cmd == 'read_file' and path_hint:
        start = args.get('view_range_start')
        end = args.get('view_range_end')
        if start is not None and end is not None:
            return f'lines {start}–{end}'
    if cmd == 'replace_text' and path_hint:
        return path_hint
    return None


def _stats_task_tracker(args: dict[str, Any]) -> str | None:
    tasks = args.get('task_list')
    if isinstance(tasks, list) and tasks:
        return f'{len(tasks)} tasks'
    return None


def _stats_read_symbol(args: dict[str, Any]) -> str | None:
    sym = args.get('symbol') or args.get('name')
    if isinstance(sym, str) and sym.strip():
        return f'symbol: {sym}'
    return None


def _stats_terminal_manager(args: dict[str, Any]) -> str | None:
    sid = args.get('session_id')
    if (
        isinstance(sid, str)
        and sid.strip()
        and str(args.get('action', '')).lower() != 'open'
    ):
        from backend.cli._tool_display.summarize import _trunc

        return f'session: {_trunc(sid, 36)}'
    return None


def _stats_lsp(args: dict[str, Any]) -> str | None:
    q = args.get('command') or args.get('query_type')
    if isinstance(q, str) and q.strip():
        return q
    return None


_STATS_HANDLERS: dict[str, Callable[[dict[str, Any]], str | None]] = {
    'search_code': _stats_search_code,
    'analyze_project_structure': _stats_analyze_project,
    'explore_tree_structure': _stats_explore_tree,
    'text_editor': _stats_text_editor,
    'task_tracker': _stats_task_tracker,
    'read_symbol_definition': _stats_read_symbol,
    'terminal_manager': _stats_terminal_manager,
    'code_intelligence': _stats_lsp,
    'lsp_query': _stats_lsp,
}


def tool_activity_stats_hint(tool_name: str, args: dict[str, Any]) -> str | None:
    """Optional dim second line (scope, depth, counts)."""
    handler = _STATS_HANDLERS.get((tool_name or '').strip())
    if handler is None:
        return None
    return handler(args)
