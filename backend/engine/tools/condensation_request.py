"""Tool for requesting conversation condensation within the Orchestrator agent."""

from __future__ import annotations

from backend.engine.contracts import ChatCompletionToolParam
from backend.engine.tools.common import create_tool_definition

_CONDENSATION_REQUEST_DESCRIPTION = 'Request a condensation of the conversation history when the context becomes too long or when you need to focus on the most relevant information.'


def create_summarize_context_tool() -> ChatCompletionToolParam:
    """Create the summarize context tool for the Orchestrator agent."""
    return create_tool_definition(
        name='summarize_context',
        description=_CONDENSATION_REQUEST_DESCRIPTION,
        properties={},
        required=[],
    )
