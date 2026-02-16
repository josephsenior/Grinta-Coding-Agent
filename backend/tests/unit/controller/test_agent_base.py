"""Tests for backend.controller.agent (Agent base class)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from backend.controller.agent import Agent
from backend.core.config.agent_config import AgentConfig
from backend.core.exceptions import (
    AgentAlreadyRegisteredError,
    AgentNotRegisteredError,
)


# ── helpers ──────────────────────────────────────────────────────────

def _make_concrete_agent(name: str = "TestAgent"):
    """Create a concrete Agent subclass for testing."""
    return type(name, (Agent,), {"step": lambda self, state: None})


def _llm_registry():
    reg = MagicMock()
    reg.get_llm_from_agent_config.return_value = MagicMock()
    return reg


# ── registration ─────────────────────────────────────────────────────

class TestAgentRegistry:
    def setup_method(self):
        """Snapshot and restore the registry between tests."""
        self._original = dict(Agent._registry)

    def teardown_method(self):
        Agent._registry = self._original

    def test_register_and_get(self):
        cls = _make_concrete_agent("RegTestAgent")
        Agent.register("reg_test", cls)
        assert Agent.get_cls("reg_test") is cls

    def test_register_duplicate_raises(self):
        cls = _make_concrete_agent("DupAgent")
        Agent.register("dup", cls)
        with pytest.raises(AgentAlreadyRegisteredError):
            Agent.register("dup", cls)

    def test_get_unregistered_raises(self):
        with pytest.raises(AgentNotRegisteredError):
            Agent.get_cls("__nonexistent__")

    def test_list_agents(self):
        cls = _make_concrete_agent("ListAgent")
        Agent.register("list_test", cls)
        names = Agent.list_agents()
        assert "list_test" in names


# ── init and properties ──────────────────────────────────────────────

class TestAgentInit:
    def test_init_basic(self):
        cls = _make_concrete_agent("BasicInitAgent")
        agent = cls(config=AgentConfig(), llm_registry=_llm_registry())
        assert agent.name == "BasicInitAgent"
        assert agent.complete is False
        assert agent.tools == []
        assert agent.mcp_tools == {}

    def test_reset(self):
        cls = _make_concrete_agent()
        agent = cls(config=AgentConfig(), llm_registry=_llm_registry())
        agent._complete = True
        agent.reset()
        assert agent.complete is False

    def test_prompt_manager_uninitialized_raises(self):
        cls = _make_concrete_agent()
        agent = cls(config=AgentConfig(), llm_registry=_llm_registry())
        with pytest.raises(ValueError, match="not initialized"):
            _ = agent.prompt_manager


# ── set_mcp_tools ────────────────────────────────────────────────────

class TestSetMcpTools:
    def test_adds_tools(self):
        cls = _make_concrete_agent()
        agent = cls(config=AgentConfig(), llm_registry=_llm_registry())
        tool_dict = {"function": {"name": "my_tool", "parameters": {}}}
        with patch("backend.controller.agent.build_tool", return_value=tool_dict):
            agent.set_mcp_tools([tool_dict])
        assert "my_tool" in agent.mcp_tools
        assert len(agent.tools) == 1

    def test_skips_duplicate_tool(self):
        cls = _make_concrete_agent()
        agent = cls(config=AgentConfig(), llm_registry=_llm_registry())
        tool_dict = {"function": {"name": "dup_tool", "parameters": {}}}
        with patch("backend.controller.agent.build_tool", return_value=tool_dict):
            agent.set_mcp_tools([tool_dict, tool_dict])
        assert len(agent.tools) == 1

    def test_skips_none_from_build_tool(self):
        cls = _make_concrete_agent()
        agent = cls(config=AgentConfig(), llm_registry=_llm_registry())
        with patch("backend.controller.agent.build_tool", return_value=None):
            agent.set_mcp_tools([{"function": {"name": "x"}}])
        assert len(agent.tools) == 0


# ── get_system_message ───────────────────────────────────────────────

class TestGetSystemMessage:
    def test_with_prompt_manager(self):
        cls = _make_concrete_agent()
        agent = cls(config=AgentConfig(), llm_registry=_llm_registry())
        pm = MagicMock()
        pm.get_system_message.return_value = "You are an assistant."
        agent._prompt_manager = pm

        msg = agent.get_system_message()
        assert msg is not None
        assert msg.content == "You are an assistant."

    def test_without_prompt_manager_returns_none(self):
        cls = _make_concrete_agent()
        agent = cls(config=AgentConfig(), llm_registry=_llm_registry())
        # _prompt_manager is None by default, get_system_message should warn and return None
        msg = agent.get_system_message()
        assert msg is None
