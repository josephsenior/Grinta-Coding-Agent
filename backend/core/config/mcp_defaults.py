"""Default user-managed MCP servers (settings.json) vs internal bundled backends."""

from __future__ import annotations

from typing import Any

# Operator-facing defaults seeded into settings.json (editable / deletable in TUI).
DEFAULT_USER_MCP_SERVERS: list[dict[str, Any]] = [
    {
        'name': 'shadcn',
        'type': 'stdio',
        'command': 'npx',
        'args': [
            '-y',
            '@jpisnice/shadcn-ui-mcp-server',
            '--framework',
            'react',
        ],
        'enabled': True,
        'usage_hint': (
            'shadcn/ui React components: variants, props, CLI install, and registry lookups.'
        ),
    },
    {
        'name': 'github',
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '@modelcontextprotocol/server-github'],
        'enabled': True,
        'usage_hint': (
            'GitHub API for repos, issues, PRs, metadata. Set '
            '**GITHUB_PERSONAL_ACCESS_TOKEN** in `.env` (classic or fine-grained PAT '
            'with repo scope). Bad credentials = expired/revoked token or missing scopes.'
        ),
        'env': {
            'GITHUB_PERSONAL_ACCESS_TOKEN': '',
        },
    },
    {
        'name': 'rigour',
        'type': 'stdio',
        'command': 'npx',
        'args': ['-y', '@rigour-labs/mcp'],
        'enabled': True,
        'usage_hint': (
            '**Rigour** — local code governance / quality gates. No API key. If the '
            'project has no `rigour.yml`, Grinta creates a **minimal** one so the '
            'server can start (upstream `npx rigour init` is broken on npm). Prefer '
            '**`rigour_check`** / **`rigour_status`** after substantive edits. '
            '**`RIGOUR_CWD`** is the open workspace.'
        ),
        'env': {
            'RIGOUR_CWD': '${PROJECT_ROOT}',
        },
    },
]


def default_user_mcp_config() -> dict[str, Any]:
    """Return a copy of the default ``mcp_config`` block for settings.json."""
    return {
        'enabled': True,
        'servers': [dict(server) for server in DEFAULT_USER_MCP_SERVERS],
    }
