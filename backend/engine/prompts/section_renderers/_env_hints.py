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


def _explore_hint(_config: Any = None) -> str:
    """Return the canonical layout-discovery tool hint."""
    if _lsp_available(_config):
        return (
            '`grep` for text search, `glob` for file discovery, `find_symbols` for symbol candidates, '
            '`read` to fetch a specific symbol/file body, `lsp` for definitions/references '
            '(LSP), `analyze_project_structure` for tree layout'
        )
    return (
        '`grep` for text search, `glob` for file discovery, `find_symbols` for symbol candidates, `read` to fetch a '
        'specific symbol/file body, `analyze_project_structure` for tree layout'
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
    return (
        'You may batch independent code search or read operations in one turn '
        'when they improve latency. Dependent edits and runs must remain sequential.'
    )


def _routing_memory_tool_placeholders(
    *,
    working_memory_on: bool,
    tracker_on: bool,
    condensation_on: bool,
    meta_cognition_on: bool,
) -> dict[str, str]:
    _ = meta_cognition_on
    ambiguous_intent_instruction = (
        'Use `ask_user` with a short question rather than guessing.'
    )
    _ = working_memory_on
    memory_and_context_section = ''
    post_condensation_retrieval = (
        'Resume from the summary and your most recent verified observations.'
    )
    surviving_state_facts = (
        'Only the visible conversation, current files, and tool observations are available.'
    )
    context_budget_sync_clause = ', sync `task_tracker`' if tracker_on else ''
    context_budget_next_step = (
        'write the final summary or continue after automatic condensation'
        if condensation_on
        else 'write the final summary or close the current sub-task before doing any broader exploration'
    )
    repetition_recovery_options = (
        'switch tools, use `ask_user` for required input, or write a partial final result.'
    )
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
        'context_budget_sync_clause': context_budget_sync_clause,
        'context_budget_next_step': context_budget_next_step,
        'repetition_recovery_options': repetition_recovery_options,
        'remaining_work_source_of_truth': remaining_work_source_of_truth,
    }
