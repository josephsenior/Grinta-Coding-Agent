# MCP Examples

This page provides lightweight examples of MCP usage patterns in Grinta.

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
