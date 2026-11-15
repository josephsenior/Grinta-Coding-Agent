"""Prompt + MCP helpers extracted from :class:`Orchestrator`."""

from __future__ import annotations

import contextlib
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.engine.orchestrator import Orchestrator
    from backend.orchestration.state.state import State
    from backend.utils.prompt import PromptManager


def _create_prompt_manager(orch: Orchestrator) -> PromptManager:
    from backend.utils.prompt import OrchestratorPromptManager

    prompt_dir = os.path.join(os.path.dirname(__file__), 'prompts')

    resolved_model = ''
    with contextlib.suppress(Exception):
        resolved_model = (orch.llm.config.model or '').strip()
    if not resolved_model and orch.llm_registry:
        with contextlib.suppress(Exception):
            llm_cfg = orch.llm_registry.config.get_llm_config_from_agent_config(
                orch.config
            )
            if llm_cfg and getattr(llm_cfg, 'model', None):
                resolved_model = str(llm_cfg.model).strip()
    return OrchestratorPromptManager(
        prompt_dir=prompt_dir,
        config=orch.config,
        resolved_llm_model_id=resolved_model or None,
        app_config=orch.llm_registry.config if orch.llm_registry else None,
    )


def _set_prompt_tier_from_recent_history(orch: Orchestrator, state: State) -> None:
    """Escalate to debug tier on recent errors or elevated-risk file operations."""
    with contextlib.suppress(Exception):
        from backend.core.enums import ActionSecurityRisk
        from backend.ledger.action import FileEditAction
        from backend.ledger.observation import ErrorObservation

        recent = state.history[-12:] if len(state.history) > 12 else state.history
        if any(
            isinstance(e, ErrorObservation) and not getattr(e, 'notify_ui_only', False)
            for e in recent
        ):
            orch.prompt_manager.set_prompt_tier('debug')
            return
        for e in recent:
            if isinstance(e, FileEditAction):
                risk = getattr(e, 'security_risk', ActionSecurityRisk.UNKNOWN)
                if risk in (ActionSecurityRisk.MEDIUM, ActionSecurityRisk.HIGH):
                    orch.prompt_manager.set_prompt_tier('debug')
                    return
        orch.prompt_manager.set_prompt_tier('base')


def _mcp_server_hint_row(server: object) -> dict[str, str] | None:
    from backend.integrations.mcp.native_backends import is_user_visible_mcp_server

    name = (getattr(server, 'name', None) or '').strip() or 'unknown'
    if not is_user_visible_mcp_server(name):
        return None
    if not bool(getattr(server, 'enabled', True)):
        return None
    hint = (getattr(server, 'usage_hint', None) or '').strip()
    if not hint:
        return None
    return {'server': name, 'hint': hint}


def _mcp_server_prompt_hints(orch: Orchestrator) -> list[dict[str, str]]:
    """Build ``[{"server": name, "hint": text}, ...]`` from MCP ``usage_hint`` fields.

    Only *enabled* user-facing servers are included. Disabled servers
    (e.g. Rigour, which ships disabled in :mod:`mcp_defaults`) must
    not appear in the system prompt — otherwise the model reasons
    about tools it cannot actually call.
    """
    try:
        app_cfg = getattr(orch.llm_registry, 'config', None)
        mcp = getattr(app_cfg, 'mcp', None) if app_cfg is not None else None
        servers = getattr(mcp, 'servers', None) or []
        rows: list[dict[str, str]] = []
        for s in servers:
            row = _mcp_server_hint_row(s)
            if row is not None:
                rows.append(row)
        return rows
    except Exception:
        return []


def _mcp_tool_descriptions_from_specs(mcp_tools: list[dict]) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    for tool_dict in mcp_tools:
        fn = tool_dict.get('function') or {}
        name = fn.get('name') or tool_dict.get('name', '')
        desc = fn.get('description') or tool_dict.get('description', '')
        if name and desc:
            descriptions[name] = desc.split('\n')[0][:120]
    return descriptions


def _mcp_hidden_facade_tools(
    orch: Orchestrator, hidden: frozenset[str]
) -> frozenset[str]:
    if not getattr(orch.config, 'enable_web', True):
        from backend.integrations.mcp.native_backends import (
            MCP_TOOLS_HIDDEN_BY_NATIVE_WEB,
        )

        hidden = hidden - MCP_TOOLS_HIDDEN_BY_NATIVE_WEB
    if not getattr(orch.config, 'enable_docs', True):
        from backend.integrations.mcp.native_backends import (
            MCP_TOOLS_HIDDEN_BY_NATIVE_DOCS,
        )

        hidden = hidden - MCP_TOOLS_HIDDEN_BY_NATIVE_DOCS
    return hidden


def _visible_mcp_tool_names(
    orch: Orchestrator,
    pm: object,
    *,
    native_facades_on: bool,
    native_server_names: frozenset[str],
    hidden_facade_tools: frozenset[str],
) -> list[str]:
    server_map: dict[str, str] = dict(getattr(pm, 'mcp_tool_server_map', {}) or {})
    visible_names = [
        name
        for name in orch.mcp_tools.keys()
        if server_map.get(name, '') not in native_server_names
    ]
    if not native_facades_on:
        return visible_names
    hidden = _mcp_hidden_facade_tools(orch, hidden_facade_tools)
    return [name for name in visible_names if name not in hidden]


def _apply_mcp_tool_descriptions(
    orch: Orchestrator,
    pm: object,
    mcp_tools: list[dict],
    visible_names: list[str],
) -> None:
    descriptions = _mcp_tool_descriptions_from_specs(mcp_tools)
    if hasattr(pm, 'mcp_tool_descriptions'):
        pm.mcp_tool_descriptions = {
            name: descriptions[name] for name in visible_names if name in descriptions
        }
    if hasattr(pm, 'mcp_server_hints'):
        pm.mcp_server_hints = _mcp_server_prompt_hints(orch)


def _apply_mcp_tools(orch: Orchestrator, mcp_tools: list[dict]) -> None:
    """Sync MCP tool names + descriptions onto the prompt manager.

    The visible name set is the intersection of:

    1. Every tool currently in ``orch.mcp_tools`` (live catalogue).
    2. Excluding any tool whose originating server is in
       :data:`NATIVE_MCP_SERVER_NAMES` (context7, exa, fetch). Native
       servers power the ``docs_*`` / ``web_*`` facade tools; their
       MCP-side twins must not also surface under the model-callable
       tool list.
    3. Excluding any tool name in
       :data:`MCP_TOOLS_HIDDEN_BY_NATIVE_FACADES` (defense in depth
       for the rare case where a user installs a non-native server
       that happens to ship a tool with the same name).
    4. Excluding tools whose server or docs/web facade is disabled in
       the agent config.
    """
    from backend.engine.tool_registry import (
        validate_mcp_tool_name_collisions,
    )
    from backend.integrations.mcp.native_backends import (
        NATIVE_MCP_SERVER_NAMES,
    )

    validate_mcp_tool_name_collisions(
        orch.tools,
        orch.mcp_tools.keys(),
        strict=bool(getattr(orch.config, 'strict_mcp_tool_name_collision', False)),
    )
    pm = getattr(orch, '_prompt_manager', None)
    if not pm or not hasattr(pm, 'mcp_tool_names'):
        return

    from backend.integrations.mcp.native_backends import (
        MCP_TOOLS_HIDDEN_BY_NATIVE_FACADES,
    )

    native_facades_on = bool(getattr(orch.config, 'enable_web', True)) or bool(
        getattr(orch.config, 'enable_docs', True)
    )
    pm.mcp_tool_names = _visible_mcp_tool_names(
        orch,
        pm,
        native_facades_on=native_facades_on,
        native_server_names=NATIVE_MCP_SERVER_NAMES,
        hidden_facade_tools=MCP_TOOLS_HIDDEN_BY_NATIVE_FACADES,
    )
    _apply_mcp_tool_descriptions(orch, pm, mcp_tools, pm.mcp_tool_names)
