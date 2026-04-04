"""blackboard tool — read/write shared state when running as a delegated worker.

Only available when this agent is a sub-agent and delegate_task_blackboard_enabled
is True. The planner adds this tool when agent.blackboard is set.
"""

from __future__ import annotations

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import create_tool_definition
from backend.ledger.action.agent import BlackboardAction

BLACKBOARD_TOOL_NAME = 'shared_task_board'

_DESCRIPTION = (
    'Read or write the shared blackboard. When running sub-agents (via delegate_task) in the background, '
    'use this tool to check their live status or publish shared data. '
    "Use 'get' with key='all' or no key to see everything; 'set' to publish a key-value; "
    "'keys' to list keys. Values are strings. Use this to coordinate between the orchestrator and background workers."
)


def create_blackboard_tool() -> ChatCompletionToolParam:
    """Create the blackboard tool definition."""
    return create_tool_definition(
        name=BLACKBOARD_TOOL_NAME,
        description=_DESCRIPTION,
        properties={
            'command': {
                'type': 'string',
                'enum': ['get', 'set', 'keys'],
                'description': "get: read one key or 'all'. set: write key=value. keys: list keys.",
            },
            'key': {
                'type': 'string',
                'description': "Key to get/set. For get, use 'all' or omit for full dump.",
            },
            'value': {
                'type': 'string',
                'description': "Value for 'set' command.",
            },
        },
        required=['command'],
    )


def build_blackboard_action(arguments: dict) -> BlackboardAction:
    """Build BlackboardAction from tool arguments."""
    command = (arguments.get('command') or 'get').lower()
    key = (arguments.get('key') or '').strip()
    value = (arguments.get('value') or '').strip()
    return BlackboardAction(command=command, key=key, value=value)
