# Integrations

This package holds **MCP (Model Context Protocol) adapters** — external tools discovered at runtime and invoked through the `call_mcp_tool` gateway.

## What lives here

```
integrations/mcp/
  client.py          FastMCP client (stdio / SSE / streamable HTTP)
  mcp_utils.py       Bootstrap, connect, call_tool_mcp
  tool.py            MCP tool schema → OpenAI function shape
  wrappers.py        Synthetic wrappers (web fetch router, cache helpers)
  cache.py           MCP result cache
```

Bundled server defaults: [`backend/execution/mcp/config.json`](../execution/mcp/config.json).

## What does *not* live here

| Capability | Package |
|------------|---------|
| Browser automation | `backend/execution/browser/` |
| LSP queries | `backend/engine/tools/lsp_query.py` |
| Debugger (DAP) | `backend/execution/dap/` |
| Native web search/fetch facades | `backend/engine/tools/web_tools.py` |
| LLM providers | `backend/inference/` |

See [docs/INFERENCE_AND_INTEGRATIONS.md](../../docs/INFERENCE_AND_INTEGRATIONS.md) for the full map.

## Philosophy

MCP servers are **curated**, not an open plugin marketplace. Native core tools stay in the LLM schema; MCP tools appear in the system prompt catalog and route through one gateway. See [docs/journey/43-the-plugin-boundary.md](../../docs/journey/43-the-plugin-boundary.md).
