from __future__ import annotations

import asyncio
import json

from backend.orchestration import blackboard as blackboard_module
from backend.orchestration.blackboard import Blackboard


def test_blackboard_persists_under_app_dir(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )

    async def _test():
        board = Blackboard()
        await board.set('schema', 'ok')
        await board.flush()

    asyncio.run(_test())

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


def test_blackboard_rejects_oversized_value(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )

    async def _test():
        board = Blackboard()
        oversized = 'x' * (blackboard_module.MAX_BLACKBOARD_VALUE_BYTES + 1)
        try:
            await board.set('large', oversized)
        except ValueError as exc:
            assert 'value too large' in str(exc)
        else:  # pragma: no cover - guard should always reject
            raise AssertionError('oversized blackboard value was accepted')

    asyncio.run(_test())


def test_blackboard_skips_oversized_existing_data(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        'backend.core.workspace_resolution.workspace_agent_state_dir',
        lambda project_root=None: tmp_path,
    )
    blackboard_file = tmp_path / 'blackboard.json'
    blackboard_file.write_text(
        json.dumps(
            {
                'ok': 'ready',
                'too_large': 'x' * (blackboard_module.MAX_BLACKBOARD_VALUE_BYTES + 1),
            }
        ),
        encoding='utf-8',
    )

    board = Blackboard()

    assert asyncio.run(board.get('ok')) == 'ready'
    assert asyncio.run(board.get('too_large')) == ''
