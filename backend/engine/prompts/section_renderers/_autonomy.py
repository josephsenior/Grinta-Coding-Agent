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
        'You have persistent context tools. Use them — context condensation is free '
        'and silent; relying only on attention-backed context guarantees information loss.'
    )

    # note/recall are always available — unconditional include
    parts.extend(
        [
            '',
            '**note/recall** — facts that must survive across turns and new tasks:',
            '- Decision made, architectural constraint discovered, stable command found, or project convention learned \u2192 note() when useful.',
            '- Never store raw secrets, tokens, passwords, private keys, or credentials in note/memory. Store only non-sensitive facts such as "API key exists in env var X" when needed.',
            '- Workspace architecture, DB URL, port mapping, test command \u2192 note().',
            "- recall(key='all') at session start to re-ground; never recall 'lessons' twice this session.",
        ]
    )

    if working_memory_on:
        parts.extend(
            [
                '',
                '**memory_manager** — your structured cognitive workspace for the current session:',
                "- update section='hypothesis' when you form a theory; update 'findings' when you have evidence.",
                "- update section='blockers' when something is stuck; update 'decisions' at each architectural pivot.",
                '- Call memory_manager(get) before context re-reads you might skip.',
            ]
        )

    if tracker_on:
        parts.extend(
            [
                '',
                '**task_tracker** — your structural anchor:',
                '- In Agent or Plan mode, call create_task_tracker first when you decide a request requires structured work.',
                '- Use task_tracker for viewing and status updates after the tracker exists.',
                '- For small/local tasks, do not create tracker overhead; act, verify, and finish.',
                '- If task_tracker was used for this run, keep it synced before finish.',
                "- Update status \u2192 'in_progress' when starting, 'done' after proof, 'blocked' with reason.",
                '- For multi-step tasks: task_tracker(view) at turn start to re-anchor.',
            ]
        )
        if condensation_on:
            if working_memory_on:
                parts.append(
                    '  Post-condensation: task_tracker(view) first, then memory_manager(get) + scratchpad.'
                )
            else:
                parts.append(
                    '  Post-condensation: task_tracker(view) first, then scratchpad.'
                )

    if checkpoints_on:
        parts.extend(
            [
                '',
                '**checkpoint** — Use checkpoint before destructive operations or risky non-atomic multi-step edits.',
                '`multiedit` already provides atomic edit semantics; use checkpoint when rollback beyond a single atomic edit would be valuable.',
            ]
        )

    parts.append('</CONTEXT_DISCIPLINE>')
    return '\n'.join(parts)


def _build_when_to_use_context(
    *,
    working_memory_on: bool,
    tracker_on: bool,
    checkpoints_on: bool,
) -> str:
    parts = ['<WHEN_TO_USE_CONTEXT>']
    parts.append(
        '- **note/recall**: Cross-turn persistence for facts, decisions, and discoveries.'
    )
    if working_memory_on:
        parts.append(
            '- **memory_manager**: In-session structured workspace for hypotheses, blockers, findings, and decisions.'
        )
    if tracker_on:
        parts.append(
            '- **task_tracker**: Engineering work planning and progress tracking — update before multi-step tasks, view at turn start.'
        )
    if checkpoints_on:
        parts.append(
            '- **checkpoint**: Before destructive or multi-file batch operations — save state so you can rollback.'
        )
    parts.append('</WHEN_TO_USE_CONTEXT>')
    return '\n'.join(parts)


def _build_mandatory_discipline_checkpoints(
    *,
    working_memory_on: bool,
    tracker_on: bool,
    checkpoints_on: bool,
) -> str:
    parts = ['<MANDATORY_DISCIPLINE_CHECKPOINTS>']
    # Session start is always relevant
    items = ["1. Session start \u2192 recall(key='all')"]
    idx = 2
    if tracker_on:
        items.append(
            f'{idx}. For multi-step tasks \u2192 create_task_tracker with full plan'
        )
        idx += 1
        items.append(
            f'{idx}. At turn start during multi-step work \u2192 task_tracker(view)'
        )
        idx += 1
    if checkpoints_on:
        items.append(f'{idx}. Before destructive ops \u2192 checkpoint.save')
        idx += 1
    items.append(
        f'{idx}. On decision/pivot/discovery \u2192 note() or{" memory_manager(update) or" if working_memory_on else ""} note()'
    )
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
        'Use risk preview only for risky work: multi-file refactors, core runtime changes, concurrency/async changes, lifecycle/finish/tool-schema changes, destructive operations, public API changes, or large generated edits.\n\n'
        'When triggered, write two concrete failure modes before continuing, then after the next major milestone note whether either occurred and pivot if needed.\n\n'
        'For small/local edits, skip formal risk preview.\n'
        '</RISK_PREVIEW>'
    )


def _build_autonomy_block(_mode: str, *, checkpoints_on: bool) -> str:
    cp_line = (
        " Auto-save occurs before large writes; use 'checkpoint' tool to manually save logically safe states."
        if checkpoints_on
        else ''
    )
    return (
        '<AUTONOMY>\n'
        'For implementation work, drive the request through tools and verification; '
        'for discussion or planning work, keep the response aligned with the active protocol. '
        'The runtime may interrupt a tool call to surface a user decision; treat that decision as '
        'authoritative and continue from where you stopped. On tool failure, make '
        'the next action a corrected retry or a different tool (e.g. `read` \u2192 `edit_symbols`, '
        'or `read` \u2192 `replace_string`) and auto-retry recoverable errors before reporting back.'
        f'{cp_line}\n</AUTONOMY>'
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
            '**create_task_tracker**: In Agent or Plan mode, use this as your first action when you commit to structured work.\n'
            '**task_tracker**: After creation, use `view` to inspect the plan, `update` to replace the full `task_list`, and `update_status` for single-task status changes.\n'
            'Quick status updates: use `update_status(task_id="...", status="done")` to change a single task status by ID. Optional `result` field captures outcome.\n'
            'Allowed statuses: `todo`, `in_progress`, `done`, `skipped`, `blocked`.\n'
            'Each step object has: `id` (string, e.g. "1" or "1.1"), `description` (string), `status` (one of the allowed statuses), `result` (optional string), `tags` (optional LIST of strings — never a bare string), `subtasks` (optional recursive list of the same shape).\n'
            '**Completion**: Before `finish`, no task should remain `todo` or `in_progress`. Mark truly completed work `done`, intentionally omitted work `skipped`, and only genuinely blocked work `blocked` with a reason.'
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
        task_sync_instruction = '**Task synchronization:** Update `task_tracker` to `done`, `skipped`, or `blocked` before attempting to finish.'
    else:
        problem_solving_workflow_body = base_workflow
        task_sync_instruction = '**Plan synchronization:** Keep your working memory, finish response, and finish summary aligned with what was actually completed before attempting to finish.'

    lsp_avail = _lsp_available(config)
    error_recovery_pivot_lines = (
        '- `search_code` \u2192 `lsp` (check locally with the language server; no shell grep)\n'
        '- `lsp` \u2192 `search_code` (wider text search)'
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
