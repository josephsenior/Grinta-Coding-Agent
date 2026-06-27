# MCP Examples

Configuration examples and server setup live in **[mcp/integration_examples.md](mcp/integration_examples.md)**.

For how MCP fits alongside native tools and LLM providers, see [INFERENCE_AND_INTEGRATIONS.md](INFERENCE_AND_INTEGRATIONS.md). For user-facing MCP setup in `settings.json`, see [SETTINGS.md](SETTINGS.md) and [PLUGIN_GUIDE.md](PLUGIN_GUIDE.md).

## Integration tiers

| Tier | Examples | How the model sees them |
|------|----------|-------------------------|
| Native core tools | read, edit, bash, grep | Always in the tool schema |
| Native facades | web_search, web_fetch | One stable tool name; MCP backends hidden |
| MCP extensions | GitHub, Context7, Exa, Rigour | `call_mcp_tool` gateway + prompt catalog |
| Runtime protocols | browser, LSP, debugger | Native tools; not under `integrations/` |
