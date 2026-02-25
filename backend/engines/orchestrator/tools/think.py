"""Definition of the lightweight reasoning tool for Orchestrator agents."""

from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.engines.orchestrator.contracts import ChatCompletionToolParam

_THINK_DESCRIPTION = (
    "Use the tool to think about something. It will not obtain new information or make any changes to the repository, but just log the thought. Use it when complex reasoning or brainstorming is needed.\n\n"
    "Common use cases:\n"
    "1. When exploring a repository and discovering the source of a bug, call this tool to brainstorm several unique ways of fixing the bug, and assess which change(s) are likely to be simplest and most effective.\n"
    "2. After receiving test results, use this tool to brainstorm ways to fix failing tests.\n"
    "3. When planning a complex refactoring, use this tool to outline different approaches and their tradeoffs.\n"
    "4. When designing a new feature, use this tool to think through architecture decisions and implementation details.\n"
    "5. When debugging a complex issue, use this tool to organize your thoughts and hypotheses.\n\n"
    "The tool simply logs your thought process for better transparency and does not execute any code or make changes."
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
