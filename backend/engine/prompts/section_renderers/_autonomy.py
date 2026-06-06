"""Renderer for the autonomy partial (system_partial_01_autonomy.md).

The ``_build_*`` helpers produce the inner blocks that are interpolated into
the autonomy template; keeping them in this module makes the full
autonomy-section assembly readable in one place.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.engine.prompts.section_renderers._env_hints import (
    _explore_hint,
    _lsp_available,
    _path_uncertainty_hint,
)


def _build_context_discipline_section(
    *,
    working_memory_on: bool,
    tracker_on: bool,
    checkpoints_on: bool,
    condensation_on: bool,
) -> str:
    parts = ['<CONTEXT_DISCIPLINE>']
    parts.append(
        'Use the visible conversation, current files, and fresh tool observations as context. '
        'After condensation, resume from the summary without restarting broad exploration.'
    )
    _ = (working_memory_on, checkpoints_on)

    if tracker_on:
        parts.extend(
            [
                '',
                '**task_tracker** — your structural anchor:',
                '- In Agent or Plan mode, use task_tracker(update) with a task_list when you decide a request requires structured work.',
                '- Use task_tracker for viewing and status updates.',
                '- For small/local tasks, do not create tracker overhead; act, verify, and write the final summary.',
                '- If task_tracker was used for this run, keep it synced before the final summary.',
                "- Update status \u2192 'in_progress' when starting, 'done' after proof, 'blocked' with reason.",
                '- For multi-step tasks: task_tracker(view) at turn start to re-anchor.',
            ]
        )
        if condensation_on:
            parts.append('  Post-condensation: task_tracker(view) first.')

    parts.append('</CONTEXT_DISCIPLINE>')
    return '\n'.join(parts)


def _build_when_to_use_context(
    *,
    working_memory_on: bool,
    tracker_on: bool,
    checkpoints_on: bool,
) -> str:
    parts = ['<WHEN_TO_USE_CONTEXT>']
    _ = (working_memory_on, checkpoints_on)
    if tracker_on:
        parts.append(
            '- **task_tracker**: Engineering work planning and progress tracking — update before multi-step tasks, view at turn start.'
        )
    if not tracker_on:
        parts.append('- Use fresh reads/searches and recent observations to stay grounded.')
    parts.append('</WHEN_TO_USE_CONTEXT>')
    return '\n'.join(parts)


def _build_mandatory_discipline_checkpoints(
    *,
    working_memory_on: bool,
    tracker_on: bool,
    checkpoints_on: bool,
) -> str:
    parts = ['<MANDATORY_DISCIPLINE_CHECKPOINTS>']
    _ = (working_memory_on, checkpoints_on)
    items: list[str] = []
    idx = 1
    if tracker_on:
        items.append(
            f'{idx}. For multi-step tasks \u2192 task_tracker(update) with full plan'
        )
        idx += 1
        items.append(
            f'{idx}. At turn start during multi-step work \u2192 task_tracker(view)'
        )
        idx += 1
    if not items:
        items.append('1. For complex work, inspect first and verify before final summary')
    parts.extend(items)
    parts.append('</MANDATORY_DISCIPLINE_CHECKPOINTS>')
    return '\n'.join(parts)


def _build_risk_preview(
    *,
    tracker_on: bool,
) -> str:
    if not tracker_on:
        return ''
    return (
        '<RISK_PREVIEW>\n'
        'Use risk preview only for risky work: multi-file refactors, core runtime changes, concurrency/async changes, lifecycle/tool-schema changes, destructive operations, public API changes, or large generated edits.\n\n'
        'When triggered, write two concrete failure modes before continuing, then after the next major milestone note whether either occurred and pivot if needed.\n\n'
        'For small/local edits, skip formal risk preview.\n'
        '</RISK_PREVIEW>'
    )


def _build_autonomy_block(_mode: str, *, checkpoints_on: bool) -> str:
    _ = checkpoints_on
    return (
        '<AUTONOMY>\n'
        'For implementation work, drive the request through tools and verification; '
        'for discussion or planning work, keep the response aligned with the active protocol. '
        'The runtime may interrupt a tool call to surface a user decision; treat that decision as '
        'authoritative and continue from where you stopped. On tool failure, make '
        'the next action a corrected retry or a different tool (e.g. `read` \u2192 `edit_symbols`, '
        'or `read` \u2192 `replace_string`) and auto-retry recoverable errors before reporting back.'
        '\n</AUTONOMY>'
    )


def _render_autonomy(
    render_partial: Callable[..., str],
    config: Any,
    *,
    is_windows: bool,
    windows_with_bash: bool,
    shell_is_powershell: bool,
) -> str:
    from backend.core.interaction_modes import (
        normalize_interaction_mode,
    )

    mode = normalize_interaction_mode(getattr(config, 'mode', 'agent'))
    checkpoints_on = bool(getattr(config, 'enable_checkpoints', False))
    working_memory_on = bool(getattr(config, 'enable_working_memory', True))
    condensation_on = bool(getattr(config, 'enable_condensation_request', False))
    tracker_on = bool(getattr(config, 'enable_task_tracker_tool', False))

    autonomy_block = _build_autonomy_block(mode, checkpoints_on=checkpoints_on)
    context_discipline = _build_context_discipline_section(
        working_memory_on=working_memory_on,
        tracker_on=tracker_on,
        checkpoints_on=checkpoints_on,
        condensation_on=condensation_on,
    )
    when_to_use_context = _build_when_to_use_context(
        working_memory_on=working_memory_on,
        tracker_on=tracker_on,
        checkpoints_on=checkpoints_on,
    )
    mandatory_discipline_checkpoints = _build_mandatory_discipline_checkpoints(
        working_memory_on=working_memory_on,
        tracker_on=tracker_on,
        checkpoints_on=checkpoints_on,
    )
    risk_preview = _build_risk_preview(tracker_on=tracker_on)

    explore = _explore_hint(config)
    path_hint = _path_uncertainty_hint(
        explore,
        is_windows=is_windows,
        windows_with_bash=windows_with_bash,
        shell_is_powershell=shell_is_powershell,
    )
    if tracker_on:
        task_tracker_discipline_block = (
            '<TASK_TRACKING>\n'
            '**task_tracker**: In Agent or Plan mode, use `task_tracker(update, task_list=[...])` as your first action when you commit to structured work.\n'
            'Use `view` to inspect the plan, `update` to replace the full `task_list`, and `update_status` for single-task status changes.\n'
            'Quick status updates: use `update_status(task_id="...", status="done")` to change a single task status by ID. Optional `result` field captures outcome.\n'
            'Allowed statuses: `todo`, `in_progress`, `done`, `skipped`, `blocked`.\n'
            'Each step object has: `id` (string, e.g. "1" or "1.1"), `description` (string), `status` (one of the allowed statuses), `result` (optional string), `tags` (optional LIST of strings — never a bare string), `subtasks` (optional recursive list of the same shape).\n'
            '**Completion**: Before the final summary, no task should remain `todo` or `in_progress`. Mark truly completed work `done`, intentionally omitted work `skipped`, and only genuinely blocked work `blocked` with a reason.'
            '</TASK_TRACKING>'
        )
    else:
        task_tracker_discipline_block = ''

    base_workflow = (
        'Default loop: scope \u2192 reproduce \u2192 isolate \u2192 fix \u2192 verify.\n'
        'For debug/fix tasks, re-run the same reproducer when possible.'
    )
    if tracker_on:
        problem_solving_workflow_body = (
            base_workflow
            + '\n\nWith **task_tracker** enabled, treat **sync** as part of the loop: after verify, update the plan when progress changed.'
        )
        task_sync_instruction = '**Task synchronization:** Update `task_tracker` to `done`, `skipped`, or `blocked` before writing the final summary.'
    else:
        problem_solving_workflow_body = base_workflow
        task_sync_instruction = '**Plan synchronization:** Keep your final response aligned with what was actually completed.'

    lsp_avail = _lsp_available(config)
    error_recovery_pivot_lines = (
        '- `grep` / `glob` \u2192 `lsp` (check locally with the language server; no shell grep)\n'
        '- `lsp` \u2192 `grep` (wider text search)'
        if lsp_avail
        else ''
    )

    return render_partial(
        'system_partial_01_autonomy.md',
        autonomy_block=autonomy_block,
        context_discipline=context_discipline,
        when_to_use_context=when_to_use_context,
        mandatory_discipline_checkpoints=mandatory_discipline_checkpoints,
        risk_preview=risk_preview,
        task_tracker_discipline_block=task_tracker_discipline_block,
        task_sync_instruction=task_sync_instruction,
        path_discovery_hint=path_hint,
        problem_solving_workflow_body=problem_solving_workflow_body,
        error_recovery_pivot_lines=error_recovery_pivot_lines,
    )
