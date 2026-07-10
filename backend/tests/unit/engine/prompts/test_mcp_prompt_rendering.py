"""Tests for the MCP system-prompt rendering fixes.

Coverage:
* F1 — disabled servers' ``usage_hint`` is filtered out of the system
  prompt (Rigour, which ships disabled, must not appear).
* F2 — tools whose originating server is a native backend
  (context7, exa, fetch) are hidden from ``mcp_tool_names`` even
  when the alias preparer renamed them.
* B  — the ``<CAPABILITIES>`` block always carries an
  ``External MCP tools`` line whose text matches the live bootstrap
  state, and the ``call_mcp_tool`` gateway description is honest
  about whether any catalogue is connected.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from backend.integrations.mcp import mcp_bootstrap_status as bs_mod


def _base_config(**overrides: Any) -> SimpleNamespace:
    cfg = SimpleNamespace(
        autonomy_level='balanced',
        enable_checkpoints=False,
        enable_lsp_query=False,
        enable_task_tracker_tool=False,
        enable_permissions=False,
        enable_web=True,
        enable_docs=True,
        enable_debugger=False,
        mcp_capability_status=None,
        cli_mode=False,
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


# ── F1: disabled-server hint filtering ──────────────────────────────


class TestDisabledServerHints:
    def test_disabled_server_hint_excluded(self, tmp_path: Any) -> None:
        from backend.utils.prompt import OrchestratorPromptManager

        cfg = _base_config()
        cfg.mcp = SimpleNamespace(
            servers=[
                SimpleNamespace(
                    name='rigour',
                    type='stdio',
                    enabled=False,
                    usage_hint='Rigour local code governance.',
                ),
            ]
        )
        cfg.llm_registry = SimpleNamespace(config=cfg)

        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path), config=cfg)
        orch = SimpleNamespace(llm_registry=cfg.llm_registry)
        from backend.engine.orchestrator_helpers.prompts import (
            _mcp_server_prompt_hints,
        )

        hints = _mcp_server_prompt_hints(orch)
        assert hints == []

    def test_enabled_server_hint_included(self, tmp_path: Any) -> None:

        cfg = _base_config()
        cfg.mcp = SimpleNamespace(
            servers=[
                SimpleNamespace(
                    name='github',
                    type='stdio',
                    enabled=True,
                    usage_hint='GitHub API for repos, issues, PRs.',
                ),
            ]
        )
        cfg.llm_registry = SimpleNamespace(config=cfg)
        orch = SimpleNamespace(llm_registry=cfg.llm_registry)

        from backend.engine.orchestrator_helpers.prompts import (
            _mcp_server_prompt_hints,
        )

        hints = _mcp_server_prompt_hints(orch)
        assert len(hints) == 1
        assert hints[0]['server'] == 'github'


# ── F2: native-server tool hiding via mcp_tool_server_map ────────────


class TestNativeServerToolHiding:
    def test_tools_from_native_server_hidden(self, tmp_path: Any) -> None:
        from backend.utils.prompt import OrchestratorPromptManager

        cfg = _base_config()
        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path), config=cfg)

        # Simulate the rename the alias preparer would apply when a
        # collision happens — the exposed name is *not* the protocol
        # name. The protocol-name filter would miss it; the
        # server-name filter must catch it.
        opm.mcp_tool_names = [
            'context7_resolve-library',  # from context7 (native)
            'github_search',  # from github (user)
            'exa_web_search_exa',  # from exa (native)
        ]
        opm.mcp_tool_server_map = {
            'context7_resolve-library': 'context7',
            'github_search': 'github',
            'exa_web_search_exa': 'exa',
        }
        opm.mcp_tool_descriptions = {
            name: f'desc {name}' for name in opm.mcp_tool_names
        }

        from backend.engine.orchestrator_helpers.prompts import (
            _apply_mcp_tools,
        )

        # Stub the orchestrator; we only need config + mcp_tools.
        class _StubOrch:
            config = cfg
            mcp_tools = {
                name: {'function': {'name': name, 'description': f'd {name}'}}
                for name in opm.mcp_tool_names
            }
            tools: list = []
            llm = None
            llm_registry = SimpleNamespace(config=cfg)

        # Wire the prompt manager into the stub.
        _StubOrch._prompt_manager = opm

        _apply_mcp_tools(_StubOrch(), list(_StubOrch.mcp_tools.values()))

        assert 'context7_resolve-library' not in opm.mcp_tool_names
        assert 'exa_web_search_exa' not in opm.mcp_tool_names
        assert 'github_search' in opm.mcp_tool_names

    def test_tool_with_unknown_server_not_hidden(self, tmp_path: Any) -> None:
        from backend.utils.prompt import OrchestratorPromptManager

        cfg = _base_config()
        opm = OrchestratorPromptManager(prompt_dir=str(tmp_path), config=cfg)
        opm.mcp_tool_names = ['user_tool']
        opm.mcp_tool_server_map = {}  # no map (legacy path / disabled facade)
        opm.mcp_tool_descriptions = {'user_tool': 'd'}

        from backend.engine.orchestrator_helpers.prompts import (
            _apply_mcp_tools,
        )

        class _StubOrch:
            config = cfg
            mcp_tools = {
                'user_tool': {'function': {'name': 'user_tool', 'description': 'd'}}
            }
            tools: list = []
            llm = None
            llm_registry = SimpleNamespace(config=cfg)

        _StubOrch._prompt_manager = opm
        _apply_mcp_tools(_StubOrch(), list(_StubOrch.mcp_tools.values()))

        # When the server map is empty the filter is a no-op; the tool
        # stays visible.
        assert opm.mcp_tool_names == ['user_tool']


# ── B: <MCP_STATUS> capability line + honest gateway description ────


class TestMCPCapabilityStatus:
    def setup_method(self) -> None:
        bs_mod.reset_mcp_bootstrap_status()

    def teardown_method(self) -> None:
        bs_mod.reset_mcp_bootstrap_status()

    def test_capabilities_block_has_empty_state_message(self) -> None:
        from backend.engine.prompts.section_renderers._capabilities import (
            _render_system_capabilities,
        )

        cfg = _base_config()
        # Empty bootstrap = no catalogue.
        out = _render_system_capabilities(
            cfg,
            function_calling_mode='native',
            parallel_tool_calls_provider_flag=True,
            mode='agent',
        )
        assert 'External MCP tools' in out
        assert 'none connected' in out
        assert 'Settings' in out  # points the user at the right panel

    def test_capabilities_block_reports_connected_count(self) -> None:
        from backend.engine.prompts.section_renderers._capabilities import (
            _render_system_capabilities,
        )

        cfg = _base_config(
            mcp_capability_status={
                'state': 'healthy',
                'remote_tool_param_count': 5,
                'connected_client_count': 2,
            }
        )
        out = _render_system_capabilities(
            cfg,
            function_calling_mode='native',
            parallel_tool_calls_provider_flag=True,
            mode='agent',
        )
        assert '5 tools from 2 connected servers' in out

    def test_capabilities_block_reports_mcp_disabled(self) -> None:
        from backend.engine.prompts.section_renderers._capabilities import (
            _render_system_capabilities,
        )

        cfg = _base_config(
            mcp_capability_status={'state': 'mcp_disabled'},
        )
        out = _render_system_capabilities(
            cfg,
            function_calling_mode='native',
            parallel_tool_calls_provider_flag=True,
            mode='agent',
        )
        assert 'disabled' in out
        assert 'External MCP tools' in out

    def test_capabilities_block_reports_mcp_disabled_via_config(self) -> None:
        from backend.engine.prompts.section_renderers._capabilities import (
            _render_system_capabilities,
        )

        cfg = _base_config(
            enable_mcp=False,
        )
        out = _render_system_capabilities(
            cfg,
            function_calling_mode='native',
            parallel_tool_calls_provider_flag=True,
            mode='agent',
        )
        assert 'disabled' in out
        assert 'External MCP tools' in out

    def test_capabilities_block_reports_no_servers_configured(self) -> None:
        from backend.engine.prompts.section_renderers._capabilities import (
            _render_system_capabilities,
        )

        cfg = _base_config(
            mcp_capability_status={'state': 'no_servers_configured'},
        )
        out = _render_system_capabilities(
            cfg,
            function_calling_mode='native',
            parallel_tool_calls_provider_flag=True,
            mode='agent',
        )
        assert 'none configured' in out

    def test_capabilities_block_reports_last_error(self) -> None:
        from backend.engine.prompts.section_renderers._capabilities import (
            _render_system_capabilities,
        )

        cfg = _base_config(
            mcp_capability_status={
                'state': 'no_clients_connected',
                'last_error': 'npx not found on PATH',
            }
        )
        out = _render_system_capabilities(
            cfg,
            function_calling_mode='native',
            parallel_tool_calls_provider_flag=True,
            mode='agent',
        )
        assert 'npx not found on PATH' in out


class TestExecuteMCPToolDescription:
    def test_empty_catalogue_says_no_mcp_connected(self) -> None:
        from backend.engine.tools.execute_mcp_tool import (
            create_execute_mcp_tool_tool,
        )

        cfg = _base_config()  # no mcp_capability_status
        tool = create_execute_mcp_tool_tool(cfg)
        desc = tool['function']['description']
        assert 'No external MCP servers are connected' in desc
        assert 'Settings' in desc

    def test_nonempty_catalogue_keeps_legacy_description(self) -> None:
        from backend.engine.tools.execute_mcp_tool import (
            create_execute_mcp_tool_tool,
        )

        cfg = _base_config(
            mcp_capability_status={
                'state': 'healthy',
                'remote_tool_param_count': 1,
                'connected_client_count': 1,
            }
        )
        tool = create_execute_mcp_tool_tool(cfg)
        desc = tool['function']['description']
        assert 'See the <MCP_TOOLS> section' in desc
        assert 'No external MCP servers' not in desc

    def test_native_facade_hint_dropped_when_docs_disabled(self) -> None:
        from backend.engine.tools.execute_mcp_tool import (
            create_execute_mcp_tool_tool,
        )

        cfg = _base_config(enable_docs=False)
        tool = create_execute_mcp_tool_tool(cfg)
        desc = tool['function']['description']
        assert 'docs_resolve' not in desc
        assert 'docs_query' not in desc

    def test_native_facade_hint_dropped_when_web_disabled(self) -> None:
        from backend.engine.tools.execute_mcp_tool import (
            create_execute_mcp_tool_tool,
        )

        cfg = _base_config(enable_web=False)
        tool = create_execute_mcp_tool_tool(cfg)
        desc = tool['function']['description']
        assert 'web_search' not in desc
        assert 'web_fetch' not in desc

    def test_native_facade_hint_includes_both_when_enabled(self) -> None:
        from backend.engine.tools.execute_mcp_tool import (
            create_execute_mcp_tool_tool,
        )

        cfg = _base_config(enable_web=True, enable_docs=True)
        tool = create_execute_mcp_tool_tool(cfg)
        desc = tool['function']['description']
        assert 'docs_resolve' in desc
        assert 'web_search' in desc

    def test_no_config_uses_neutral_legacy_description(self) -> None:
        """Unit tests that pass ``None`` for config still work."""
        from backend.engine.tools.execute_mcp_tool import (
            create_execute_mcp_tool_tool,
        )

        tool = create_execute_mcp_tool_tool()
        desc = tool['function']['description']
        assert 'See the <MCP_TOOLS> section' in desc
