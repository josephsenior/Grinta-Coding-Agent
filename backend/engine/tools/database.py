"""Database tools for Orchestrator agent."""

from backend.engine.tools.common import create_tool_definition
from backend.engine.contracts import ChatCompletionToolParam


# Tool for connecting to databases using environment variables
def create_database_connect_tool() -> ChatCompletionToolParam:
    """Create the database connect tool."""
    return create_tool_definition(
        name="database_connect",
        description="""Connect to a database using credentials from environment variables.

The connection uses environment variables with a specified prefix:
- PostgreSQL: {PREFIX}_HOST, {PREFIX}_PORT, {PREFIX}_DATABASE, {PREFIX}_USER, {PREFIX}_PASSWORD
- MongoDB: {PREFIX}_CONNECTION_STRING or {PREFIX}_HOST, {PREFIX}_PORT, {PREFIX}_DATABASE
- Redis: {PREFIX}_HOST, {PREFIX}_PORT, {PREFIX}_PASSWORD (optional)
- MySQL: {PREFIX}_HOST, {PREFIX}_PORT, {PREFIX}_DATABASE, {PREFIX}_USER, {PREFIX}_PASSWORD

Example: If env_prefix is "PROD_DB", it will look for PROD_DB_HOST, PROD_DB_PORT, etc.

The connection is established in the runtime environment, so credentials never leave the user's infrastructure.""",
        properties={
            "connection_name": {
                "type": "string",
                "description": 'Unique name for this connection (e.g., "prod_postgres", "staging_mongo")',
            },
            "db_type": {
                "type": "string",
                "enum": ["postgresql", "mongodb", "mysql", "redis"],
                "description": "Type of database to connect to",
            },
            "env_prefix": {
                "type": "string",
                "description": 'Environment variable prefix (e.g., "PROD_DB", "STAGING_DB")',
            },
        },
        required=["connection_name", "db_type", "env_prefix"],
    )


# Tool for fetching database schema
def create_database_schema_tool() -> ChatCompletionToolParam:
    """Create the database schema tool."""
    return create_tool_definition(
        name="database_schema",
        description="""Fetch the schema of a database connection.

For SQL databases (PostgreSQL, MySQL):
- Returns list of tables with columns, types, indexes, and foreign keys

For MongoDB:
- Returns list of collections with sample documents

For Redis:
- Returns list of keys with types and TTL

This helps understand the database structure before writing queries.""",
        properties={
            "connection_name": {
                "type": "string",
                "description": "Name of the established connection",
            },
        },
        required=["connection_name"],
    )


# Tool for executing database queries
def create_database_query_tool() -> ChatCompletionToolParam:
    """Create the database query tool."""
    return create_tool_definition(
        name="database_query",
        description="""Execute a query against a database connection.

Query formats by database type:

PostgreSQL/MySQL:
- Use standard SQL: "SELECT * FROM users WHERE age > 18 LIMIT 10"
- Supports SELECT, INSERT, UPDATE, DELETE

MongoDB:
- Use JSON format: {"collection": "users", "filter": {"age": {"$gt": 18}}, "limit": 10}
- Supports find queries with MongoDB operators

Redis:
- Use Redis commands: "GET mykey" or "HGETALL user:1001" or "LRANGE mylist 0 10"

Returns query results with execution time and row count.""",
        properties={
            "connection_name": {
                "type": "string",
                "description": "Name of the established connection",
            },
            "query": {
                "type": "string",
                "description": "The query to execute (format depends on database type)",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of rows to return (default: 100)",
                "default": 100,
            },
        },
        required=["connection_name", "query"],
    )


def get_database_tools() -> list[ChatCompletionToolParam]:
    """Get all database tools for the Orchestrator agent."""
    return [
        create_database_connect_tool(),
        create_database_schema_tool(),
        create_database_query_tool(),
    ]
