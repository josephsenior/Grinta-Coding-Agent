# MCP Examples

This page provides lightweight examples of MCP usage patterns in Grinta.

For how MCP fits alongside native tools and LLM providers, see [INFERENCE_AND_INTEGRATIONS.md](INFERENCE_AND_INTEGRATIONS.md).

## Integration tiers

| Tier | Examples | How the model sees them |
|------|----------|-------------------------|
| Native core tools | read, edit, bash, grep | Always in the tool schema |
| Native facades | web_search, web_fetch | One stable tool name; MCP backends hidden |
| MCP extensions | GitHub, Context7, Exa, Rigour | `call_mcp_tool` gateway + prompt catalog |
| Runtime protocols | browser, LSP, debugger | Native tools; not under `integrations/` |

## Example: read-only docs lookup

- Use an MCP docs server to resolve current API signatures.
- Keep outputs scoped and summarize findings in the session.

## Example: issue/PR automation

- Use a GitHub MCP server to fetch issue metadata.
- Avoid mutation operations unless explicitly requested by the operator.

## Example: external service integration

- Authenticate with least privilege.
- Validate tool schemas before invocation.
- Record enough context in logs for troubleshooting without exposing secrets.
