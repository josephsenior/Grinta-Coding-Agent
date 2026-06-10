"""Renderer for the interaction tail partial (system_partial_03_tail.md)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


def _build_response_style_block(
    _mode: str, *, meta_cognition_on: bool = False
) -> str:
    _ = meta_cognition_on
    return (
        'Use the output form required for this turn:\n'
        '- use tools for investigation or implementation when the protocol calls for action\n'
        '- use plain prose only for conversation, explanation, or the final summary'
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
    response_style_body = _build_response_style_block(
        resolved_mode,
        meta_cognition_on=False,
    )
    communicate_tool_section = (
        '<ASK_USER_TOOL>\n'
        'Use `ask_user(questions=[...])` only when user input is required to continue. '
        'Do not use plain text for a mid-task question; plain text ends the run.\n'
        '</ASK_USER_TOOL>'
    )
    return render_partial(
        'system_partial_03_tail.md',
        response_style_body=response_style_body,
        communicate_tool_section=communicate_tool_section,
        interaction_guidance=(
            'If a request is vague, inspect nearby docs/config first; see `<ASK_USER_TOOL>` only if you are still blocked or the scope is still ambiguous.'
        ),
    )
