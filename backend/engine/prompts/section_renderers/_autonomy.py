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


def _semantic_recall_runtime(
    config: Any, *, semantic_recall_active: bool | None = None
) -> bool:
    from backend.utils.optional_extras import resolve_semantic_recall_for_prompt

    return resolve_semantic_recall_for_prompt(
        config, semantic_recall_active=semantic_recall_active
    )


def _build_context_discipline_section(
    *,
    working_memory_on: bool,
    tracker_on: bool,
    checkpoints_on: bool,
    condensation_on: bool,
    semantic_recall_on: bool = False,
) -> str:
    parts = ['<CONTEXT_DISCIPLINE>']
    parts.append(
        'Use the visible conversation, current files, and fresh tool observations as context. '
        'After condensation, resume from durable state without restarting broad exploration.'
    )
    if working_memory_on:
        memory_actions = 'working/persist'
        if semantic_recall_on:
            memory_actions += '/recall'
        parts.extend(
            [
                '',
                f'**memory** — see `<MEMORY_AND_CONTEXT>` for {memory_actions}; '
                'do not duplicate task progress here.',
            ]
        )
    if checkpoints_on:
        parts.append(
            '**checkpoint** — auto snapshots precede risky edits; use `save` for named milestones, '
            '`revert` when recovery is needed, `clear` when ending a task or resetting the list.'
        )

    if tracker_on:
        parts.extend(
            [
                '',
                '**task_tracker** — see `<TASK_TRACKING>` for planning, sync, and completion rules.',
            ]
        )
        if condensation_on:
            parts.append('Post-condensation: `task_tracker(view)` first.')

    parts.append('</CONTEXT_DISCIPLINE>')
    return '\n'.join(parts)


def _build_when_to_use_context(
    *,
    working_memory_on: bool,
    tracker_on: bool,
    checkpoints_on: bool,
    semantic_recall_on: bool = False,
) -> str:
    parts = ['<WHEN_TO_USE_CONTEXT>']
    if working_memory_on:
        parts.append(
            '- **memory(action="working")**: hypothesis, findings, blockers, and plan during long work.'
        )
        if semantic_recall_on:
            parts.append(
                '- **memory(action="recall", key=...)**: when the visible window no longer shows a prior decision.'
            )
        parts.append(
            '- **memory(action="persist", kind=...)**: rare, only for verified knowledge worth keeping across sessions. '
            'Tactical kinds (`convention`/`command`/`architecture`/`lesson`) for codebase facts; '
            'strategic kinds (`strategy`/`heuristic`/`decision`/`preference`) for higher-level knowledge. '
            'Task progress belongs in `task_tracker`, not memory.'
        )
    if checkpoints_on:
        parts.append(
            '- **checkpoint**: `view` before choosing a revert target; `revert` after a bad edit '
            'or failed command; `clear` when the saved milestone list is stale.'
        )
    if tracker_on:
        parts.append('- **task_tracker**: See `<TASK_TRACKING>`.')
    if not tracker_on:
        parts.append(
            '- Use fresh reads/searches and recent observations to stay grounded.'
        )
    parts.append('</WHEN_TO_USE_CONTEXT>')
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
        'During implementation, continue work through tool calls. Plain text without tool calls is treated as '
        'the final response, so reserve it for completion, user-facing explanation, or an honest blocked/partial result. '
        'If the user changes or contradicts the task mid-run, treat the latest user directive as authoritative. '
        'Preserve completed work that still applies, drop work that no longer applies, and continue from the new instruction. '
        'The runtime may interrupt a tool call to surface a user decision; treat that decision as '
        'authoritative and continue from where you stopped. On tool failure, follow `<ERROR_RECOVERY>`.'
        '\n</AUTONOMY>'
    )


def _render_autonomy(
    render_partial: Callable[..., str],
    config: Any,
    *,
    is_windows: bool,
    windows_with_bash: bool,
    shell_is_powershell: bool,
    semantic_recall_active: bool | None = None,
) -> str:
    from backend.core.interaction_modes import (
        normalize_interaction_mode,
    )

    mode = normalize_interaction_mode(getattr(config, 'mode', 'agent'))
    checkpoints_on = bool(getattr(config, 'enable_checkpoints', True))
    working_memory_on = bool(getattr(config, 'enable_working_memory', True))
    condensation_on = bool(getattr(config, 'enable_condensation_request', False))
    tracker_on = bool(getattr(config, 'enable_task_tracker_tool', True))

    autonomy_block = _build_autonomy_block(mode, checkpoints_on=checkpoints_on)
    context_discipline = _build_context_discipline_section(
        working_memory_on=working_memory_on,
        tracker_on=tracker_on,
        checkpoints_on=checkpoints_on,
        condensation_on=condensation_on,
        semantic_recall_on=_semantic_recall_runtime(
            config, semantic_recall_active=semantic_recall_active
        ),
    )
    when_to_use_context = _build_when_to_use_context(
        working_memory_on=working_memory_on,
        tracker_on=tracker_on,
        checkpoints_on=checkpoints_on,
        semantic_recall_on=_semantic_recall_runtime(
            config, semantic_recall_active=semantic_recall_active
        ),
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
            'Set `title` to the objective; define what "done" looks like before decomposing into steps.\n'
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
        task_sync_instruction = (
            '**Task synchronization:** See `<TASK_TRACKING>` before the final summary.'
        )
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
        risk_preview=risk_preview,
        task_tracker_discipline_block=task_tracker_discipline_block,
        task_sync_instruction=task_sync_instruction,
        path_discovery_hint=path_hint,
        problem_solving_workflow_body=problem_solving_workflow_body,
        error_recovery_pivot_lines=error_recovery_pivot_lines,
    )
