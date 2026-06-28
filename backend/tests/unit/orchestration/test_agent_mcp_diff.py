"""Unit tests for the diff-aware :class:`Agent.set_mcp_tools`."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from backend.orchestration.agent import Agent
from backend.orchestration.agent.tools import build_tool


class _RecordingAgent(Agent):
    """Concrete ``Agent`` used to exercise the diff helper in isolation."""

    DEPRECATED = False

    def __init__(self) -> None:
        # Skip Agent.__init__; we are not testing the full agent.
        self.mcp_tools: dict[str, Any] = {}
        self.tools: list[Any] = []
        self.mcp_capability_status: dict[str, Any] | None = None
        self.llm = None
        self.llm_registry = None
        self.config = SimpleNamespace(name='recording')

    async def step(self, *_args: Any, **_kwargs: Any) -> None:  # pragma: no cover
        return None

    @property
    def name(self) -> str:
        return 'recording'


def _tool_dict(name: str) -> dict[str, Any]:
    return {
        'type': 'function',
        'function': {
            'name': name,
            'description': f'desc {name}',
            'parameters': {
                'type': 'object',
                'properties': {},
            },
        },
    }


def test_set_mcp_tools_first_add() -> None:
    agent = _RecordingAgent()
    diff = agent.set_mcp_tools([_tool_dict('a'), _tool_dict('b')])
    assert diff['added'] == ['a', 'b']
    assert diff['removed'] == []
    assert diff['unchanged'] == []
    assert set(agent.mcp_tools) == {'a', 'b'}


def test_set_mcp_tools_removes_orphans() -> None:
    agent = _RecordingAgent()
    agent.set_mcp_tools([_tool_dict('a'), _tool_dict('b')])
    diff = agent.set_mcp_tools([_tool_dict('b')])
    assert diff['added'] == []
    assert diff['removed'] == ['a']
    assert diff['unchanged'] == ['b']
    assert set(agent.mcp_tools) == {'b'}


def test_set_mcp_tools_noop_on_identical_input() -> None:
    agent = _RecordingAgent()
    agent.set_mcp_tools([_tool_dict('a'), _tool_dict('b')])
    diff = agent.set_mcp_tools([_tool_dict('a'), _tool_dict('b')])
    assert diff['added'] == []
    assert diff['removed'] == []
    assert set(diff['unchanged']) == {'a', 'b'}


def test_set_mcp_tools_keeps_existing_in_prompt_toolset() -> None:
    """Non-MCP tools on ``self.tools`` must survive an MCP refresh."""
    agent = _RecordingAgent()
    # Pretend the agent already has a built-in tool on its visible
    # toolset (e.g. ``run``).
    built = build_tool(_tool_dict('run'))
    assert built is not None
    agent.tools = [built]

    agent.set_mcp_tools([_tool_dict('mcp_a')])
    # After adding MCP tool, the visible toolset still has 'run' but
    # not 'mcp_a' (MCP tools are routed through the gateway, not added
    # to self.tools).
    assert 'run' in {t['function']['name'] for t in agent.tools}
    assert 'mcp_a' not in {t['function']['name'] for t in agent.tools}

    # After removing the MCP tool, the visible toolset must NOT gain
    # 'mcp_a' (no leak), and 'run' must still be there.
    agent.set_mcp_tools([])
    assert 'run' in {t['function']['name'] for t in agent.tools}
    assert 'mcp_a' not in {t['function']['name'] for t in agent.tools}


def test_unset_mcp_tools_specific_names() -> None:
    agent = _RecordingAgent()
    agent.set_mcp_tools([_tool_dict('a'), _tool_dict('b')])
    removed = agent.unset_mcp_tools(['a'])
    assert removed == ['a']
    assert set(agent.mcp_tools) == {'b'}


def test_unset_mcp_tools_all_when_none() -> None:
    agent = _RecordingAgent()
    agent.set_mcp_tools([_tool_dict('a'), _tool_dict('b')])
    removed = agent.unset_mcp_tools()
    assert sorted(removed) == ['a', 'b']
    assert agent.mcp_tools == {}


def test_set_mcp_tools_with_invalid_tool_skipped() -> None:
    agent = _RecordingAgent()
    # No ``function`` key → ``build_tool`` returns None and the row
    # is dropped (must not be registered or counted as added).
    bad = {'type': 'function'}
    diff = agent.set_mcp_tools([_tool_dict('a'), bad])
    assert diff['added'] == ['a']
    assert 'broken' not in agent.mcp_tools
    assert set(agent.mcp_tools) == {'a'}
