"""Setup script to create database and run migrations using asyncpg."""

import asyncio
import os
import sys
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    import codecs

    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")

import asyncpg


async def create_database():
    """Create the database if it doesn't exist."""
    # Connect to default postgres database
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "5432"))
    database = "postgres"  # Connect to default database
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "postgres")

    db_name = os.getenv("DB_NAME", "forge")

    dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    print(f"Connecting to PostgreSQL server at {host}:{port}...")

    try:
        conn = await asyncpg.connect(dsn)
        print("✓ Connected to PostgreSQL")

        # Check if database exists
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", db_name
        )

        if exists:
            print(f"✓ Database '{db_name}' already exists")
        else:
            # Create database
            await conn.execute(f'CREATE DATABASE "{db_name}"')
            print(f"✓ Created database '{db_name}'")

        await conn.close()
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


async def run_migrations():
    """Run all migration scripts."""
    # Get database connection parameters
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "5432"))
    database = os.getenv("DB_NAME", "forge")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "postgres")

    dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    print(f"\nConnecting to database '{database}'...")

    try:
        conn = await asyncpg.connect(dsn)
        print("[OK] Connected to database")
    except Exception as e:
        print(f"[ERROR] Error connecting to database: {e}")
        print("\nMake sure PostgreSQL is running and credentials are correct.")
        return False

    # Get migration directory
    project_root = Path(__file__).parent.parent
    migrations_dir = project_root / "forge" / "storage" / "user" / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))

    if not migration_files:
        print("[ERROR] No migration files found!")
        await conn.close()
        return False

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
            return False

    await conn.close()
    print("\n[OK] All migrations completed successfully!")
    return True


async def verify_setup():
    """Verify the setup by checking if users table exists."""
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "5432"))
    database = os.getenv("DB_NAME", "forge")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "postgres")

    dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"

    try:
        conn = await asyncpg.connect(dsn)
        table_exists = await conn.fetchval(
            "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'users')"
        )
        await conn.close()

        if table_exists:
            print("[OK] Users table exists")
            return True
        print("[ERROR] Users table not found")
        return False
    except Exception as e:
        print(f"[ERROR] Error verifying setup: {e}")
        return False


async def main():
    """Main setup function."""
    print("=" * 60)
    print("Forge Database Setup")
    print("=" * 60)
    print()

    # Check environment variables
    db_host = os.getenv("DB_HOST", "localhost")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME", "forge")
    db_user = os.getenv("DB_USER", "postgres")
    db_password = os.getenv("DB_PASSWORD", "")

    print("Database connection settings:")
    print(f"  DB_HOST: {db_host}")
    print(f"  DB_PORT: {db_port}")
    print(f"  DB_NAME: {db_name}")
    print(f"  DB_USER: {db_user}")
    if not db_password:
        print("  DB_PASSWORD: (not set - will prompt if needed)")
    else:
        print(f"  DB_PASSWORD: {'*' * len(db_password)}")
    print()

    if not db_password:
        print("[WARNING] DB_PASSWORD environment variable is not set.")
        print("Please set it in your .env file or environment:")
        print("  DB_PASSWORD=your_postgres_password")
        print()
        print("Or run the script with:")
        print("  $env:DB_PASSWORD='your_password'; python scripts/setup_database.py")
        print()
        return

    # Create database
    if not await create_database():
        sys.exit(1)

    # Run migrations
    if not await run_migrations():
        sys.exit(1)

    # Verify setup
    print("\nVerifying setup...")
    if not await verify_setup():
        sys.exit(1)

    print("\n" + "=" * 60)
    print("[OK] Database setup complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("1. Set USER_STORAGE_TYPE=database in your .env file")
    print("2. Restart your application")
    print()


if __name__ == "__main__":
    asyncio.run(main())
