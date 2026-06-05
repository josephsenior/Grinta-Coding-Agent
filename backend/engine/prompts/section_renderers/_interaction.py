"""Renderer for the interaction tail partial (system_partial_03_tail.md)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _build_response_style_block(
    _mode: str, *, meta_cognition_on: bool = False
) -> str:
    clarification_line = (
        '- use `communicate_with_user` for blocking questions when available'
        if meta_cognition_on
        else '- ask the user a short clarifying question in natural language when genuinely blocked'
    )
    return (
        'Use the output form required for this turn:\n'
        '- use tools for investigation or implementation when the protocol calls for action\n'
        f'{clarification_line}\n'
        '- use `finish` for final outcomes when the protocol requires a structured completion\n'
        '- use plain prose for conversation, explanation, or final summaries when allowed'
    )


def _render_interaction_tail(
    render_partial: Callable[..., str],
    config: Any,
    mode: str | None = None,
) -> str:
    from backend.core.interaction_modes import normalize_interaction_mode

    resolved_mode = normalize_interaction_mode(
        mode if mode is not None else getattr(config, 'mode', 'agent')
    )
    meta_cognition = getattr(config, 'enable_meta_cognition', False)
    response_style_body = _build_response_style_block(
        resolved_mode,
        meta_cognition_on=meta_cognition,
    )
    communicate_tool_section = (
        '<COMMUNICATE_TOOL>\n'
        'Use `communicate_with_user` to interact with the user. Pick the right intent:\n'
        '  - `clarification` (default): ask a question, optionally with multiple-choice options. Use `options` with `{label, description?}` objects.\n'
        '  - `proposal`: offer 2+ alternative approaches; set `recommended` to the index of the one you think is best.\n'
        '  - `confirm`: require explicit user OK before a destructive or irreversible action. Provide exactly two options; the safe option (deny) is pre-selected.\n'
        '  - `inform`: share a non-blocking status update; the turn continues.\n'
        '  - `uncertainty`: flag low confidence; supply `uncertainty_level` (0.0-1.0) and a list of specific concerns.\n'
        '  - `escalate`: after 3 failed attempts on a sub-task, hand off to the human; include a structured `attempts` list and a `specific_help_needed` sentence.\n'
        'Do not ask mid-task questions in plain text; use this tool so the turn ends cleanly and waits for user input.\n'
        '</COMMUNICATE_TOOL>'
        if meta_cognition
        else ''
    )
    return render_partial(
        'system_partial_03_tail.md',
        response_style_body=response_style_body,
        communicate_tool_section=communicate_tool_section,
        interaction_guidance=(
            'If a request is vague, inspect nearby docs/config first; use `communicate_with_user` only if you are still blocked or the scope is still ambiguous.'
            if meta_cognition
            else 'If a request is vague, inspect nearby docs/config first; ask the user directly in natural language only if you are still blocked or the scope is still ambiguous.'
        ),
    )
