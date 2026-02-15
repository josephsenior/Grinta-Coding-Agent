#!/usr/bin/env python3
"""Script to query users directly from PostgreSQL database using SQL.

This script connects directly to the database and runs SQL queries.
"""

import asyncio
import os
import sys
from pathlib import Path

from typing import Any

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import asyncpg  # noqa: E402


def _print_table_structure(columns: list[Any]) -> None:
    """Print the database table structure."""
    print("\nUsers Table Structure:")
    print(f"{'Column':<25} {'Type':<20} {'Nullable':<10} {'Default':<20}")
    print("-" * 75)
    for col in columns:
        default = (col["column_default"] or "")[:18]
        null_status = "NULL" if col["is_nullable"] == "YES" else "NOT NULL"
        print(
            f"{col['column_name']:<25} {col['data_type']:<20} {null_status:<10} {default:<20}"
        )


def _format_user_row(row: Any) -> list[Any]:
    """Format a single user database row for display."""

    def fmt_dt(dt, alt="N/A"):
        return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else alt

    return [
        str(row["id"])[:8] + "...",
        row["email"],
        row["username"],
        row["role"],
        "Yes" if row["email_verified"] else "No",
        "Yes" if row["is_active"] else "No",
        fmt_dt(row["created_at"]),
        fmt_dt(row["updated_at"]),
        fmt_dt(row["last_login"], "Never"),
        row["failed_login_attempts"],
        fmt_dt(row["locked_until"], "Not locked"),
    ]


def _print_users_table(users: list[Any]) -> None:
    """Print the users summary table."""
    headers = [
        "ID (truncated)",
        "Email",
        "Username",
        "Role",
        "Verified",
        "Active",
        "Created At",
        "Updated At",
        "Last Login",
        "Failed Logins",
        "Locked Until",
    ]
    col_widths = [12, 30, 20, 10, 8, 8, 19, 19, 19, 12, 19]

    print("\nUsers in Database:")
    header_row = " | ".join(
        h.ljust(w) for h, w in zip(headers, col_widths, strict=False)
    )
    print(header_row)
    print("-" * len(header_row))

    for row in users:
        formatted = _format_user_row(row)
        data_row = " | ".join(
            str(cell).ljust(w)[:w]
            for cell, w in zip(formatted, col_widths, strict=False)
        )
        print(data_row)


async def query_users_sql():
    """Query users directly from PostgreSQL."""
    try:
        # Get connection parameters from environment
        dsn = (
            f"postgresql://{os.getenv('DB_USER', 'forge')}:"
            f"{os.getenv('DB_PASSWORD', 'forge')}@"
            f"{os.getenv('DB_HOST', 'localhost')}:"
            f"{os.getenv('DB_PORT', '5432')}/"
            f"{os.getenv('DB_NAME', 'forge')}"
        )

        print(f"Connecting to database: {os.getenv('DB_NAME', 'forge')}...")
        conn = await asyncpg.connect(dsn)

        try:
            if not await conn.fetchval(
                "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'users')"
            ):
                print("\n[WARNING] The 'users' table does not exist.")
                return

            # Show structure
            columns = await conn.fetch(
                "SELECT column_name, data_type, is_nullable, column_default "
                "FROM information_schema.columns WHERE table_name = 'users' ORDER BY ordinal_position"
            )
            _print_table_structure(columns)

            # Count and Show Users
            user_count = await conn.fetchval("SELECT COUNT(*) FROM users")
            print(f"\nTotal Users: {user_count}")

            if user_count > 0:
                users = await conn.fetch("SELECT * FROM users ORDER BY created_at DESC")
                _print_users_table(users)

                if len(sys.argv) > 1 and sys.argv[1] == "--full-ids":
                    print("\nFull User IDs:")
                    for row in users:
                        print(f"  {row['email']}: {row['id']}")
            else:
                print("No users found in the database.")

        finally:
            await conn.close()
            print("\n[OK] Database connection closed.")

    except asyncpg.exceptions.InvalidPasswordError:
        print("[ERROR] Invalid database password.", file=sys.stderr)
        print("   Please check your DB_PASSWORD environment variable.", file=sys.stderr)
        sys.exit(1)
    except asyncpg.exceptions.ConnectionDoesNotExistError:
        print("[ERROR] Could not connect to database.", file=sys.stderr)
        print("   Please check your database connection settings:", file=sys.stderr)
        print(f"   DB_HOST={os.getenv('DB_HOST', 'localhost')}", file=sys.stderr)
        print(f"   DB_PORT={os.getenv('DB_PORT', '5432')}", file=sys.stderr)
        print(f"   DB_NAME={os.getenv('DB_NAME', 'forge')}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(query_users_sql())
