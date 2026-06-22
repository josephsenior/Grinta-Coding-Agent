"""Environment/platform hint strings shared across routing, tools, and autonomy.

These builders return small text fragments that are interpolated into the
larger prompt sections. Grouping them here keeps shell- and language-server-
specific wording in one place.
"""

from __future__ import annotations

from typing import Any


def _lsp_available(config: Any = None) -> bool:
    """Return whether the lsp tool should be considered available."""
    if not getattr(config, 'enable_lsp_query', True):
        return False
    try:
        from backend.utils.runtime_detect import has_any_lsp_server

        return bool(has_any_lsp_server())
    except Exception:
        return False


def _debugger_available(config: Any = None) -> bool:
    """Return whether the debugger tool should be considered available."""
    if not getattr(config, 'enable_debugger', False):
        return False
    try:
        from backend.utils.runtime_detect import has_any_debug_adapter

        return bool(has_any_debug_adapter())
    except Exception:
        return False


def _discovery_decision_table(
    *,
    lsp_available: bool,
    web_on: bool = True,
    docs_on: bool = True,
    browser_on: bool = False,
) -> str:
    """Canonical routing table for overlapping search/discovery tools."""
    lines = [
        '<DISCOVERY_ROUTING>',
        'Pick the first matching row:',
        '- Text/regex in file contents → `grep` (default output_mode=files_with_matches; use content when you need lines)',
        '- File paths by name/pattern → `glob`',
        '- Symbol name, file unknown → `find_symbols`',
        '- Symbol bodies after candidates → `read(type="symbols", symbols=[...])`',
        '- File body or line range (one file) → `read(type="file", path=...)`; add `start_line`+`end_line` together (`end_line=-1` for EOF) or omit both for whole file',
        '- File signatures only (one file) → `analyze_project_structure` command=file_outline',
        '- File symbol list (one file) → `analyze_project_structure` command=symbols',
        '- Project tree / recent changes → `analyze_project_structure` command=tree or recent',
        '- Imports/deps before multi-file refactor → `analyze_project_structure` command=imports or dependencies',
        '- Workspace-wide references (fast regex) → `analyze_project_structure` command=callers',
        '- Workspace-wide references (AST fallback) → `analyze_project_structure` command=semantic_search',
        '- Test files for a module → `glob` (`**/*test*`, `**/*_test.*`) then `grep` for imports/references',
    ]
    if web_on:
        web_lines = [
            '- External/current info (errors, release notes, unknown APIs) → `web_search`',
            '- Known URL, static/markdown page → `web_fetch` (default for URLs)',
        ]
        if browser_on:
            web_lines.append(
                '- Login, forms, JS SPA, or interaction required → `browser` (not `web_fetch`)'
            )
        lines.extend(web_lines)
    elif browser_on:
        lines.append('- Interactive/JS-heavy pages → `browser`')
    if docs_on:
        docs_lines = [
            '- Library/framework/SDK docs (API syntax, setup, migrations) → `docs_resolve` then `docs_query`',
            '- Known corpus ID `/org/project` or `/org/project/version` → `docs_query` only',
        ]
        if web_on:
            docs_lines.append(
                '- Prefer `docs_*` over `web_search` when the library is known'
            )
        lines.extend(docs_lines)
    lines.extend(
        [
            '- Directed exploration (1–3 targeted searches): use `grep`, `glob`, or `find_symbols` directly',
            '- Broader multi-location exploration: batch parallel searches in one turn before widening scope',
        ]
    )
    if lsp_available:
        lines.append(
            '- Known file + line/column (definition/refs/hover/diagnostics) → `lsp`'
        )
    lines.append('</DISCOVERY_ROUTING>')
    return '\n'.join(lines)


def _explore_hint(_config: Any = None) -> str:
    """Return the canonical layout-discovery tool hint."""
    if _lsp_available(_config):
        return (
            '`grep` (files_with_matches first, then content; head_limit/offset), `glob` for file discovery, '
            '`find_symbols` for symbol candidates, `read` for symbol/file bodies, `lsp` for precise '
            'definitions/references, `analyze_project_structure` for tree/imports/deps/references'
        )
    return (
        '`grep` (files_with_matches first, then content; head_limit/offset), `glob` for file discovery, '
        '`find_symbols` for symbol candidates, `read` for symbol/file bodies, '
        '`analyze_project_structure` for tree/imports/deps/references'
    )


def _repo_discovery_contract(
    *,
    is_windows: bool,
    windows_with_bash: bool,
    shell_is_powershell: bool,
) -> str:
    """One line: prefer ladder tools for repo intelligence; shell details live in SHELL_IDENTITY."""
    if not is_windows:
        return (
            'Repo/source intelligence: follow `<TOOL_ROUTING_LADDER>` and use '
            '`read`—avoid improvised `find`/`grep`/`cat` tree walks; '
            '`<SHELL_IDENTITY>` governs allowed shell usage.'
        )
    if windows_with_bash:
        return (
            'Repo/source intelligence: follow `<TOOL_ROUTING_LADDER>` and editors first; '
            'terminal is Git Bash under `<SHELL_IDENTITY>`.'
        )
    if shell_is_powershell:
        return (
            'Repo/source intelligence: follow `<TOOL_ROUTING_LADDER>` and editors first; '
            'do not use Unix-only shell habits in PowerShell—see `<SHELL_IDENTITY>`.'
        )
    return (
        'Repo/source intelligence: follow `<TOOL_ROUTING_LADDER>` first; '
        'see `<SHELL_IDENTITY>` for shell-specific rules.'
    )


def _path_uncertainty_hint(
    explore: str,
    *,
    is_windows: bool,
    windows_with_bash: bool,
    shell_is_powershell: bool,
) -> str:
    """Short ERROR_RECOVERY path line; defers anti-pattern lists to SHELL_IDENTITY."""
    if not is_windows:
        return (
            f'When paths are uncertain: use {explore}; boundaries in '
            '`<TOOL_ROUTING_LADDER>` + `<SHELL_IDENTITY>`.'
        )
    if windows_with_bash:
        return f'When paths are uncertain: use {explore}; Git Bash rules in `<SHELL_IDENTITY>`.'
    if shell_is_powershell:
        return f'When paths are uncertain: use {explore}; PowerShell rules in `<SHELL_IDENTITY>`.'
    return f'When paths are uncertain: use {explore}; see `<SHELL_IDENTITY>`.'


def _routing_tool_batching_paragraph(function_calling_mode: str | None) -> str:
    _ = function_calling_mode
    return (
        'You may batch independent read-only discovery (`grep`, `glob`, `find_symbols`, '
        '`read` line ranges, `analyze_project_structure`, `lsp`) in one turn when they '
        'improve latency. Dependent edits and runs must remain sequential. '
        'Start bounded: files_with_matches before content, line ranges before whole files; '
        'paginate with head_limit/offset instead of unbounded scans.'
    )


def _routing_memory_tool_placeholders(
    *,
    working_memory_on: bool,
    tracker_on: bool,
    semantic_recall_on: bool = False,
) -> dict[str, str]:
    ambiguous_intent_instruction = 'If intent is still ambiguous after inspection, see `<ASK_USER_TOOL>` rather than guessing.'
    if working_memory_on:
        recall_line = (
            '- `memory(action="recall", key=...)`: fuzzy search when prior turns fell out of '
            'the visible window.\n'
            if semantic_recall_on
            else ''
        )
        memory_and_context_section = (
            '<MEMORY_AND_CONTEXT>\n'
            '**memory** tool — actions:\n'
            '- `memory(action="working", update_type=update, section=..., content=...)`: '
            'session reasoning (hypothesis, findings, blockers, plan). '
            'Auto-restored after condensation; do not re-fetch at session start.\n'
            '- `memory(action="persist", key=..., kind=..., value=...)`: rare workspace facts '
            '(conventions, commands, architecture, lessons). '
            'Ranked workspace memory may appear at session start.\n'
            f'{recall_line}'
            'Do not store task progress in memory — use `task_tracker`.\n'
            '</MEMORY_AND_CONTEXT>'
        )
    else:
        memory_and_context_section = ''
    post_condensation_retrieval = (
        'Resume from the summary and your most recent verified observations.'
    )
    surviving_state_facts = 'Only the visible conversation, current files, and tool observations are available.'
    remaining_work_source_of_truth = (
        'Trust your `task_tracker` plan as the source of truth for what remains.'
        if tracker_on
        else 'Use recent verified observations as the source of truth for what remains.'
    )
    return {
        'ambiguous_intent_instruction': ambiguous_intent_instruction,
        'memory_and_context_section': memory_and_context_section,
        'post_condensation_retrieval': post_condensation_retrieval,
        'surviving_state_facts': surviving_state_facts,
        'remaining_work_source_of_truth': remaining_work_source_of_truth,
    }
