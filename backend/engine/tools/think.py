"""Definition of the lightweight reasoning tool for Orchestrator agents."""

from backend.engine.tools.common import create_tool_definition
from backend.engine.contracts import ChatCompletionToolParam

_THINK_DESCRIPTION = (
    "Log a reasoning step without taking action. Use for brainstorming fixes, "
    "planning refactors, debugging hypotheses, or weighing tradeoffs before committing to an approach."
)


def create_think_tool() -> ChatCompletionToolParam:
    """Create the think tool for the Orchestrator agent."""
    return create_tool_definition(
        name="think",
        description=_THINK_DESCRIPTION,
        properties={
            "thought": {
                "type": "string",
                "description": "The thought to log.",
            }
        },
        required=["thought"],
    )
