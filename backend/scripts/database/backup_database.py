"""Database backup script for PostgreSQL user storage.

Creates automated backups of the Forge PostgreSQL database.
Supports full backups, incremental backups, and restore operations.

Usage:
    # Full backup
    python scripts/backup_database.py --backup

    # Restore from backup
    python scripts/backup_database.py --restore backup_file.sql

    # List backups
    python scripts/backup_database.py --list

    # Cleanup old backups (keep last 30 days)
    python scripts/backup_database.py --cleanup --days 30
"""

import argparse
import asyncio
import os
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

# Fix Windows console encoding
if sys.platform == "win32":
    import codecs

    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")

import asyncpg


def find_pg_tool(tool_name: str):
    """Find PostgreSQL tool executable (pg_dump, pg_restore, psql) in common installation locations."""
    import shutil

    # Check if tool is in PATH
    tool_path = shutil.which(tool_name)
    if tool_path:
        return tool_path

    # Common Windows PostgreSQL installation paths
    if sys.platform == "win32":
        common_paths = [
            r"C:\Program Files\PostgreSQL\16\bin",
            r"C:\Program Files\PostgreSQL\15\bin",
            r"C:\Program Files\PostgreSQL\14\bin",
            r"C:\Program Files\PostgreSQL\13\bin",
            r"C:\Program Files (x86)\PostgreSQL\16\bin",
            r"C:\Program Files (x86)\PostgreSQL\15\bin",
            r"C:\Program Files (x86)\PostgreSQL\14\bin",
            r"C:\Program Files (x86)\PostgreSQL\13\bin",
            r"C:\PostgreSQL\16\bin",
            r"C:\PostgreSQL\15\bin",
        ]

        # Also check environment variable
        pg_bin = os.getenv("POSTGRES_BIN")
        if pg_bin:
            tool_candidate = Path(pg_bin) / f"{tool_name}.exe"
            if tool_candidate.exists():
                return str(tool_candidate)

        # Try to find in common paths
        for bin_path in common_paths:
            tool_candidate = Path(bin_path) / f"{tool_name}.exe"
            if tool_candidate.exists():
                return str(tool_candidate)

    return None


def find_pg_dump():
    """Find pg_dump executable."""
    return find_pg_tool("pg_dump")


# Configuration
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", "./backups"))
BACKUP_RETENTION_DAYS = int(os.getenv("BACKUP_RETENTION_DAYS", "30"))


async def get_db_connection():
    """Get database connection from environment variables."""
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "5432"))
    database = os.getenv("DB_NAME", "forge")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "")

    if not password:
        print("ERROR: DB_PASSWORD environment variable is required")
        sys.exit(1)

    dsn = f"postgresql://{user}:{password}@{host}:{port}/{database}"
    return await asyncpg.connect(dsn)


async def create_backup():
    """Create a full database backup."""
    print("Creating database backup...")
    print(f"Backup directory: {BACKUP_DIR}")

    # Ensure backup directory exists
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # Generate backup filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = BACKUP_DIR / f"forge_backup_{timestamp}.sql"

    try:
        conn = await get_db_connection()

        # Get database name
        db_name = os.getenv("DB_NAME", "forge")

        # Use pg_dump via subprocess (more reliable than asyncpg for backups)
        import subprocess

        host = os.getenv("DB_HOST", "localhost")
        port = os.getenv("DB_PORT", "5432")
        user = os.getenv("DB_USER", "postgres")
        password = os.getenv("DB_PASSWORD", "")

        # Set PGPASSWORD environment variable for pg_dump
        env = os.environ.copy()
        env["PGPASSWORD"] = password

        # Find pg_dump executable
        pg_dump_exe = find_pg_dump()
        if not pg_dump_exe:
            print("ERROR: pg_dump not found. Please install PostgreSQL client tools.")
            print("  On Ubuntu/Debian: sudo apt-get install postgresql-client")
            print("  On macOS: brew install postgresql")
            print(
                "  On Windows: Install PostgreSQL from https://www.postgresql.org/download/"
            )
            print(
                "  Or set POSTGRES_BIN environment variable to PostgreSQL bin directory"
            )
            sys.exit(1)

        # Run pg_dump
        cmd = [
            pg_dump_exe,
            "-h",
            host,
            "-p",
            port,
            "-U",
            user,
            "-d",
            db_name,
            "-F",
            "c",  # Custom format (compressed)
            "-f",
            str(backup_file),
        ]

        print(f"Running pg_dump ({pg_dump_exe})...")
        result = subprocess.run(
            cmd, check=False, env=env, capture_output=True, text=True
        )

        if result.returncode != 0:
            print("ERROR: Backup failed")
            print(f"stderr: {result.stderr}")
            sys.exit(1)

        # Also create a plain SQL backup for easier inspection
        sql_backup_file = BACKUP_DIR / f"forge_backup_{timestamp}.sql"
        cmd_sql = [
            pg_dump_exe,
            "-h",
            host,
            "-p",
            port,
            "-U",
            user,
            "-d",
            db_name,
            "-F",
            "p",  # Plain SQL format
            "-f",
            str(sql_backup_file),
        ]

        result_sql = subprocess.run(
            cmd_sql, check=False, env=env, capture_output=True, text=True
        )

        if result_sql.returncode != 0:
            print("WARNING: SQL backup failed (custom format backup succeeded)")
            print(f"stderr: {result_sql.stderr}")
        else:
            print(f"✓ Created SQL backup: {sql_backup_file}")

        await conn.close()

        # Get file size
        file_size = backup_file.stat().st_size / (1024 * 1024)  # MB
        print(f"✓ Backup created successfully: {backup_file}")
        print(f"  Size: {file_size:.2f} MB")
        print("  Format: Custom (compressed)")

        return backup_file

    except FileNotFoundError:
        print("ERROR: pg_dump not found. Please install PostgreSQL client tools.")
        print("  On Ubuntu/Debian: sudo apt-get install postgresql-client")
        print("  On macOS: brew install postgresql")
        print(
            "  On Windows: Install PostgreSQL from https://www.postgresql.org/download/"
        )
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Backup failed: {e}")
        sys.exit(1)


def _build_restore_env() -> dict[str, str]:
    """Build environment for restore with DB credentials."""
    env = os.environ.copy()
    env["PGPASSWORD"] = os.getenv("DB_PASSWORD", "")
    return env


def _build_restore_cmd(
    backup_path: Path,
    pg_restore_exe: str | None,
    psql_exe: str | None,
) -> list[str]:
    """Build restore command (pg_restore or psql) based on backup format."""
    host = os.getenv("DB_HOST", "localhost")
    port = os.getenv("DB_PORT", "5432")
    user = os.getenv("DB_USER", "postgres")
    db_name = os.getenv("DB_NAME", "forge")
    is_custom = backup_path.suffix == ".sql" and backup_path.stat().st_size < 1000
    if is_custom or backup_path.suffix == ".dump":
        return [
            pg_restore_exe, "-h", host, "-p", port, "-U", user,
            "-d", db_name, "--clean", "--if-exists", str(backup_path),
        ]
    return [
        psql_exe, "-h", host, "-p", port, "-U", user,
        "-d", db_name, "-f", str(backup_path),
    ]


async def restore_backup(backup_file: str):
    """Restore database from backup file."""
    backup_path = Path(backup_file)
    if not backup_path.exists():
        print(f"ERROR: Backup file not found: {backup_file}")
        sys.exit(1)

    print("WARNING: This will overwrite the current database!")
    print(f"Backup file: {backup_file}")
    if input("Are you sure you want to continue? (yes/no): ").lower() != "yes":
        print("Restore cancelled.")
        return

    try:
        pg_restore_exe = find_pg_tool("pg_restore")
        psql_exe = find_pg_tool("psql")
        if not pg_restore_exe or not psql_exe:
            print("ERROR: pg_restore/psql not found. Please install PostgreSQL client tools.")
            print("  Or set POSTGRES_BIN environment variable to PostgreSQL bin directory")
            sys.exit(1)

        cmd = _build_restore_cmd(backup_path, pg_restore_exe, psql_exe)
        env = _build_restore_env()
        print("Restoring backup...")
        result = subprocess.run(cmd, check=False, env=env, capture_output=True, text=True)

        if result.returncode != 0:
            print("ERROR: Restore failed")
            print(f"stderr: {result.stderr}")
            sys.exit(1)
        print(f"✓ Database restored successfully from {backup_file}")
    except FileNotFoundError:
        print("ERROR: pg_restore/psql not found. Please install PostgreSQL client tools.")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Restore failed: {e}")
        sys.exit(1)


def list_backups():
    """List all available backups."""
    if not BACKUP_DIR.exists():
        print(f"No backup directory found: {BACKUP_DIR}")
        return

    backups = sorted(BACKUP_DIR.glob("forge_backup_*.sql"), reverse=True)
    backups.extend(sorted(BACKUP_DIR.glob("forge_backup_*.dump"), reverse=True))

    if not backups:
        print("No backups found.")
        return

    print(f"Found {len(backups)} backup(s):\n")
    for backup in backups:
        stat = backup.stat()
        size_mb = stat.st_size / (1024 * 1024)
        mtime = datetime.fromtimestamp(stat.st_mtime)
        age = datetime.now() - mtime

        print(f"  {backup.name}")
        print(f"    Size: {size_mb:.2f} MB")
        print(
            f"    Created: {mtime.strftime('%Y-%m-%d %H:%M:%S')} ({age.days} days ago)"
        )
        print()


def cleanup_old_backups(days: int = BACKUP_RETENTION_DAYS):
    """Remove backups older than specified days."""
    if not BACKUP_DIR.exists():
        print(f"No backup directory found: {BACKUP_DIR}")
        return

    cutoff_date = datetime.now() - timedelta(days=days)
    backups = list(BACKUP_DIR.glob("forge_backup_*.*"))

    old_backups = [
        b for b in backups if datetime.fromtimestamp(b.stat().st_mtime) < cutoff_date
    ]

    if not old_backups:
        print(f"No backups older than {days} days found.")
        return

    print(f"Found {len(old_backups)} backup(s) older than {days} days:")
    for backup in old_backups:
        mtime = datetime.fromtimestamp(backup.stat().st_mtime)
        print(f"  {backup.name} ({mtime.strftime('%Y-%m-%d')})")

    response = input(f"\nDelete these {len(old_backups)} backup(s)? (yes/no): ")
    if response.lower() == "yes":
        for backup in old_backups:
            backup.unlink()
            print(f"  Deleted: {backup.name}")
        print(f"\n✓ Cleaned up {len(old_backups)} old backup(s)")
    else:
        print("Cleanup cancelled.")


async def main():
    parser = argparse.ArgumentParser(description="Forge Database Backup Tool")
    parser.add_argument("--backup", action="store_true", help="Create a new backup")
    parser.add_argument("--restore", type=str, help="Restore from backup file")
    parser.add_argument("--list", action="store_true", help="List all backups")
    parser.add_argument("--cleanup", action="store_true", help="Clean up old backups")
    parser.add_argument(
        "--days",
        type=int,
        default=BACKUP_RETENTION_DAYS,
        help="Days to keep backups (default: 30)",
    )

    args = parser.parse_args()

    if args.backup:
        await create_backup()
    elif args.restore:
        await restore_backup(args.restore)
    elif args.list:
        list_backups()
    elif args.cleanup:
        cleanup_old_backups(args.days)
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
