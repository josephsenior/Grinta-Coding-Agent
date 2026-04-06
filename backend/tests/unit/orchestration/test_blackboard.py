from __future__ import annotations

import asyncio
import json

from backend.orchestration.blackboard import Blackboard


def test_blackboard_persists_under_app_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )

    board = Blackboard()
    asyncio.run(board.set('schema', 'ok'))

    blackboard_file = tmp_path / 'blackboard.json'
    assert blackboard_file.exists()
    assert json.loads(blackboard_file.read_text(encoding='utf-8')) == {'schema': 'ok'}


def test_blackboard_loads_existing_app_data(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    blackboard_file = tmp_path / 'blackboard.json'
    blackboard_file.parent.mkdir(parents=True, exist_ok=True)
    blackboard_file.write_text(json.dumps({'status': 'ready'}), encoding='utf-8')

    board = Blackboard()

    assert asyncio.run(board.get('status')) == 'ready'
