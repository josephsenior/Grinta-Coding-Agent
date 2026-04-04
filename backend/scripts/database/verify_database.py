"""Verify database setup."""

import asyncio
import os
import sys
from typing import Any

ASYNCPG_ERROR_MESSAGE = (
    'asyncpg is required for PostgreSQL scripts. '
    "Install it with: uv sync --extra database or pip install 'grinta-ai[database]'"
)

asyncpg: Any | None = None


def _load_asyncpg() -> Any | None:
    try:
        import asyncpg as imported_asyncpg
    except ImportError:
        return None
    return imported_asyncpg


asyncpg = _load_asyncpg()


def _require_asyncpg() -> Any:
    if asyncpg is None:
        raise RuntimeError(ASYNCPG_ERROR_MESSAGE)
    return asyncpg


async def verify():
    """Verify the database setup."""
    asyncpg_module = _require_asyncpg()
    host = os.getenv('DB_HOST', 'localhost')
    port = int(os.getenv('DB_PORT', '5432'))
    database = os.getenv('DB_NAME', 'app')
    user = os.getenv('DB_USER', 'postgres')
    password = os.getenv('DB_PASSWORD', '')

    if not password:
        print('[ERROR] DB_PASSWORD not set')
        return False

    dsn = f'postgresql://{user}:{password}@{host}:{port}/{database}'

    try:
        conn = await asyncpg_module.connect(dsn)

        # Check if table exists
        exists = await conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'users')"
        )

        if not exists:
            print('[ERROR] Users table does not exist')
            await conn.close()
            return False

        # Get columns
        cols = await conn.fetch(
            "SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'users' ORDER BY ordinal_position"
        )

        print('[OK] Database setup verified!')
        print(f'\nDatabase: {database}')
        print('Table: users')
        print(f'\nColumns ({len(cols)}):')
        for col in cols:
            print(f'  - {col["column_name"]} ({col["data_type"]})')

        # Check indexes
        indexes = await conn.fetch(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'users'"
        )
        print(f'\nIndexes ({len(indexes)}):')
        for idx in indexes:
            print(f'  - {idx["indexname"]}')

        await conn.close()
        return True

    except Exception as e:
        print(f'[ERROR] {e}')
        return False


if __name__ == '__main__':
    success = asyncio.run(verify())
    sys.exit(0 if success else 1)
