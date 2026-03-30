#!/usr/bin/env python3
"""Check user storage configuration."""

import os

print("=" * 80)
print("User Storage Configuration Check")
print("=" * 80)

storage_type = os.getenv("USER_STORAGE_TYPE", "NOT SET")
print(f"\nUSER_STORAGE_TYPE: {storage_type}")

if storage_type == "NOT SET":
    print("\n[WARNING] USER_STORAGE_TYPE is not set!")
    print("  Defaulting to 'file' storage (users saved to .app/users/users.json)")
    print("  To use PostgreSQL, set: USER_STORAGE_TYPE=database")
elif storage_type.lower() in ("database", "db"):
    print("\n[OK] Using database storage")
    print(f"  DB_HOST: {os.getenv('DB_HOST', 'NOT SET')}")
    print(f"  DB_PORT: {os.getenv('DB_PORT', 'NOT SET')}")
    print(f"  DB_NAME: {os.getenv('DB_NAME', 'NOT SET')}")
    print(f"  DB_USER: {os.getenv('DB_USER', 'NOT SET')}")
    print(f"  DB_PASSWORD: {'SET' if os.getenv('DB_PASSWORD') else 'NOT SET'}")
else:
    print(f"\n[INFO] Using file storage: {storage_type}")

print("\n" + "=" * 80)
print("To fix disappearing users:")
print("  1. Set USER_STORAGE_TYPE=database in your environment")
print("  2. Ensure DB_* variables are set correctly")
print("  3. Restart your backend server")
print("=" * 80)
