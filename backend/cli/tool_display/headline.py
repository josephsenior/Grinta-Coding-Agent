"""Verb / headline / activity-stat mappings for tool calls."""

from __future__ import annotations

from typing import Any, Callable

from backend.cli.tool_display.constants import _TOOL_HEADLINE


def tool_headline(tool_name: str, *, use_icons: bool = True) -> tuple[str, str]:
    """Return (icon, category label) for *tool_name*.

    *use_icons* controls whether the spec icon is emitted.  Orient tools
    get distinct icons (₡, ◆, ƒ, ↳, ≡, ⌐) while non-orient tools get
    no icon (empty string).
    """
    if not tool_name:
        return '', 'Tool'
    info = _TOOL_HEADLINE.get(tool_name.strip())
    if info:
        icon, headline = info
        if use_icons:
            return icon, headline
        return '', headline
    pretty = tool_name.replace('_', ' ').strip() or 'tool'
    return '', pretty.title()


# ---------------------------------------------------------------------------
# Verb mapping
# ---------------------------------------------------------------------------

_TERMINAL_MANAGER_VERBS = {
    'open': 'Started',
    'input': 'Sent',
    'read': 'Read',
    'logs': 'Read',
    'wait': 'Waited',
    'list': 'Listed',
    'close': 'Stopped',
    'stop': 'Stopped',
}

_DEBUGGER_VERBS = {
    'start': 'Started',
    'set_breakpoints': 'Set',
    'continue': 'Continued',
    'next': 'Stepped',
    'step_in': 'Stepped',
    'step_out': 'Stepped',
    'pause': 'Paused',
    'stack': 'Inspected',
    'scopes': 'Inspected',
    'variables': 'Inspected',
    'evaluate': 'Evaluated',
    'status': 'Checked',
    'stop': 'Stopped',
}

_SIMPLE_VERB_MAP = {
    'read_file': 'Read',
    'create_file': 'Created',
    'replace_string': 'Edited',
    'multiedit': 'Edited',
    'find_symbols': 'Found',
    'agent_think': 'Thinking',
    'think': 'Thinking',
    'memory_manager': 'Managed',
    'task_tracker': 'Tracked',
    'grep': 'Grepped',
    'glob': 'Globbed',
    'lsp': 'Analyzed',
    'analyze_project_structure': 'Analyzed',
    'browser': 'Browser',
    'delegate_task': 'Delegated',
    'shared_task_board': 'Checked',
    'ask_user': 'Asked',
    'call_mcp_tool': 'Invoked',
    'checkpoint': 'Saved',
}


def _verb_terminal_manager(args: dict[str, Any]) -> str:
    op = str(args.get('action') or '').strip().lower()
    return _TERMINAL_MANAGER_VERBS.get(op, 'Tool')


def _verb_debugger(args: dict[str, Any]) -> str:
    op = str(args.get('action') or args.get('debug_action') or '').strip().lower()
    return _DEBUGGER_VERBS.get(op, 'Debugging')


def friendly_verb_for_tool(tool_name: str, args: dict[str, Any] | None = None) -> str:
    """Short English verb for the activity row (no emoji)."""
    tn = (tool_name or '').strip()
    a = args or {}
    if tn in {'execute_bash', 'execute_powershell'}:
        return 'Ran'
    if tn == 'terminal_manager':
        verb = _verb_terminal_manager(a)
        if verb != 'Tool':
            return verb
    if tn == 'debugger':
        return _verb_debugger(a)
    if tn in _SIMPLE_VERB_MAP:
        return _SIMPLE_VERB_MAP[tn]
    return tn.replace('_', ' ').title() if tn else 'Tool'


# ---------------------------------------------------------------------------
# Activity stats hint (one short dim line per tool)
# ---------------------------------------------------------------------------


def _stats_search(args: dict[str, Any]) -> str | None:
    root = args.get('path') or args.get('root') or args.get('directory')
    if isinstance(root, str) and root.strip():
        return f'scope: {root}'
    return None


def _stats_grep(args: dict[str, Any]) -> str | None:
    root = args.get('path') or args.get('root') or args.get('directory')
    if isinstance(root, str) and root.strip():
        return f'scope: {root}'
    return None


def _stats_glob(_args: dict[str, Any]) -> str | None:
    return None


def _stats_analyze_project(args: dict[str, Any]) -> str | None:
    depth = args.get('depth')
    if isinstance(depth, int) and depth > 0:
        return f'tree depth {depth}'
    p = args.get('path') or args.get('root')
    if isinstance(p, str) and p.strip():
        return f'path: {p}'
    return None


def _stats_task_tracker(args: dict[str, Any]) -> str | None:
    tasks = args.get('task_list')
    if isinstance(tasks, list) and tasks:
        return f'{len(tasks)} tasks'
    return None


def _stats_terminal_manager(args: dict[str, Any]) -> str | None:
    sid = args.get('session_id')
    if (
        isinstance(sid, str)
        and sid.strip()
        and str(args.get('action', '')).lower() != 'open'
    ):
        from backend.cli.tool_display.summarize import _trunc

        return f'session: {_trunc(sid, 36)}'
    return None


def _stats_lsp(args: dict[str, Any]) -> str | None:
    q = args.get('command') or args.get('query_type')
    if isinstance(q, str) and q.strip():
        return q
    return None


def _stats_debugger(args: dict[str, Any]) -> str | None:
    sid = args.get('session_id')
    if isinstance(sid, str) and sid.strip():
        from backend.cli.tool_display.summarize import _trunc

        return f'session: {_trunc(sid, 36)}'
    adapter = args.get('adapter') or args.get('language') or args.get('adapter_type')
    if isinstance(adapter, str) and adapter.strip():
        return f'adapter: {adapter}'
    return None


_STATS_HANDLERS: dict[str, Callable[[dict[str, Any]], str | None]] = {
    'grep': _stats_grep,
    'glob': _stats_glob,
    'analyze_project_structure': _stats_analyze_project,
    'task_tracker': _stats_task_tracker,
    'terminal_manager': _stats_terminal_manager,
    'debugger': _stats_debugger,
    'lsp': _stats_lsp,
    'lsp_query': _stats_lsp,
}


def tool_activity_stats_hint(tool_name: str, args: dict[str, Any]) -> str | None:
    """Optional dim second line (scope, depth, counts)."""
    handler = _STATS_HANDLERS.get((tool_name or '').strip())
    if handler is None:
        return None
    return handler(args)
