# MCP Integration Examples

Grinta supports the Model Context Protocol (MCP) to connect agents with external tools and data sources.

## 1. Configuring MCP Servers

MCP servers are configured in `settings.json` under `mcp_config.servers` (see [SETTINGS.md](../SETTINGS.md)).

### Example: Filesystem Server

```json
{
  "mcp_config": {
    "servers": [
      {
        "name": "filesystem",
        "command": "npx",
        "args": [
          "-y",
          "@modelcontextprotocol/server-filesystem",
          "/path/to/directory"
        ]
      }
    ]
  }
}
```

### Example: GitHub Server

```json
{
  "mcp_config": {
    "servers": [
      {
        "name": "github",
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-github"],
        "env": {
          "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"
        }
      }
    ]
  }
}
```

Set `GITHUB_TOKEN` (or the provider-specific env var) in your environment (for example `.env`).

## 2. Using MCP Tools in Agents

Once an MCP server is configured, its tools are automatically available to the agent.

The agent can call tools like:

- `filesystem_read_file`
- `filesystem_list_directory`
- `github_search_repositories`
