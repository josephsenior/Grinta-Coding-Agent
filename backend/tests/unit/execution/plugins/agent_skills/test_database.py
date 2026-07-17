import os
from unittest.mock import AsyncMock, patch

import pytest

from backend.execution.plugins.agent_skills.database import (
    _connections,
    connect_postgresql,
)


@pytest.mark.asyncio
async def test_connect_postgresql_missing_deps():
    with patch.dict('sys.modules', {'asyncpg': None}):
        with pytest.raises(ImportError, match='asyncpg not installed'):
            await connect_postgresql('TEST', 'conn1')


@pytest.mark.asyncio
async def test_connect_postgresql_missing_env():
    # Provide asyncpg mock
    mock_asyncpg = AsyncMock()
    with patch.dict('sys.modules', {'asyncpg': mock_asyncpg}):
        with pytest.raises(ValueError, match='Missing required environment variables'):
            await connect_postgresql('TEST', 'conn1')


@pytest.mark.asyncio
async def test_connect_postgresql_success():
    mock_asyncpg = AsyncMock()
    mock_conn = AsyncMock()
    mock_asyncpg.connect.return_value = mock_conn

    env = {
        'TEST_HOST': 'localhost',
        'TEST_DATABASE': 'mydb',
        'TEST_USER': 'myuser',
        'TEST_PASSWORD': 'mypassword',
    }
    with (
        patch.dict('sys.modules', {'asyncpg': mock_asyncpg}),
        patch.dict(os.environ, env),
    ):
        result = await connect_postgresql('TEST', 'conn_success')
        assert result['success'] is True
        assert result['connection_name'] == 'conn_success'
        assert _connections['conn_success']['conn'] == mock_conn
