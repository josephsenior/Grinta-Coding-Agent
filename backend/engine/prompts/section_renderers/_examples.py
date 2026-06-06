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
        'Use `ask_user` to confirm scope and target.'
    )
    _ = (meta_cognition_on, checkpoints_on)
    checkpoint_step = (
        'If approved, keep the change surface small and verify immediately after the action.'
    )
    adjacent_tool_fallback = (
        'symbol lookup → `grep`; `lsp` → `grep`'
        if lsp_available
        else 'symbol lookup → `grep`; refine the `grep` query and read nearby files'
    )
    failure_escalation_step = (
        'After repeated failed attempts on the same sub-task, use `ask_user` with a 1-line post-mortem and a specific question.'
    )
    return render_partial(
        'system_partial_05_examples.md',
        planning_hint=planning_hint,
        destructive_confirmation_step=destructive_confirmation_step,
        checkpoint_step=checkpoint_step,
        adjacent_tool_fallback=adjacent_tool_fallback,
        failure_escalation_step=failure_escalation_step,
    )
