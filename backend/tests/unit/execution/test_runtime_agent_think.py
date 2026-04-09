from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from backend.execution.base import Runtime
from backend.ledger.action import (
    CmdRunAction,
    FileEditAction,
    FileReadAction,
    FileWriteAction,
)
from backend.ledger.action.agent import AgentThinkAction
from backend.ledger.action.mcp import MCPAction
from backend.ledger.observation import AgentThinkObservation, Observation


class _RuntimeStub(Runtime):
    async def connect(self) -> None:
        return None

    def get_mcp_config(self, extra_servers=None):
        return MagicMock()

    def run(self, action: CmdRunAction) -> Observation:
        raise NotImplementedError

    def read(self, action: FileReadAction) -> Observation:
        raise NotImplementedError

    def write(self, action: FileWriteAction) -> Observation:
        raise NotImplementedError

    def edit(self, action: FileEditAction) -> Observation:
        raise NotImplementedError

    def copy_to(self, host_src: str, runtime_dest: str, recursive: bool = False) -> None:
        raise NotImplementedError

    def copy_from(self, path: str) -> Path:
        raise NotImplementedError

    def list_files(self, path: str, recursive: bool = False) -> list[str]:
        raise NotImplementedError

    async def call_tool_mcp(self, action: MCPAction) -> Observation:
        raise NotImplementedError


def test_run_action_preserves_tool_result_for_tool_backed_think_action() -> None:
    runtime = object.__new__(_RuntimeStub)
    action = AgentThinkAction(thought='[CHECKPOINT] Saved #1: phase 1', source_tool='checkpoint')
    action.tool_result = {'tool': 'checkpoint', 'ok': True, 'status': 'saved'}

    observation = runtime.run_action(action)

    assert isinstance(observation, AgentThinkObservation)
    assert observation.suppress_cli is True
    assert observation.tool_result == action.tool_result
