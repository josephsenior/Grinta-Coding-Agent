# Plugin Guide

Grinta supports extensibility through MCP-compatible tooling and runtime integrations.

## Current guidance

- Prefer MCP servers for external tool integrations.
- Keep plugin/tool behavior deterministic and auditable.
- Document required environment variables and network permissions for each plugin.

## Authoring checklist

1. Define the plugin/tool contract clearly (inputs, outputs, failure modes).
2. Add tests for normal and failure paths.
3. Add security notes for command/network/file access.
4. Document setup and usage in `docs/`.

For examples, see [MCP examples](MCP_EXAMPLES.md).
