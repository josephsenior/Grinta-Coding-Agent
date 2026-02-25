"""Tool for requesting conversation condensation within the Orchestrator agent."""

from __future__ import annotations

from backend.engines.orchestrator.tools.common import create_tool_definition
from backend.engines.orchestrator.contracts import ChatCompletionToolParam

_CONDENSATION_REQUEST_DESCRIPTION = "Request a condensation of the conversation history when the context becomes too long or when you need to focus on the most relevant information."


def create_condensation_request_tool() -> ChatCompletionToolParam:
    """Create the condensation request tool for the Orchestrator agent."""
    return create_tool_definition(
        name="request_condensation",
        description=_CONDENSATION_REQUEST_DESCRIPTION,
        properties={},
        required=[],
    )
