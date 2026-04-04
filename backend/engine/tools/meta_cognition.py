"""Meta-cognition tools enabling the LLM to express uncertainty and seek guidance.

These tools allow the LLM to interact with the user or system to express doubt,
ask for clarification, propose options, or escalate when stuck.
"""

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import create_tool_definition

# Single unified tool name
COMMUNICATE_TOOL_NAME = 'communicate_with_user'

_COMMUNICATE_DESCRIPTION = (
    'Interact with the user: ask for clarification, flag uncertainty, '
    'propose options before risky actions, or escalate when stuck.'
)


def create_communicate_tool() -> ChatCompletionToolParam:
    """Create the unified communication tool."""
    return create_tool_definition(
        name=COMMUNICATE_TOOL_NAME,
        description=_COMMUNICATE_DESCRIPTION,
        properties={
            'intent': {
                'type': 'string',
                'enum': ['clarification', 'uncertainty', 'proposal', 'escalate'],
                'description': 'The specific reason for communication.',
            },
            'message': {
                'type': 'string',
                'description': 'The question, reason, or explanation you want to deliver.',
            },
            'options': {
                'type': 'array',
                'items': {'type': 'string'},
                'description': '(Optional) For clarification or proposals: A list of options to present.',
            },
            'context': {
                'type': 'string',
                'description': '(Optional) Context on what you tried or why you are asking.',
            },
            'thought': {
                'type': 'string',
                'description': 'Your internal reasoning.',
            },
        },
        required=['intent', 'message', 'thought'],
    )
