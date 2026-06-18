"""Tests for shared debugger/LSP-related alias maps."""

from __future__ import annotations

from backend.utils.lsp.language_tool_aliases import (
    DEBUG_ADAPTER_SYNONYMS,
    normalize_debug_adapter_name,
)


def test_normalize_pwa_node_to_javascript() -> None:
    assert normalize_debug_adapter_name('pwa-node') == 'javascript'
    assert normalize_debug_adapter_name('  PWA-NODE ') == 'javascript'


def test_normalize_passthrough_unknown() -> None:
    assert normalize_debug_adapter_name('python') == 'python'
    assert normalize_debug_adapter_name('go') == 'go'


def test_synonyms_dict_has_expected_keys() -> None:
    assert 'pwa-node' in DEBUG_ADAPTER_SYNONYMS
