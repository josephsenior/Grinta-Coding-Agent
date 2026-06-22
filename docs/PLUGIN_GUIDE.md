# Plugin Guide

Grinta supports extensibility through MCP-compatible tooling and runtime integrations.

## Table of Contents

1. Extension Points
2. MCP Integration
3. Authoring Guidelines
4. Security Considerations

---

## Extension Points

Grinta provides two primary extension mechanisms:

| Mechanism | Use When |
| --- | --- |
| **MCP Servers** | You need external tools, APIs, or services (e.g., GitHub, databases, search) |
| **Runtime integrations** | You need to modify core agent behavior ( rarer ) |

Prefer MCP servers for external tool integrations — they're the standard path and keep Grinta's execution model clean.

---

## MCP Integration

### Basic setup

1. Configure MCP server in `settings.json`:

```json
{
  "mcp_config": {
    "servers": [
      {
        "name": "github",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {
          "GITHUB_TOKEN": "${GITHUB_TOKEN}"
        }
      }
    ]
  }
}
```

2. The server becomes available as tools within Grinta's session.

### Best practices

- **Keep tool behavior deterministic** — avoid non-idempotent operations unless explicitly requested.
- **Document required environment variables** — users need to know what secrets/keys to provide.
- **Validate tool schemas** — before invoking, confirm the tool contract matches expectations.
- **Scope permissions narrowly** — request only the capabilities your plugin needs.

For examples, see [MCP examples](MCP_EXAMPLES.md).

---

## Authoring Guidelines

### Plugin contract

For each plugin, define:

1. **Inputs** — what parameters the tool accepts
2. **Outputs** — what the tool returns (structured JSON preferred)
3. **Failure modes** — what errors can occur and when
4. **Dependencies** — required env vars, network access, external services

### Checklist

- [ ] Define the plugin/tool contract (inputs, outputs, failure modes)
- [ ] Add tests for normal and failure paths
- [ ] Document required environment variables and network permissions
- [ ] Add security notes for command/network/file access
- [ ] Document setup and usage in `docs/`
- [ ] Verify the plugin works with Grinta's current MCP client

---

## Security Considerations

- Grinta executes locally — plugins run with your user privileges
- Audit logs record every plugin invocation (see `~/.grinta/workspaces/<id>/storage/<session>/audit/`)
- Use least-privilege authentication (scoped tokens, minimal IAM permissions)
- Disable network-using commands when working offline (`security.allow_network_commands: false` in `settings.json`)

For security baseline, see [SECURITY_CHECKLIST.md](SECURITY_CHECKLIST.md).
