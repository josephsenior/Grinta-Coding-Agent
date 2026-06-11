"""Integration-style checks for MCP synthetic wrapper tools and discovery params."""

from __future__ import annotations

import pytest

from backend.integrations.mcp.wrappers import WRAPPER_TOOL_REGISTRY, wrapper_tool_params


@pytest.mark.integration
def test_wrapper_tool_registry_maps_cached_names_to_underlying_tools() -> None:
    assert 'get_component_cached' in WRAPPER_TOOL_REGISTRY
    assert 'get_block_cached' in WRAPPER_TOOL_REGISTRY
    assert len(WRAPPER_TOOL_REGISTRY) == 3


@pytest.mark.integration
def test_wrapper_tool_params_emits_component_cached_when_server_exposes_get_component() -> (
    None
):
    params = wrapper_tool_params(['get_component', 'other'])
    names = [p['function']['name'] for p in params]
    assert 'get_component_cached' in names
    assert 'get_block_cached' not in names


@pytest.mark.integration
def test_wrapper_tool_params_emits_both_cached_tools_when_present() -> None:
    params = wrapper_tool_params(['get_component', 'get_block', 'extra'])
    names = {p['function']['name'] for p in params}
    assert names == {'get_component_cached', 'get_block_cached'}
