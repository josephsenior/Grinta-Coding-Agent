"""Renderer for the MCP catalog and permissions block."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.engine.prompts.section_renderers._interaction import (
    _render_interaction_tail,
)
from backend.engine.prompts.section_renderers._permissions import (
    _render_permissions,
)


def _append_mcp_connected_catalog_sections(
    parts: list[str],
    mcp_tool_names: list[str],
    mcp_tool_descriptions: dict[str, str],
    mcp_server_hints: list[dict[str, str]],
    mode: str,
) -> None:
    from backend.core.interaction_modes import is_plan_mode

    total = len(mcp_tool_names)
    mode_rule = (
        'Mode rules override MCP capability suggestions.'
        if not is_plan_mode(mode)
        else 'Mode rules override MCP capability suggestions. Plan mode remains codebase read-only; task tracking is allowed.'
    )
    parts.extend(
        (
            '<CURATED_MCP_CAPABILITIES>\n'
            'Grinta has a curated first-party MCP capability layer. Think in capabilities first, then call the matching MCP tool by its exact listed name.\n\n'
            '- Web Search: discover external/current information, official pages, unknown errors, release notes, or references.\n'
            '- Fetch: read a specific URL/page. Web Search finds pages; Fetch reads pages.\n'
            '- GitHub: inspect repositories, issues, PRs, commits, releases, and upstream context. Remote write actions require explicit user intent.\n'
            '- Docs / Context7: use for reliable library/framework documentation when the library is known.\n'
            '- UI / shadcn: use only for React/Tailwind/shadcn component work.\n'
            '- Quality Gates: use for tests, lint, typecheck, formatting checks, and finish-readiness validation.\n\n'
            f'{mode_rule}\n'
            '</CURATED_MCP_CAPABILITIES>',
            f'🔌 **External MCP tools** ({total}): use **`call_mcp_tool(tool_name="...", arguments={{...}})`** '
            f'— argument shapes match the registered tool schema.',
            '**Tool-name discipline (critical):** Pass each tool name to '
            '`call_mcp_tool(tool_name=...)` **exactly as listed below** — the names '
            'are already flat. Do **not** add `server:`, `server/`, `server.`, '
            '`server__` or any other prefix; those are not part of the name and '
            'will fail. If a name you want is not in this list, that tool is '
            'not available in this session — pick a different tool or an '
            'alternative approach. Do not guess.',
        )
    )
    for name in mcp_tool_names:
        parts.append(f'- `{name}`: {mcp_tool_descriptions[name]}')

    if mcp_server_hints:
        parts.extend(
            (
                '',
                '<MCP_SERVER_HINTS>',
                '**Configured MCP servers (when to use each — from your MCP settings):**',
            )
        )
        for row in mcp_server_hints:
            parts.append(f'- **`{row["server"]}`:** {row["hint"]}')
        parts.append('</MCP_SERVER_HINTS>')

    parts.extend(('', '<MCP_WHEN_TO_USE>', '**Discipline (MCP):**'))
    if mcp_server_hints:
        parts.append(
            'Follow **Configured MCP servers** above for *when* to prefer each server; '
            "match the user's task to those hints, then pick the concrete tool name from the list "
            "and each tool's description."
        )
    else:
        parts.append(
            "Infer *when* to call MCP from each tool's **name** and **description** in the list above "
            '(and avoid training-memory guesses for vendor-specific or version-specific facts—use a tool when one fits).'
        )
    parts.extend(
        (
            'Prefer **`call_mcp_tool`** over shell one-offs when an MCP tool covers the need. '
            'If asked what you can do or which models/tools you have, answer from **this** tool list, '
            '**MCP server hints** (if any), and your configured model id—**not** generic "no web / no docs" tropes.',
            'On failure, MCP results carry a `category` field. Use it to pick the next move: '
            '`bad_args` → fix arguments and retry once; '
            '`timeout` → narrow the scope and retry; '
            '`tool_bug` → switch to a different tool; '
            '`env` → fall back to a non-MCP tool (e.g. terminal); '
            '`not_found` → pick a tool name from the list above.',
            '</MCP_WHEN_TO_USE>',
        )
    )


def _mcp_tail_render_kwargs(
    render_partial: Callable[..., str],
    config: Any,
    mode: str | None = None,
) -> str:
    return _render_interaction_tail(render_partial, config, mode)


def _render_mcp_and_permissions(
    render_partial: Callable[..., str],
    mcp_tool_names: list[str],
    mcp_tool_descriptions: dict[str, str],
    mcp_server_hints: list[dict[str, str]],
    config: Any,
) -> str:
    from backend.core.interaction_modes import normalize_interaction_mode

    mode = normalize_interaction_mode(getattr(config, 'mode', 'agent'))
    parts: list[str] = ['<MCP_TOOLS>']

    if mcp_tool_names:
        _append_mcp_connected_catalog_sections(
            parts,
            mcp_tool_names,
            mcp_tool_descriptions,
            mcp_server_hints,
            mode,
        )
    else:
        parts.append('No external MCP tools connected.')
    parts.append('</MCP_TOOLS>')

    if getattr(config, 'enable_permissions', False):
        perm = getattr(config, 'permissions', None)
        if perm is not None:
            parts.extend(('', _render_permissions(config, perm)))

    return '\n'.join(parts)
