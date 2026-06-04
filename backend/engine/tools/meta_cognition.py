"""Meta-cognition tools enabling the LLM to express uncertainty and seek guidance.

These tools allow the LLM to interact with the user or system to express doubt,
ask for clarification, propose options, request explicit confirmation, post a
non-blocking status update, or escalate when stuck.
"""

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import create_tool_definition

# Single unified tool name
COMMUNICATE_TOOL_NAME = 'communicate_with_user'

_VALID_INTENTS: frozenset[str] = frozenset(
    {
        'clarification',
        'uncertainty',
        'proposal',
        'confirm',
        'inform',
        'escalate',
    }
)

_COMMUNICATE_DESCRIPTION = (
    'Interact with the user. Pick the intent that matches what you need:\n'
    '  - clarification: ask a question, optionally with multiple-choice options.\n'
    '  - uncertainty: flag that you are not confident; describe concerns and what would help.\n'
    '  - proposal: offer 2+ alternative approaches with optional descriptions and a recommended pick.\n'
    '  - confirm: require explicit user OK before a destructive or irreversible action; auto-denies on timeout.\n'
    '  - inform: share a non-blocking status update; the user can read it but the turn continues.\n'
    '  - escalate: hand off to the human after repeated failures; include what you tried and what help you need.'
)


def create_communicate_tool() -> ChatCompletionToolParam:
    """Create the unified communication tool."""
    return create_tool_definition(
        name=COMMUNICATE_TOOL_NAME,
        description=_COMMUNICATE_DESCRIPTION,
        properties={
            'intent': {
                'type': 'string',
                'enum': sorted(_VALID_INTENTS),
                'description': 'The specific reason for communication.',
            },
            'message': {
                'type': 'string',
                'description': 'The question, reason, or explanation you want to deliver.',
            },
            'options': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'label': {
                            'type': 'string',
                            'description': 'Short label for this option (shown in the UI).',
                        },
                        'description': {
                            'type': 'string',
                            'description': 'Optional one-line explanation of tradeoffs.',
                        },
                    },
                    'required': ['label'],
                },
                'description': (
                    '(Optional) For clarification/proposal/confirm: a list of option objects. '
                    'Each option needs a "label"; "description" is optional. '
                    'For confirm, use exactly two options: the positive and the negative.'
                ),
            },
            'recommended': {
                'type': 'integer',
                'minimum': 0,
                'description': (
                    '(Optional, proposal only) Zero-based index of the option you recommend. '
                    'The UI pre-selects it so the user can accept with one Enter.'
                ),
            },
            'uncertainty_level': {
                'type': 'number',
                'minimum': 0.0,
                'maximum': 1.0,
                'description': (
                    '(Optional, uncertainty only) Your confidence in the current approach, '
                    'where 1.0 = fully confident and 0.0 = no idea. Defaults to 0.5.'
                ),
            },
            'specific_help_needed': {
                'type': 'string',
                'description': (
                    '(Optional, escalate only) What concrete input or decision would unblock you. '
                    'Shown verbatim to the user.'
                ),
            },
            'attempts': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'action': {
                            'type': 'string',
                            'description': 'Short label of the attempt (e.g. "rg --files").',
                        },
                        'result': {
                            'type': 'string',
                            'description': 'What happened (error, exit code, observation).',
                        },
                    },
                    'required': ['action'],
                },
                'description': (
                    '(Optional, escalate only) Structured list of approaches already tried. '
                    'Each entry has an "action" and optional "result".'
                ),
            },
            'context': {
                'type': 'string',
                'description': '(Optional) Background on what you tried or why you are asking.',
            },
            'thought': {
                'type': 'string',
                'description': 'Your internal reasoning. Optional for this tool.',
            },
        },
        required=['intent', 'message'],
    )
