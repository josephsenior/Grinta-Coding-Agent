"""Definition of the Orchestrator finish tool for signalling task completion."""

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
    "\nOptionally provide structured completion metadata via the other fields."
)


def create_finish_tool() -> ChatCompletionToolParam:
    """Create the finish tool for the Orchestrator agent."""
    return create_tool_definition(
        name=FINISH_TOOL_NAME,
        description=_FINISH_DESCRIPTION,
        properties={
            "message": {
                "type": "string",
                "description": "Final message to send to the user",
            },
            "completed": {
                "type": "array",
                "description": "List of tasks or steps that were completed during this session",
                "items": {"type": "string"},
            },
            "blocked_by": {
                "type": "string",
                "description": (
                    "If you were unable to fully complete the task, describe what is "
                    "blocking progress (missing info, permissions, external dependency, etc.)"
                ),
            },
            "next_steps": {
                "type": "array",
                "description": "Concrete next steps the user should take to continue",
                "items": {"type": "string"},
            },
            "lessons_learned": {
                "type": "string",
                "description": (
                    "Internal reflection on what you learned during this task. "
                    "Identify recurring patterns, mistakes you made, or verified "
                    "solutions that should be remembered for future sessions."
                ),
            },
        },
        required=["message"],
    )
