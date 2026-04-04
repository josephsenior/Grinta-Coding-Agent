"""Database helper library for App agent runtime.

This library provides database connection and query functions that execute
in the user's runtime environment, ensuring credentials never leave their infrastructure.

Usage:
    from app_database import connect_postgresql, query_postgresql

    conn = await connect_postgresql('PROD_DB')
    results = await query_postgresql(conn, 'SELECT * FROM users LIMIT 10')
"""

import json
import os
from typing import Any

# Global connection registry
_connections: dict[str, dict[str, Any]] = {}


async def connect_postgresql(env_prefix: str, connection_name: str) -> dict[str, Any]:
    """Connect to PostgreSQL using environment variables.

    Required environment variables:
    - {env_prefix}_HOST
    - {env_prefix}_PORT (default: 5432)
    - {env_prefix}_DATABASE
    - {env_prefix}_USER
    - {env_prefix}_PASSWORD
    - {env_prefix}_SSL (optional, default: prefer)

    Args:
        env_prefix: Prefix for environment variables (e.g., 'PROD_DB')
        connection_name: Unique name for this connection

    Returns:
        Connection info dict

    """
    try:
        import asyncpg  # type: ignore[import-not-found, import-untyped]
    except ImportError as exc:
        msg = (
            'asyncpg not installed. Run: uv sync --extra database or '
            "pip install 'grinta-ai[database]'"
        )
        raise ImportError(msg) from exc

    # Get connection parameters from environment
    host = os.getenv(f'{env_prefix}_HOST')
    port = int(os.getenv(f'{env_prefix}_PORT', '5432'))
    database = os.getenv(f'{env_prefix}_DATABASE')
    user = os.getenv(f'{env_prefix}_USER')
    password = os.getenv(f'{env_prefix}_PASSWORD')
    ssl = os.getenv(f'{env_prefix}_SSL', 'prefer')

    # Validate required variables
    if not all([host, database, user, password]):
        msg = (
            f'Missing required environment variables. Need: {env_prefix}_HOST, '
            f'{env_prefix}_DATABASE, {env_prefix}_USER, {env_prefix}_PASSWORD'
        )
        raise ValueError(
            msg,
        )

    # Connect
    conn = await asyncpg.connect(
        host=host,
        port=port,
        database=database,
        user=user,
        password=password,
        ssl=ssl,
        timeout=10.0,
    )

    # Store connection
    _connections[connection_name] = {
        'type': 'postgresql',
        'conn': conn,
        'env_prefix': env_prefix,
    }

    return {
        'success': True,
        'connection_name': connection_name,
        'db_type': 'postgresql',
        'host': host,
        'database': database,
    }


async def connect_mongodb(env_prefix: str, connection_name: str) -> dict[str, Any]:
    """Connect to MongoDB using environment variables.

    Required environment variables (Option 1 - Connection String):
    - {env_prefix}_CONNECTION_STRING

    OR (Option 2 - Individual params):
    - {env_prefix}_HOST
    - {env_prefix}_PORT (default: 27017)
    - {env_prefix}_DATABASE
    - {env_prefix}_USER (optional)
    - {env_prefix}_PASSWORD (optional)

    Args:
        env_prefix: Prefix for environment variables
        connection_name: Unique name for this connection

    Returns:
        Connection info dict

    """
    try:
        from motor.motor_asyncio import (
            AsyncIOMotorClient,  # type: ignore[import-not-found, import-untyped]
        )
    except ImportError as exc:
        msg = 'motor not installed. Run: pip install motor'
        raise ImportError(msg) from exc

    # Try connection string first
    conn_str = os.getenv(f'{env_prefix}_CONNECTION_STRING')

    if conn_str:
        client: Any = AsyncIOMotorClient(conn_str, serverSelectionTimeoutMS=10000)
    else:
        # Build from individual params
        host = os.getenv(f'{env_prefix}_HOST', 'localhost')
        port = int(os.getenv(f'{env_prefix}_PORT', '27017'))
        database = os.getenv(f'{env_prefix}_DATABASE')
        user = os.getenv(f'{env_prefix}_USER')
        password = os.getenv(f'{env_prefix}_PASSWORD')

        if not database:
            msg = f'Missing {env_prefix}_DATABASE environment variable'
            raise ValueError(msg)

        if user and password:
            conn_str = f'mongodb://{user}:{password}@{host}:{port}/{database}'
        else:
            conn_str = f'mongodb://{host}:{port}/{database}'

        client = AsyncIOMotorClient(conn_str, serverSelectionTimeoutMS=10000)

    # Test connection
    await client.admin.command('ping')

    # Store connection
    db_name = os.getenv(f'{env_prefix}_DATABASE') or client.get_default_database().name
    _connections[connection_name] = {
        'type': 'mongodb',
        'client': client,
        'db': client[db_name],
        'env_prefix': env_prefix,
    }

    return {
        'success': True,
        'connection_name': connection_name,
        'db_type': 'mongodb',
        'database': db_name,
    }


async def connect_redis(env_prefix: str, connection_name: str) -> dict[str, Any]:
    """Connect to Redis using environment variables.

    Required environment variables:
    - {env_prefix}_HOST
    - {env_prefix}_PORT (default: 6379)
    - {env_prefix}_PASSWORD (optional)

    Args:
        env_prefix: Prefix for environment variables
        connection_name: Unique name for this connection

    Returns:
        Connection info dict

    """
    try:
        import redis.asyncio as redis  # type: ignore[import-not-found, import-untyped]
    except ImportError as exc:
        msg = (
            'redis not installed. Run: uv sync --extra redis or '
            "pip install 'grinta-ai[redis]'"
        )
        raise ImportError(msg) from exc

    host = os.getenv(f'{env_prefix}_HOST', 'localhost')
    port = int(os.getenv(f'{env_prefix}_PORT', '6379'))
    password = os.getenv(f'{env_prefix}_PASSWORD')

    # Connect
    client = redis.Redis(
        host=host,
        port=port,
        password=password,
        decode_responses=True,
        socket_connect_timeout=10,
    )

    # Test connection
    await client.ping()

    # Store connection
    _connections[connection_name] = {
        'type': 'redis',
        'client': client,
        'env_prefix': env_prefix,
    }

    return {
        'success': True,
        'connection_name': connection_name,
        'db_type': 'redis',
        'host': host,
        'port': port,
    }


async def get_schema(connection_name: str) -> dict[str, Any]:
    """Get schema for a database connection.

    Args:
        connection_name: Name of the established connection

    Returns:
        Schema information dict

    """
    if connection_name not in _connections:
        msg = f"Connection '{connection_name}' not found. Connect first using database_connect."
        raise ValueError(msg)

    conn_info = _connections[connection_name]
    db_type = conn_info['type']

    if db_type == 'postgresql':
        return await _get_postgresql_schema(conn_info['conn'])
    if db_type == 'mongodb':
        return await _get_mongodb_schema(conn_info['db'])
    if db_type == 'redis':
        return await _get_redis_schema(conn_info['client'])
    msg = f'Unsupported database type: {db_type}'
    raise ValueError(msg)


async def execute_query(
    connection_name: str, query: str, limit: int = 100
) -> dict[str, Any]:
    """Execute a query on a database connection.

    Args:
        connection_name: Name of the established connection
        query: Query to execute (format depends on database type)
        limit: Maximum number of results to return

    Returns:
        Query results dict with data, columns, row_count, execution_time

    """
    import time

    if connection_name not in _connections:
        msg = f"Connection '{connection_name}' not found. Connect first using database_connect."
        raise ValueError(msg)

    conn_info = _connections[connection_name]
    db_type = conn_info['type']

    start_time = time.time()

    try:
        if db_type == 'postgresql':
            result = await _execute_postgresql_query(conn_info['conn'], query, limit)
        elif db_type == 'mongodb':
            result = await _execute_mongodb_query(conn_info['db'], query, limit)
        elif db_type == 'redis':
            result = await _execute_redis_command(conn_info['client'], query)
        else:
            msg = f'Unsupported database type: {db_type}'
            raise ValueError(msg)

        execution_time = round((time.time() - start_time) * 1000, 2)  # ms
        result['execution_time_ms'] = execution_time

        return result

    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'execution_time_ms': round((time.time() - start_time) * 1000, 2),
        }


# PostgreSQL helper functions
async def _get_postgresql_schema(conn) -> dict[str, Any]:
    """Get PostgreSQL schema."""
    # Fetch all tables
    tables_query = """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name;
    """
    tables_result = await conn.fetch(tables_query)

    tables = []
    for table_row in tables_result:
        table_name = table_row['table_name']

        # Fetch columns
        columns_query = """
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = $1
            ORDER BY ordinal_position;
        """
        columns_result = await conn.fetch(columns_query, table_name)

        # Get row count
        try:
            count = await conn.fetchval(f'SELECT COUNT(*) FROM "{table_name}"')
        except Exception:
            count = None

        tables.append(
            {
                'name': table_name,
                'columns': [
                    {
                        'name': c['column_name'],
                        'type': c['data_type'],
                        'nullable': c['is_nullable'] == 'YES',
                    }
                    for c in columns_result
                ],
                'row_count': count,
            },
        )

    return {'tables': tables}


async def _execute_postgresql_query(conn, query: str, limit: int) -> dict[str, Any]:
    """Execute PostgreSQL query."""
    # Add LIMIT if SELECT and no LIMIT specified
    if 'SELECT' in query.upper() and 'LIMIT' not in query.upper():
        query = f'{query.rstrip(";")} LIMIT {limit}'

    rows = await conn.fetch(query)

    if rows:
        data = [dict(row) for row in rows]
        # Convert non-JSON types to strings
        for row in data:
            for key, value in row.items():
                if value is not None and not isinstance(
                    value, str | int | float | bool | type(None)
                ):
                    row[key] = str(value)

        return {
            'success': True,
            'data': data,
            'columns': list(data[0].keys()),
            'row_count': len(data),
        }
    return {
        'success': True,
        'data': [],
        'columns': [],
        'row_count': 0,
        'message': 'Query executed successfully (no rows returned)',
    }


# MongoDB helper functions
async def _get_mongodb_schema(db) -> dict[str, Any]:
    """Get MongoDB schema."""
    collection_names = await db.list_collection_names()

    collections = []
    for coll_name in collection_names:
        collection = db[coll_name]

        # Get count and sample
        try:
            count = await collection.count_documents({})
            sample = await collection.find_one()
            if sample and '_id' in sample:
                sample['_id'] = str(sample['_id'])
        except Exception:
            count = None
            sample = None

        collections.append(
            {
                'name': coll_name,
                'document_count': count,
                'sample_document': sample,
            },
        )

    return {'collections': collections}


async def _execute_mongodb_query(db, query: str, limit: int) -> dict[str, Any]:
    """Execute MongoDB query."""
    try:
        query_obj = json.loads(query)
    except json.JSONDecodeError:
        return {
            'success': False,
            'error': 'Invalid JSON query. Use: {"collection": "users", "filter": {}, "limit": 10}',
        }

    collection_name = query_obj.get('collection')
    filter_obj = query_obj.get('filter', {})
    query_limit = query_obj.get('limit', limit)

    if not collection_name:
        return {
            'success': False,
            'error': 'Query must include "collection" field',
        }

    collection = db[collection_name]
    cursor = collection.find(filter_obj).limit(query_limit)
    documents = await cursor.to_list(length=query_limit)

    # Convert ObjectId to string
    for doc in documents:
        if '_id' in doc:
            doc['_id'] = str(doc['_id'])

    return {
        'success': True,
        'data': documents,
        'columns': list(documents[0].keys()) if documents else [],
        'row_count': len(documents),
    }


# Redis helper functions
async def _get_redis_schema(client) -> dict[str, Any]:
    """Get Redis keys."""
    keys_list = []
    cursor = 0
    count = 0
    max_keys = 100

    while count < max_keys:
        cursor, keys = await client.scan(cursor=cursor, count=10)

        for key in keys:
            if count >= max_keys:
                break

            key_type = await client.type(key)
            ttl = await client.ttl(key)

            keys_list.append(
                {
                    'key': key,
                    'type': key_type,
                    'ttl': ttl,
                },
            )
            count += 1

        if cursor == 0:
            break

    return {'keys': keys_list}


async def _execute_redis_command(client, command: str) -> dict[str, Any]:
    """Execute Redis command."""
    parts = command.strip().split()
    if not parts:
        return {
            'success': False,
            'error': 'Empty command',
        }

    cmd = parts[0].upper()
    args = parts[1:]

    result = await client.execute_command(cmd, *args)

    # Format result
    if result is None:
        data = [{'result': 'nil'}]
    elif isinstance(result, list | tuple):
        data = [{'index': str(i), 'value': str(v)} for i, v in enumerate(result)]
    elif isinstance(result, dict):
        data = [{'key': k, 'value': str(v)} for k, v in result.items()]
    else:
        data = [{'result': str(result)}]

    return {
        'success': True,
        'data': data,
        'columns': list(data[0].keys()) if data else [],
        'row_count': len(data),
    }


def get_connection(connection_name: str) -> dict[str, Any]:
    """Get an established connection by name."""
    if connection_name not in _connections:
        msg = f"Connection '{connection_name}' not found"
        raise ValueError(msg)
    return _connections[connection_name]


def list_connections() -> list[str]:
    """List all established connection names."""
    return list(_connections.keys())


async def close_connection(connection_name: str) -> None:
    """Close a database connection."""
    if connection_name not in _connections:
        return

    conn_info = _connections[connection_name]

    if conn_info['type'] == 'postgresql':
        await conn_info['conn'].close()
    elif conn_info['type'] == 'mongodb':
        conn_info['client'].close()
    elif conn_info['type'] == 'redis':
        await conn_info['client'].close()

    del _connections[connection_name]


async def close_all_connections() -> None:
    """Close all database connections."""
    for name in list(_connections.keys()):
        await close_connection(name)
