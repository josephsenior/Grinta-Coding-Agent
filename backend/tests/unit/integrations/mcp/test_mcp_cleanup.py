"""Regression tests for the MCP cleanup.

Covers:
  - ``mcp_capabilities_status`` is no longer registered as a wrapper tool.
  - Env values that are empty / ``${VAR}`` are resolved from ``os.environ``
    before being passed to the stdio transport (so secrets from ``.env``
    flow through to MCP children like ``server-github``).
  - The system prompt lists *all* MCP tools (the old 10-item cap is gone)
    and carries an explicit anti-hallucination discipline about tool names.
"""

from __future__ import annotations

import pytest

from backend.integrations.mcp.mcp_utils import _resolve_server_env
from backend.integrations.mcp.wrappers import (
    WRAPPER_TOOL_REGISTRY,
    wrapper_tool_params,
)


class TestWrapperToolRegistry:
    def test_mcp_capabilities_status_is_removed(self) -> None:
        assert 'mcp_capabilities_status' not in WRAPPER_TOOL_REGISTRY

    def test_registry_only_contains_cache_helpers(self) -> None:
        # The surviving wrappers are pure cache/search helpers that the agent
        # can actually use; no meta-diagnostic tools.
        assert set(WRAPPER_TOOL_REGISTRY.keys()) == {
            'search_components',
            'get_component_cached',
            'get_block_cached',
        }

    def test_wrapper_tool_params_does_not_advertise_capabilities_status(
        self,
    ) -> None:
        # No shadcn tools available -> no wrapper params should be emitted
        # (the removed ``mcp_capabilities_status`` used to leak through here).
        params = wrapper_tool_params(available_server_tools=[])
        names = {p['function']['name'] for p in params}
        assert 'mcp_capabilities_status' not in names
        assert names == set()

    def test_wrapper_tool_params_only_when_underlying_present(self) -> None:
        params = wrapper_tool_params(
            available_server_tools=['list_components', 'get_component']
        )
        names = {p['function']['name'] for p in params}
        assert names == {'search_components', 'get_component_cached'}


class TestResolveServerEnv:
    def test_none_input_returns_none(self) -> None:
        assert _resolve_server_env(None) is None

    def test_empty_dict_returns_same_dict(self) -> None:
        assert _resolve_server_env({}) == {}

    def test_empty_value_resolved_from_os_environ(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('GITHUB_PERSONAL_ACCESS_TOKEN', 'ghp_secret')
        resolved = _resolve_server_env({'GITHUB_PERSONAL_ACCESS_TOKEN': ''})
        assert resolved == {'GITHUB_PERSONAL_ACCESS_TOKEN': 'ghp_secret'}

    def test_empty_value_without_os_env_is_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An empty string that also has no backing os.environ entry must be
        # *dropped* (not passed through) so the child process inherits its
        # parent env rather than seeing a literal "" which servers treat as
        # an auth failure.
        monkeypatch.delenv('MISSING_SECRET', raising=False)
        resolved = _resolve_server_env({'MISSING_SECRET': ''})
        assert resolved == {}

    def test_template_var_syntax_resolves(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv('MY_TOKEN', 'abc123')
        resolved = _resolve_server_env({'AUTH': '${MY_TOKEN}'})
        assert resolved == {'AUTH': 'abc123'}

    def test_template_var_missing_is_dropped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv('NOT_SET', raising=False)
        resolved = _resolve_server_env({'AUTH': '${NOT_SET}'})
        assert resolved == {}

    def test_literal_values_pass_through(self) -> None:
        resolved = _resolve_server_env({'FOO': 'bar', 'BAZ': 'qux'})
        assert resolved == {'FOO': 'bar', 'BAZ': 'qux'}

    def test_mixed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv('RESOLVED_TOKEN', 'pat_value')
        monkeypatch.delenv('UNSET_TOKEN', raising=False)
        resolved = _resolve_server_env(
            {
                'LITERAL': 'stays',
                'FROM_EMPTY': '',  # dropped (UNSET_TOKEN not set here)
                'FROM_TEMPLATE': '${RESOLVED_TOKEN}',
                'FROM_MISSING_TEMPLATE': '${UNSET_TOKEN}',
            }
        )
        assert resolved == {
            'LITERAL': 'stays',
            'FROM_TEMPLATE': 'pat_value',
        }


class TestPromptMcpSection:
    def _build(self, mcp_tool_names, mcp_tool_descriptions):
        from backend.engine.prompts.prompt_builder import (
            _render_mcp_and_permissions,
        )

        class _Cfg:
            pass

        return _render_mcp_and_permissions(
            mcp_tool_names=mcp_tool_names,
            mcp_tool_descriptions=mcp_tool_descriptions,
            mcp_server_hints=[],
            config=_Cfg(),
        )

    def test_all_tools_listed_even_beyond_old_cap(self) -> None:
        # The old implementation silently truncated to 10 and told the agent
        # "and N more", which is exactly what caused the hallucinated tool
        # names (context7:search-libraries, etc.) we saw in the wild.
        names = [f'tool_{i}' for i in range(25)]
        descs = {n: f'description for {n}' for n in names}

        text = self._build(names, descs)

        for name in names:
            assert f'`{name}`' in text
        # The old cap messaging must not re-appear.
        assert 'Too many tools to list' not in text
        assert 'Core ones include' not in text

    def test_naming_discipline_guidance_is_present(self) -> None:
        text = self._build(['fetch'], {'fetch': 'Fetch a URL.'})

        # The rule must explicitly forbid the prefixes the agent hallucinated.
        assert 'call_mcp_tool' in text
        assert 'server:' in text
        assert 'server/' in text
        assert 'server__' in text
        assert 'not available in this session' in text or (
            'not available' in text and 'guess' in text.lower()
        )

    def test_no_section_when_no_mcp_tools(self) -> None:
        text = self._build([], {})
        assert 'No external MCP tools connected.' in text
