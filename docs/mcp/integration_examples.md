# MCP Integration Examples

Grinta supports the Model Context Protocol (MCP) to connect agents with external tools and data sources.

## 1. Configuring MCP Servers

MCP servers are configured in `agent.yaml` under the `mcp_servers` section.

### Example: Filesystem Server

```yaml
mcp_servers:
  filesystem:
    command: "npx"
    args:
      - "-y"
      - "@modelcontextprotocol/server-filesystem"
      - "/path/to/directory"
```

### Example: GitHub Server

```yaml
mcp_servers:
  github:
    command: "npx"
    args:
      - "-y"
      - "@modelcontextprotocol/server-github"
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: "${GITHUB_TOKEN}"
```

## 2. Using MCP Tools in Agents

Once an MCP server is configured, its tools are automatically available to the agent.

The agent can call tools like:

- `filesystem_read_file`
- `filesystem_list_directory`
- `github_search_repositories`

## 3. Creating a Custom MCP Server

You can create your own MCP server using the Python SDK.

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weather")

@mcp.tool()
def get_weather(city: str) -> str:
    """Get the weather for a city."""
    return f"The weather in {city} is sunny."

if __name__ == "__main__":
    mcp.run()
```

Add it to `agent.yaml`:

```yaml
mcp_servers:
  weather:
    command: "python"
    args:
      - "path/to/weather_server.py"
```
