"""Renderer for the autonomy partial (system_partial_01_autonomy.md).

The ``_build_*`` helpers produce the inner blocks that are interpolated into
the autonomy template; keeping them in this module makes the full
autonomy-section assembly readable in one place.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.engine.prompts.section_renderers._common import _semantic_recall_runtime
from backend.engine.prompts.section_renderers._env_hints import (
    _explore_hint,
    _lsp_available,
    _path_uncertainty_hint,
)

_CRITERIA_VS_TASKS_EXAMPLE = (
    '**Example (criteria vs tasks):** '
    'Criteria (outcomes): ac1 "pytest backend/tests/unit/foo.py exits 0" (stated); '
    'ac2 "No new public API exports" (inferred). '
    'Tasks (milestones): 1 Reproduce failure; 2 Fix root cause; 3 Verify and audit.'
)


def _build_context_discipline_section(
    *,
    working_memory_on: bool,
    tracker_on: bool,
    criteria_on: bool = True,
    checkpoints_on: bool,
    condensation_on: bool,
    semantic_recall_on: bool = False,
) -> str:
    parts = ['<CONTEXT_DISCIPLINE>']
    parts.append(
        'Use the visible conversation, current files, and fresh tool observations as context. '
        'After condensation, follow `<SELF_REGULATION>`.'
    )
    if working_memory_on:
        memory_actions = 'working/persist'
        if semantic_recall_on:
            memory_actions += '/recall'
        parts.extend(
            [
                '',
                f'**memory** — see `<MEMORY_AND_CONTEXT>` for {memory_actions}.',
            ]
        )
    if checkpoints_on:
        parts.append(
            '**checkpoint** — see System Capabilities and `<EDITOR_AND_FILE_OPERATIONS>`.'
        )

    if tracker_on:
        parts.extend(
            [
                '',
                '**task_tracker** — see `<TASK_TRACKING>`.',
            ]
        )
        if condensation_on:
            parts.append('Post-condensation: `task_tracker(view)` first.')

    if criteria_on:
        parts.extend(
            [
                '',
                '**acceptance_criteria** — see `<ACCEPTANCE_CRITERIA>`.',
            ]
        )
        if condensation_on:
            parts.append(
                'Post-condensation: persisted and auto-re-injected — use '
                '`acceptance_criteria(view)` for stable ids; do not redefine unless scope changed.'
            )

    parts.append('</CONTEXT_DISCIPLINE>')
    return '\n'.join(parts)


def _build_when_to_use_context(
    *,
    working_memory_on: bool,
    tracker_on: bool,
    criteria_on: bool = True,
    checkpoints_on: bool,
    semantic_recall_on: bool = False,
) -> str:
    parts = ['<WHEN_TO_USE_CONTEXT>']
    if working_memory_on:
        parts.append('- **memory**: See `<MEMORY_AND_CONTEXT>`.')
    if checkpoints_on:
        parts.append(
            '- **checkpoint**: before revert or when milestones are stale — see System Capabilities.'
        )
    if tracker_on:
        parts.append('- **task_tracker**: See `<TASK_TRACKING>`.')
    if criteria_on:
        parts.append(
            '- **acceptance_criteria**: See `<ACCEPTANCE_CRITERIA>`. '
            'Persisted across condensation — use `update` before work, `view` after compaction '
            'for stable ids, `refine` to correct one assertion, and `audit(audit_entries=[...])` '
            'with `evidence_ref` before the final summary.'
        )
    if not tracker_on and not criteria_on:
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


def _build_autonomy_block(_mode: str) -> str:
    return (
        '<AUTONOMY>\n'
        'For implementation work, drive the request through tools and verification; '
        'for discussion or planning work, keep the response aligned with the active protocol. '
        'During implementation, continue work through tool calls. Plain text without tool calls ends the run — '
        'see the active mode protocol for when to write it. '
        'If the user changes or contradicts the task mid-run, treat the latest user directive as authoritative. '
        'Preserve completed work that still applies, drop work that no longer applies, and continue from the new instruction. '
        'The runtime may interrupt a tool call to surface a user decision; treat that decision as '
        'authoritative and continue from where you stopped. On tool failure, follow `<ERROR_RECOVERY>`.'
        '\n</AUTONOMY>'
    )


def _build_task_sync_instruction(*, tracker_on: bool, criteria_on: bool) -> str:
    if not tracker_on and not criteria_on:
        return '**Plan synchronization:** Keep your final response aligned with what was actually completed.'
    steps: list[str] = []
    if tracker_on:
        steps.append(
            'sync `task_tracker` (no open `todo`/`in_progress` unless truly blocked)'
        )
    steps.append('run the narrowest verification')
    if criteria_on:
        steps.append(
            '`acceptance_criteria(audit, audit_entries=[...])` with `evidence_ref` '
            'pointing at prior tool output'
        )
    steps.append('write the final summary')
    ordered = '; '.join(f'{index}. {step}' for index, step in enumerate(steps, 1))
    return f'**Completion ritual:** Before the final summary: {ordered}.'


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
    criteria_on = bool(getattr(config, 'enable_acceptance_criteria_tool', True))
    semantic_recall_on = _semantic_recall_runtime(
        config, semantic_recall_active=semantic_recall_active
    )

    autonomy_block = _build_autonomy_block(mode)
    context_discipline = _build_context_discipline_section(
        working_memory_on=working_memory_on,
        tracker_on=tracker_on,
        criteria_on=criteria_on,
        checkpoints_on=checkpoints_on,
        condensation_on=condensation_on,
        semantic_recall_on=semantic_recall_on,
    )
    when_to_use_context = _build_when_to_use_context(
        working_memory_on=working_memory_on,
        tracker_on=tracker_on,
        criteria_on=criteria_on,
        checkpoints_on=checkpoints_on,
        semantic_recall_on=semantic_recall_on,
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
            '**task_tracker**: Coarse execution plan only — 3–7 parent steps, not micro-requirements.\n'
            'Task steps are activities/milestones, not verifiable outcomes (those belong in `<ACCEPTANCE_CRITERIA>`).\n'
            'Use `task_tracker(update, task_list=[...])` when you commit to structured work.\n'
            'Use `view` to inspect the plan, `update` to replace the full `task_list`, and `update_status` for single-task status changes.\n'
            'Quick status updates: use `update_status(task_id="...", status="done")` to change a single task status by ID. Optional `result` field captures outcome.\n'
            'Allowed statuses: `todo`, `in_progress`, `done`, `skipped`, `blocked`.\n'
            'Each step object has: `id` (string, e.g. "1"), `description` (string), `status` (one of the allowed statuses), `result` (optional string), `tags` (optional LIST of strings — never a bare string).\n'
            '**Completion**: Before the final summary, no task should remain `todo` or `in_progress`. Mark truly completed work `done`, intentionally omitted work `skipped`, and only genuinely blocked work `blocked` with a reason.\n'
            f'{_CRITERIA_VS_TASKS_EXAMPLE}\n'
            '</TASK_TRACKING>'
        )
    else:
        task_tracker_discipline_block = ''

    if criteria_on:
        tracker_follow = ', then `task_tracker(update, ...)`' if tracker_on else ''
        during_work = (
            '**During work:** update only the coarse `task_tracker` plan — not criteria.\n'
            if tracker_on
            else '**During work:** do not rewrite criteria unless something important was missed (`append`).\n'
        )
        checkpoint = (
            '**Component checkpoint:** when marking a `task_tracker` step done, glance at related criteria.\n'
            if tracker_on
            else ''
        )
        acceptance_criteria_discipline_block = (
            '<ACCEPTANCE_CRITERIA>\n'
            '**acceptance_criteria**: Flat verifiable assertions for what must be true when done.\n'
            f'**Start ritual:** required before work — call '
            f'`acceptance_criteria(update, criteria_list=[...])`{tracker_follow}.\n'
            '**Condensation:** persisted and auto-re-injected after context compaction; '
            'use `view` for stable ids — do not redefine unless scope changed.\n'
            'See `<COMMON_PATTERNS>` for worked flows.\n'
            'Tag each item `source: "stated"` (user/directive) or `"inferred"` (agent-proposed scope extension — proceed autonomously). '
            'Use assertion phrasing, not activities.\n'
            f'{_CRITERIA_VS_TASKS_EXAMPLE}\n'
            f'{during_work}'
            f'{checkpoint}'
            '**Refine:** when implementation reveals a wrong assertion, `refine(criterion_id, new_assertion, reason)` — do not rewrite the full list.\n'
            '**Audit:** before the final summary, `audit(audit_entries=[{criterion_id, evidence_ref}, ...])` citing prior tool output '
            '(e.g. `call_<id>:lines[n-m]` or `event:<id>:lines[n-m]`); free-text only with `unverifiable: true`.\n'
            'Legacy bulk `audit(criteria_list=[...])` with free-text evidence still works but is deprecated.\n'
            'Use `view` to read ids; `append` only for rare gaps.\n'
            '</ACCEPTANCE_CRITERIA>'
        )
    else:
        acceptance_criteria_discipline_block = ''

    problem_solving_workflow_body = (
        'Default loop: scope → reproduce → isolate → fix → verify.\n'
        'For debug/fix tasks, re-run the same reproducer when possible.'
    )
    if tracker_on:
        problem_solving_workflow_body += '\n\nWith **task_tracker** enabled, sync the plan after verify when progress changed.'

    task_sync_instruction = _build_task_sync_instruction(
        tracker_on=tracker_on, criteria_on=criteria_on
    )

    lsp_avail = _lsp_available(config)
    error_recovery_pivot_lines = (
        '- `grep` / `glob` → `lsp` (check locally with the language server; no shell grep)\n'
        '- `lsp` → `grep` (wider text search)'
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
        acceptance_criteria_discipline_block=acceptance_criteria_discipline_block,
        task_sync_instruction=task_sync_instruction,
        path_discovery_hint=path_hint,
        problem_solving_workflow_body=problem_solving_workflow_body,
        error_recovery_pivot_lines=error_recovery_pivot_lines,
    )
