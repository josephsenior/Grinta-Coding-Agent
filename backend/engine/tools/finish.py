"""Definition of the Orchestrator finish tool for signalling task completion."""

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import create_tool_definition
from backend.inference.tool_names import FINISH_TOOL_NAME

_FINISH_DESCRIPTION = (
    'Signal task completion. Include a summary of actions taken and results. '
    'Use only when the task is fully done. '
    'To report a blocker or ask the user for input, use communicate_with_user instead.'
)


def create_finish_tool() -> ChatCompletionToolParam:
    """Create the finish tool for the Orchestrator agent."""
    return create_tool_definition(
        name=FINISH_TOOL_NAME,
        description=_FINISH_DESCRIPTION,
        properties={
            'message': {
                'type': 'string',
                'description': 'Final message to send to the user',
            },
            'completed': {
                'type': 'array',
                'description': 'List of tasks or steps that were completed during this session',
                'items': {'type': 'string'},
            },
            'blocked_by': {
                'type': 'string',
                'description': (
                    'If you were unable to fully complete the task, describe what is '
                    'blocking progress (missing info, permissions, external dependency, etc.)'
                ),
            },
            'next_steps': {
                'type': 'array',
                'description': 'Concrete next steps the user should take to continue',
                'items': {'type': 'string'},
            },
            'lessons_learned': {
                'type': 'string',
                'description': (
                    'Internal reflection on what you learned during this task. '
                    'Identify recurring patterns, mistakes you made, or verified '
                    'solutions that should be remembered for future sessions.'
                ),
            },
        },
        required=['message'],
    )
