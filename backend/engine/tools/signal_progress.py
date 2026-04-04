"""signal_progress tool — proactive circuit-breaker deferral.

The LLM calls this every 10-15 steps on large multi-file tasks to tell the
controller it is making intentional forward progress.  The controller
partially resets the stuck-detection counter, preventing false interruptions
on long but healthy migrations or refactors.
"""

from __future__ import annotations

from typing import Any

from backend.ledger.action.signal import SignalProgressAction

SIGNAL_PROGRESS_TOOL_NAME = 'signal_progress'


def create_signal_progress_tool() -> dict[str, Any]:
    """Return the OpenAI function-calling tool definition for signal_progress."""
    return {
        'type': 'function',
        'function': {
            'name': SIGNAL_PROGRESS_TOOL_NAME,
            'description': (
                'Signal forward progress on a long-running task to prevent stuck-loop detection. '
                'Call every 10-15 steps during sustained multi-file operations. '
                'Do NOT call if actually stuck — use escalate() instead.'
            ),
            'parameters': {
                'type': 'object',
                'properties': {
                    'progress_note': {
                        'type': 'string',
                        'description': (
                            'A brief note describing what you just completed and what '
                            'you plan to do next. Example: '
                            "'Migrated files 1-5 of 20. Next: migrate files 6-10.'"
                        ),
                    },
                },
                'required': ['progress_note'],
            },
        },
    }


def build_signal_progress_action(arguments: dict) -> SignalProgressAction:
    """Build a SignalProgressAction from tool call arguments."""
    from backend.core.errors import FunctionCallValidationError

    note = arguments.get('progress_note', '')
    if not note:
        raise FunctionCallValidationError(
            'Missing required argument "progress_note" in tool call signal_progress'
        )
    return SignalProgressAction(progress_note=str(note))
