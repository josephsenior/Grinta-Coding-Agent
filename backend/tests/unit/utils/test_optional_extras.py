"""Tests for optional pip extra detection and runtime gating."""

from __future__ import annotations

from types import SimpleNamespace

from backend.utils import optional_extras as oe


def test_browser_tool_enabled_requires_extra(monkeypatch) -> None:
    cfg = SimpleNamespace(
        default_agent='Orchestrator',
        get_agent_config=lambda _name: SimpleNamespace(enable_browsing=True),
    )
    monkeypatch.setattr(oe, 'is_browser_extra_available', lambda: False)
    assert oe.browser_tool_enabled(cfg) is False
    monkeypatch.setattr(oe, 'is_browser_extra_available', lambda: True)
    assert oe.browser_tool_enabled(cfg) is True


def test_browser_tool_disabled_in_settings(monkeypatch) -> None:
    cfg = SimpleNamespace(
        default_agent='Orchestrator',
        get_agent_config=lambda _name: SimpleNamespace(enable_browsing=False),
    )
    monkeypatch.setattr(oe, 'is_browser_extra_available', lambda: True)
    assert oe.browser_tool_enabled(cfg) is False


def test_vector_memory_enabled_requires_extra_and_flag(monkeypatch) -> None:
    cfg = SimpleNamespace(
        default_agent='Orchestrator',
        get_agent_config=lambda _name: SimpleNamespace(enable_vector_memory=True),
    )
    monkeypatch.setattr(oe, 'is_rag_extra_available', lambda: False)
    assert oe.vector_memory_enabled(cfg) is False
    monkeypatch.setattr(oe, 'is_rag_extra_available', lambda: True)
    assert oe.vector_memory_enabled(cfg) is True


def test_semantic_recall_active_requires_live_store(monkeypatch) -> None:
    cfg = SimpleNamespace(
        default_agent='Orchestrator',
        get_agent_config=lambda _name: SimpleNamespace(enable_vector_memory=True),
    )
    monkeypatch.setattr(oe, 'is_rag_extra_available', lambda: True)
    assert (
        oe.semantic_recall_active(cfg, vector_store=None, require_live_store=True)
        is False
    )
    assert oe.semantic_recall_active(
        cfg, vector_store=object(), require_live_store=True
    )


def test_semantic_recall_active_when_disabled(monkeypatch) -> None:
    cfg = SimpleNamespace(
        default_agent='Orchestrator',
        get_agent_config=lambda _name: SimpleNamespace(enable_vector_memory=False),
    )
    monkeypatch.setattr(oe, 'is_rag_extra_available', lambda: True)
    assert oe.semantic_recall_active(cfg, require_live_store=False) is False


def test_semantic_recall_active_no_live_store_needed(monkeypatch) -> None:
    cfg = SimpleNamespace(
        default_agent='Orchestrator',
        get_agent_config=lambda _name: SimpleNamespace(enable_vector_memory=True),
    )
    monkeypatch.setattr(oe, 'is_rag_extra_available', lambda: True)
    assert oe.semantic_recall_active(cfg, require_live_store=False) is True


def test_resolve_semantic_recall_for_prompt(monkeypatch) -> None:
    cfg = SimpleNamespace(
        default_agent='Orchestrator',
        get_agent_config=lambda _name: SimpleNamespace(enable_vector_memory=True),
    )
    monkeypatch.setattr(oe, 'is_rag_extra_available', lambda: True)

    assert oe.resolve_semantic_recall_for_prompt(cfg, semantic_recall_active=True) is True
    assert oe.resolve_semantic_recall_for_prompt(cfg, semantic_recall_active=False) is False
    assert oe.resolve_semantic_recall_for_prompt(cfg, semantic_recall_active=None) is True


def test_optional_extra_installed_importerrors() -> None:
    from unittest.mock import patch
    import importlib.util

    with patch("importlib.util.find_spec", side_effect=ValueError):
        assert oe._optional_extra_installed("dummy") is False

