"""Client-side MCP tool proxy model."""

from pydantic import ConfigDict

from mcp.types import Tool


class MCPClientTool(Tool):
    """Represents a tool proxy that can be called on the MCP server from the client side.

    This version doesn't store a session reference, as sessions are created on-demand
    by the MCPClient for each operation.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def to_param(self) -> dict:
        """Convert tool to function call format.

        When the MCP tool exposes an ``outputSchema`` (or ``annotations``
        with ``output_description``), the information is appended to the
        tool's description so the LLM knows what to expect in the response.
        """
        description = self.description or ''

        # Surface output schema metadata if provided by the MCP server.
        output_schema = getattr(self, 'outputSchema', None)
        annotations = getattr(self, 'annotations', None)
        output_hint = ''
        if output_schema and isinstance(output_schema, dict):
            # Compact JSON schema summary
            output_hint = f'\n\nOutput schema: {output_schema}'
        elif annotations and isinstance(annotations, dict):
            odesc = annotations.get('output_description')
            if odesc:
                output_hint = f'\n\nExpected output: {odesc}'

        return {
            'type': 'function',
            'function': {
                'name': self.name,
                'description': description + output_hint,
                'parameters': self.inputSchema,
            },
        }
