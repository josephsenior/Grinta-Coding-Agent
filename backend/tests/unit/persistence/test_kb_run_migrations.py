from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest


@pytest.fixture
def rm():
    fake_asyncpg = type('FakeAsyncPg', (), {'connect': AsyncMock()})()
    sys.modules.pop(
        'backend.persistence.knowledge_base.migrations.run_migrations', None
    )
    with patch.dict(sys.modules, {'asyncpg': fake_asyncpg}):
        mod = importlib.import_module(
            'backend.persistence.knowledge_base.migrations.run_migrations'
        )
        yield mod


@pytest.mark.asyncio
async def test_run_migrations_no_files(
    rm, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = AsyncMock()
    monkeypatch.setenv('DB_NAME', 'dbx')
    monkeypatch.setenv('DB_USER', 'ux')
    monkeypatch.setenv('DB_PASSWORD', 'px')
    monkeypatch.setenv('DB_HOST', 'hx')
    monkeypatch.setenv('DB_PORT', '5432')

    with (
        patch.object(rm, '__file__', str(tmp_path / 'run_migrations.py')),
        patch.object(rm.asyncpg, 'connect', AsyncMock(return_value=conn)),
    ):
        await rm.run_migrations()

    conn.execute.assert_not_called()
    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_migrations_executes_sql_files(rm, tmp_path: Path) -> None:
    (tmp_path / '001_init.sql').write_text('select 1;', encoding='utf-8')
    (tmp_path / '002_more.sql').write_text('select 2;', encoding='utf-8')
    conn = AsyncMock()

    with (
        patch.object(rm, '__file__', str(tmp_path / 'run_migrations.py')),
        patch.object(rm.asyncpg, 'connect', AsyncMock(return_value=conn)),
    ):
        await rm.run_migrations()

    assert conn.execute.await_count == 2
    conn.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_migrations_connection_failure_exits(rm, tmp_path: Path) -> None:
    with (
        patch.object(rm, '__file__', str(tmp_path / 'run_migrations.py')),
        patch.object(
            rm.asyncpg, 'connect', AsyncMock(side_effect=RuntimeError('db down'))
        ),
        patch('sys.exit', side_effect=SystemExit(1)),
    ):
        with pytest.raises(SystemExit):
            await rm.run_migrations()


@pytest.mark.asyncio
async def test_run_migrations_file_execution_failure_exits(rm, tmp_path: Path) -> None:
    (tmp_path / '001_init.sql').write_text('bad sql', encoding='utf-8')
    conn = AsyncMock()
    conn.execute = AsyncMock(side_effect=RuntimeError('syntax error'))

    with (
        patch.object(rm, '__file__', str(tmp_path / 'run_migrations.py')),
        patch.object(rm.asyncpg, 'connect', AsyncMock(return_value=conn)),
        patch('sys.exit', side_effect=SystemExit(1)),
    ):
        with pytest.raises(SystemExit):
            await rm.run_migrations()
    conn.close.assert_awaited_once()
