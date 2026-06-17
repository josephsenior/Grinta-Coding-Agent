from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from backend.execution.base import Runtime
from backend.ledger.action import (
    CmdRunAction,
    FileEditAction,
    FileReadAction,
)
from backend.ledger.action.mcp import MCPAction
from backend.ledger.observation import FileEditObservation, Observation


class _RuntimeStub(Runtime):
    async def connect(self) -> None:
        return None

    def get_mcp_config(self, extra_servers=None):
        return MagicMock()

    def run(self, action: CmdRunAction) -> Observation:
        raise NotImplementedError

    def read(self, action: FileReadAction) -> Observation:
        raise NotImplementedError

    def edit(self, action: FileEditAction) -> Observation:
        raise NotImplementedError

    def copy_to(
        self, host_src: str, runtime_dest: str, recursive: bool = False
    ) -> None:
        raise NotImplementedError

    def copy_from(self, path: str) -> Path:
        raise NotImplementedError

    def list_files(self, path: str, recursive: bool = False) -> list[str]:
        raise NotImplementedError

    async def call_tool_mcp(self, action: MCPAction) -> Observation:
        raise NotImplementedError


def _make_runtime(workspace: Path) -> _RuntimeStub:
    runtime = object.__new__(_RuntimeStub)
    runtime.workspace_root = workspace
    return runtime


def test_enhance_observation_preserves_file_edit_fields(tmp_path: Path) -> None:
    runtime = _make_runtime(tmp_path)
    file_path = tmp_path / 'demo.md'
    file_path.write_text('# Demo\nline two\n', encoding='utf-8')

    observation = FileEditObservation(
        content='File created successfully. Line endings: \\n. File preview:\n1\t# Demo',
        path='demo.md',
        outcome='created',
        old_content=None,
        new_content='# Demo\nline two',
    )

    enhanced = runtime._enhance_observation_with_line_count(
        observation,
        'demo.md',
        file_path,
    )

    assert enhanced is observation
    assert isinstance(enhanced, FileEditObservation)
    assert enhanced.new_content == '# Demo\nline two'
    assert enhanced.old_content is None
    assert enhanced.outcome == 'created'
    assert 'File written: demo.md (2 lines)' in enhanced.content
    assert enhanced.content.startswith('File created successfully.')
