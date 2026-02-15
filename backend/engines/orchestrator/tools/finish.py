"""Definition of the CodeAct finish tool for signalling task completion."""

from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.engines.orchestrator.contracts import ChatCompletionToolParam
from backend.llm.tool_names import FINISH_TOOL_NAME

_FINISH_DESCRIPTION = (
    "Signals the completion of the current task or conversation.\n\nUse this tool when:\n"
    "- You have successfully completed the user's requested task\n"
    "- You cannot proceed further due to technical limitations or missing information\n\n"
    "The message should include:\n"
    "- A clear summary of actions taken and their results\n"
    "- Any next steps for the user\n"
    "- Explanation if you're unable to complete the task\n"
    "- Any follow-up questions if more information is needed\n"
)


def create_finish_tool() -> ChatCompletionToolParam:
    """Create the finish tool for the CodeAct agent."""
    return create_tool_definition(
        name=FINISH_TOOL_NAME,
        description=_FINISH_DESCRIPTION,
        properties={
            "message": {
                "type": "string",
                "description": "Final message to send to the user",
            }
        },
        required=["message"],
    )
