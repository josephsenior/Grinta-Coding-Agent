# MCP integration

## Bootstrap vs runtime clients

Grinta uses **two MCP client lifecycles** on purpose:

1. **Bootstrap (probe)** — At session start, `add_mcp_tools_to_agent` connects to each configured server, lists tools, builds metadata for the prompt catalog, then **disconnects** probe clients. This keeps startup predictable when servers are flaky.
2. **Runtime (persistent)** — On the first `MCPAction`, `action_execution_server` creates **persistent** clients that stay open for the session. Subsequent tool calls reuse them.

Both paths share connection settings from [`mcp_config.py`](../../core/config/mcp_config.py) and bundled defaults in [`execution/mcp/config.json`](../../execution/mcp/config.json).

## Call flow

```
LLM → call_mcp_tool (gateway) → MCPAction → runtime → call_tool_mcp → MCP server
```

Tool schemas are **not** injected individually into the LLM tool list. Descriptions live in `agent.mcp_tools` and the system prompt MCP section.

## Extension points

- **Wrappers** — [`wrappers.py`](wrappers.py) intercept specific MCP tool names (native web fetch router, cached component lookups).
- **Aliases** — [`mcp_tool_aliases.py`](mcp_tool_aliases.py) rename tools that collide with native names.
- **Playbooks** — can declare additional MCP servers merged at bootstrap.
