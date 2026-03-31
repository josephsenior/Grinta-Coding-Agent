"""Run database migrations for knowledge base storage.

Usage:
    python -m app.storage.knowledge_base.migrations.run_migrations
"""

import asyncio
import os
import sys
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    import codecs

    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")

try:
    import asyncpg
except ImportError as _exc:
    raise ImportError(
        "asyncpg is required for database migrations. "
        "Install with:  uv pip install 'app-ai[database]'"
    ) from _exc


async def run_migrations():
    """Run all migration scripts in order."""
    # Get database connection parameters
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "5432"))
    database = os.getenv("DB_NAME", "app")
    user = os.getenv("DB_USER", "app")
    password = os.getenv("DB_PASSWORD", "app")

    # Build connection string
    dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    print(f"Connecting to database: {database}@{host}:{port}")

    try:
        conn = await asyncpg.connect(dsn)
        print("Connected successfully!")
    except Exception as e:
        print(f"Error connecting to database: {e}")
        print("\nMake sure PostgreSQL is running and the database exists.")
        print("You can create the database with:")
        print(f"  createdb -U {user} {database}")
        sys.exit(1)

    # Get migration directory
    migrations_dir = Path(__file__).parent
    migration_files = sorted(migrations_dir.glob("*.sql"))

    if not migration_files:
        print("No migration files found!")
        await conn.close()
        return

    print(f"\nFound {len(migration_files)} migration(s) to run:")
    for f in migration_files:
        print(f"  - {f.name}")

    # Run migrations
    for migration_file in migration_files:
        print(f"\nRunning migration: {migration_file.name}")
        try:
            sql = migration_file.read_text()
            await conn.execute(sql)
            print(f"[OK] Migration {migration_file.name} completed successfully")
        except Exception as e:
            print(f"[ERROR] Error running migration {migration_file.name}: {e}")
            await conn.close()
            sys.exit(1)

    await conn.close()
    print("\n[OK] All migrations completed successfully!")


if __name__ == "__main__":
    asyncio.run(run_migrations())
