"""Prompt section renderers shared by the system prompt builder.

This package was split from a single ``section_renderers.py`` module to keep
each template partial (e.g. ``system_partial_00_routing.md``) in its own
file. The submodules group by concern:

- :mod:`_common`       — token counting, OS/terminal helpers
- :mod:`_env_hints`    — platform-, shell-, and LSP-aware hint strings
- :mod:`_capabilities` — system capabilities block + runtime detection
- :mod:`_routing`      — routing partial
- :mod:`_autonomy`     — autonomy partial + its inner ``_build_*`` blocks
- :mod:`_tools`        — tool reference partial
- :mod:`_interaction`  — interaction tail partial + response style
- :mod:`_critical`     — critical-execution partial
- :mod:`_examples`     — worked-examples partial
- :mod:`_security`     — security risk policy block
- :mod:`_permissions`  — ``<PERMISSIONS>`` block
- :mod:`_mcp`          — MCP catalog + permissions

All public/private names are re-exported below so existing import paths
(``from backend.engine.prompts.section_renderers import _render_routing``)
continue to work unchanged.
"""

from __future__ import annotations

from backend.engine.prompts.section_renderers._autonomy import (
    _build_autonomy_block,
    _build_context_discipline_section,
    _build_risk_preview,
    _build_when_to_use_context,
    _render_autonomy,
)
from backend.engine.prompts.section_renderers._capabilities import (
    _render_runtime_detection_lines,
    _render_system_capabilities,
)
from backend.engine.prompts.section_renderers._common import (
    _choose,
    _count_section_tokens,
    _resolve_terminal_command_tool,
)
from backend.engine.prompts.section_renderers._critical import _render_critical
from backend.engine.prompts.section_renderers._env_hints import (
    _debugger_available,
    _explore_hint,
    _lsp_available,
    _path_uncertainty_hint,
    _repo_discovery_contract,
    _routing_memory_tool_placeholders,
)
from backend.engine.prompts.section_renderers._examples import _render_examples
from backend.engine.prompts.section_renderers._interaction import (
    _build_response_style_block,
    _render_interaction_tail,
)
from backend.engine.prompts.section_renderers._mcp import (
    _append_mcp_connected_catalog_sections,
    _mcp_tail_render_kwargs,
    _render_mcp_and_permissions,
)
from backend.engine.prompts.section_renderers._permissions import (
    _permission_git_summary,
    _permission_shell_network_limits,
    _render_permissions,
)
from backend.engine.prompts.section_renderers._routing import _render_routing
from backend.engine.prompts.section_renderers._security import _render_security
from backend.engine.prompts.section_renderers._tools import _render_tool_reference

__all__ = [
    '_append_mcp_connected_catalog_sections',
    '_build_autonomy_block',
    '_build_context_discipline_section',
    '_build_response_style_block',
    '_build_risk_preview',
    '_build_when_to_use_context',
    '_choose',
    '_count_section_tokens',
    '_debugger_available',
    '_explore_hint',
    '_lsp_available',
    '_mcp_tail_render_kwargs',
    '_path_uncertainty_hint',
    '_permission_git_summary',
    '_permission_shell_network_limits',
    '_render_autonomy',
    '_render_critical',
    '_render_examples',
    '_render_interaction_tail',
    '_render_mcp_and_permissions',
    '_render_permissions',
    '_render_runtime_detection_lines',
    '_render_routing',
    '_render_security',
    '_render_system_capabilities',
    '_render_tool_reference',
    '_repo_discovery_contract',
    '_resolve_terminal_command_tool',
    '_routing_memory_tool_placeholders',
]
