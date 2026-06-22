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
