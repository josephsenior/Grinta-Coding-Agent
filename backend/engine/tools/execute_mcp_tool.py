"""MCP Gateway Tool — single proxy for all MCP tool calls.

Instead of injecting 50+ individual MCP tool schemas into the LLM context,
we expose ONE gateway tool. The model sees MCP tool names/descriptions in
the system prompt and routes calls through this gateway.

The description is built dynamically from the live agent config so the
model never sees a "see <MCP_TOOLS> section" pointer to a section that
isn't there, and never gets told to use a native facade that the
operator has disabled.
"""

from __future__ import annotations

from typing import Any

from backend.core.tools.tool_names import CALL_MCP_TOOL_NAME


def _native_facade_hint(config: Any) -> str:
    """Return the "use these native tools" sentence, gated on config flags.

    Returns an empty string when the agent has not enabled the relevant
    native capabilities — never tell the model to call a disabled tool.
    """
    enabled_web = bool(getattr(config, 'enable_web', True))
    enabled_docs = bool(getattr(config, 'enable_docs', True))
    parts: list[str] = []
    if enabled_docs:
        parts.append('`docs_resolve` / `docs_query`')
    if enabled_web:
        parts.append('`web_search` / `web_fetch`')
    if not parts:
        return ''
    if len(parts) == 1:
        return f' For bundled capabilities use {parts[0]} — not this gateway.'
    head = ', '.join(parts[:-1])
    return f' For bundled capabilities use {head} and {parts[-1]} — not this gateway.'


def create_execute_mcp_tool_tool(config: Any = None) -> dict:
    """Create the MCP gateway tool definition.

    Args:
        config: Optional agent config used to (a) render a clear
            "no MCP connected" message when the catalogue is empty and
            (b) gate the "use native facade" sentence on the relevant
            ``enable_*`` flags. When ``None``, the gateway uses a
            neutral description (matches the pre-fix behavior for unit
            tests that don't pass a config).
    """
    has_mcp_catalog = False
    if config is not None:
        mcp_status = getattr(config, 'mcp_capability_status', None)
        if isinstance(mcp_status, dict):
            try:
                has_mcp_catalog = int(
                    mcp_status.get('remote_tool_param_count') or 0
                ) > 0
            except (TypeError, ValueError):
                has_mcp_catalog = False

    if config is not None and not has_mcp_catalog:
        description = (
            'No external MCP servers are connected in this session. '
            'Enable one in **Settings → MCP Servers**; the catalogue appears '
            'under the per-turn <MCP_TOOLS> section once connected.'
            f'{_native_facade_hint(config)}'
        )
    else:
        description = (
            'Call any external MCP tool by name. '
            'See the <MCP_TOOLS> section for names and descriptions. '
            'Put **every** tool-specific parameter inside the ``arguments`` '
            'object using the exact keys from that tool schema (camelCase as '
            'given). Do not place parameter keys at the top level next to '
            '``tool_name`` — that yields empty args and MCP validation errors '
            '(-32602).'
            f'{_native_facade_hint(config) if config is not None else ""}'
        )

    return {
        'type': 'function',
        'function': {
            'name': CALL_MCP_TOOL_NAME,
            'description': description,
            'parameters': {
                'type': 'object',
                'properties': {
                    'tool_name': {
                        'type': 'string',
                        'description': 'The exact name of the MCP tool to call (from the <MCP_TOOLS> list).',
                    },
                    'arguments': {
                        'type': 'object',
                        'description': (
                            'Required. Object of argument names to values exactly as the MCP tool schema defines.'
                        ),
                    },
                },
                'required': ['tool_name', 'arguments'],
            },
        },
    }
