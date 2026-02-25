"""Data models describing tool call metadata within events."""

from typing import Any

from pydantic import PrivateAttr

from backend.core.schemas.metadata import ToolCallMetadataSchema

from .model_response_lite import ModelResponseLite


def build_tool_call_metadata(
    *,
    function_name: str,
    tool_call_id: str,
    response_obj: Any,
    total_calls_in_response: int,
) -> "ToolCallMetadata":
    """Unified helper to construct ToolCallMetadata across agent implementations.

    Builds a lightweight stable representation of the model response.

    All callers (Orchestrator, ReadOnly, Loc agents) should use this to ensure
    consistent metadata shape and avoid divergence in test expectations.
    """
    return ToolCallMetadata.from_sdk(
        function_name=function_name,
        tool_call_id=tool_call_id,
        response_obj=response_obj,
        total_calls_in_response=total_calls_in_response,
    )


class ToolCallMetadata(ToolCallMetadataSchema):
    """Metadata for LLM tool/function calls.

    Attributes:
        function_name: Name of the function called
        tool_call_id: Unique ID for this tool call
        model_response: Complete LLM response containing the tool call
        total_calls_in_response: Number of tool calls in the response

    """

    # Keep raw SDK response out of the public schema
    _raw_response: Any = PrivateAttr(default=None)

    @classmethod
    def from_sdk(
        cls,
        *,
        function_name: str,
        tool_call_id: str,
        response_obj: Any,
        total_calls_in_response: int,
    ) -> "ToolCallMetadata":
        lite = ModelResponseLite.from_sdk(response_obj)
        md = cls(
            function_name=function_name,
            tool_call_id=tool_call_id,
            model_response=lite.model_dump(),
            total_calls_in_response=total_calls_in_response,
        )
        md._raw_response = response_obj
        return md
