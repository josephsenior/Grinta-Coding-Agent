"""Renderer for the worked-examples partial (system_partial_05_examples.md)."""

from __future__ import annotations

from collections.abc import Callable


def _render_examples(
    render_partial: Callable[..., str],
    *,
    tracker_on: bool,
    meta_cognition_on: bool,
    lsp_available: bool,
    checkpoints_on: bool,
) -> str:
    """Render the worked-examples partial with capability-aware tool references."""
    if tracker_on:
        planning_hint = 'draft the plan with `task_tracker`'
    else:
        planning_hint = 'plan by thinking step-by-step in your head'

    destructive_confirmation_step = (
        'Use `communicate_with_user` to confirm scope and target.'
        if meta_cognition_on
        else 'ask the user a short clarifying question in natural language to confirm scope and target.'
    )
    checkpoint_step = (
        'If approved and supported, take a `checkpoint` first.'
        if checkpoints_on
        else 'If approved, keep the change surface small and verify immediately after the action.'
    )
    adjacent_tool_fallback = (
        'symbol lookup → `search_code`; `lsp` → `search_code`'
        if lsp_available
        else 'symbol lookup → `search_code`; refine the `search_code` query and read nearby files'
    )
    failure_escalation_step = (
        'After 3 failed attempts on the same sub-task, escalate via `communicate_with_user` with a 1-line post-mortem and a specific question.'
        if meta_cognition_on
        else 'After 3 failed attempts on the same sub-task, ask the user with a 1-line post-mortem and a specific question.'
    )
    return render_partial(
        'system_partial_05_examples.md',
        planning_hint=planning_hint,
        destructive_confirmation_step=destructive_confirmation_step,
        checkpoint_step=checkpoint_step,
        adjacent_tool_fallback=adjacent_tool_fallback,
        failure_escalation_step=failure_escalation_step,
    )
